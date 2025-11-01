from flask import Flask, jsonify, render_template, request
from pathlib import Path
from typing import Optional, List, Dict, Any
import threading
from datetime import date
import subprocess
import sys
import tempfile
import unicodedata
import pandas as pd
from dateutil import parser as date_parser

# 正規化済み台帳ファイルや変換スクリプトのパスを定義
DATA_FILE = Path(__file__).parent / "normalized_ledgers.tsv"
DATA_DIR = Path(__file__).parent / "data"
NORMALIZE_SCRIPT = Path(__file__).parent / "normalize.py"
_PURCHASE_LEDGER_FILENAME = "買掛台帳.TXT"
_SALES_LEDGER_FILENAME = "売掛台帳.TXT"
DATA_LOCK = threading.Lock()

app = Flask(__name__)

# 読み込み済みデータをキャッシュして再計算を抑制する
_df_cache: Optional[pd.DataFrame] = None


def _infer_date(value: Any) -> Optional[pd.Timestamp]:
	# 多様な日付表記を pandas Timestamp に変換する
	if pd.isna(value):
		return None
	try:
		return pd.to_datetime(value)
	except Exception:
		try:
			return pd.to_datetime(date_parser.parse(str(value), dayfirst=False, yearfirst=True))
		except Exception:
			return None


_SEARCH_EXCLUDE_COLUMNS = {"search_index"}
_SPACE_CHARACTERS = (" ", "\u3000")


def _normalize_for_search(value: Any) -> str:
	# 検索用に全角・半角や空白を正規化し大文字化する
	try:
		if pd.isna(value):
			return ""
	except TypeError:
		if value is None:
			return ""
	text = str(value)
	text = unicodedata.normalize("NFKC", text)
	for ch in _SPACE_CHARACTERS:
		text = text.replace(ch, "")
	return text.upper()


def _build_search_index(df: pd.DataFrame) -> pd.Series:
	# 各カラムを検索用に正規化したテキストとして結合する
	combined = pd.Series("", index=df.index, dtype="object")
	for column in df.columns:
		if column in _SEARCH_EXCLUDE_COLUMNS:
			continue
		combined = combined + df[column].map(_normalize_for_search)
	return combined


def load_data(force: bool = False) -> pd.DataFrame:
	# TSV を読み込み、検索や絞り込みに使いやすい形に整形する
	global _df_cache
	with DATA_LOCK:
		if _df_cache is not None and not force:
			return _df_cache
		if not DATA_FILE.exists():
			raise FileNotFoundError(f"Data file not found: {DATA_FILE}")
		# UTF-8 などのヘッダー付きTSVを想定して読み込む
		df = pd.read_csv(DATA_FILE, sep="\t", dtype=str, keep_default_na=False).replace({"": pd.NA})
		# 既存のカラムを標準化し、リポジトリ想定のカラム名に揃える
		standard_names = {
			"date": ["date", "日付", "伝票日付", "transaction_date"],
			"type": ["type", "種別", "区分", "ledger_type", "entry_type"],
			"counterparty": [
				"counterparty",
				"相手先",
				"得意先",
				"仕入先",
				"supplier_name",
				"customer_name",
			],
			"item": ["item", "品目", "摘要", "品名", "description"],
			"amount": ["amount", "金額", "税込金額", "税抜金額"],
			"quantity": ["quantity", "数量"],
			"document_id": [
				"document_id",
				"伝票番号",
				"請求番号",
				"reference_1",
				"reference_2",
				"reference_3",
				"reference_4",
				"reference_5",
			],
			"memo": ["memo", "備考", "メモ", "description_raw", "quantity_note"],
		}
		cols: Dict[str, Optional[str]] = {}
		for canon, candidates in standard_names.items():
			cols[canon] = next((c for c in candidates if c in df.columns), None)
		# 不明なカラムを落とさず標準化済みデータフレームを組み立てる
		normalized = pd.DataFrame()
		for canon, src in cols.items():
			if src is not None:
				normalized[canon] = df[src]
			else:
				normalized[canon] = pd.NA
		# document_id が reference_* に分かれている場合は結合する
		if "document_id" in normalized.columns and "reference_1" in df.columns:
			refs = df[[c for c in ["reference_1", "reference_2", "reference_3", "reference_4", "reference_5"] if c in df.columns]]
			normalized["document_id"] = (
				normalized["document_id"].fillna("")
				.where(normalized["document_id"].notna(), "")
			)
			joined = refs.fillna("").agg(lambda r: "-".join([x for x in r if x]), axis=1)
			normalized["document_id"] = normalized["document_id"].where(normalized["document_id"].astype(str) != "", joined)

		# 日付と数値列を解析して型を揃える
		normalized["date_parsed"] = normalized["date"].map(_infer_date)
		if "unit_price" not in normalized.columns:
			normalized["unit_price"] = pd.NA
		for num_col in ["amount", "quantity", "unit_price"]:
			normalized[num_col] = pd.to_numeric(normalized[num_col], errors="coerce")
		mask_compute = (
			normalized["unit_price"].isna()
			& normalized["amount"].notna()
			& normalized["quantity"].notna()
			& normalized["quantity"].ne(0)
		)
		if mask_compute.any():
			normalized.loc[mask_compute, "unit_price"] = normalized.loc[mask_compute, "amount"] / normalized.loc[mask_compute, "quantity"]
		# 仕入／売上の区分を揃えた文字列に変換する
		def _normalize_type(v: Any) -> str:
			vs = str(v).strip() if not pd.isna(v) else ""
			if vs in ["買掛", "仕入", "Purchase", "purchase", "buy", "supplier_detail", "supplier_balance", "opening_balance"]:
				return "purchase"
			if vs in ["売掛", "販売", "Sales", "sales", "sale", "customer_detail", "customer_balance"]:
				return "sale"
			return vs.lower() or "unknown"
		normalized["type_norm"] = normalized["type"].map(_normalize_type)
		# 元のカラムも失われないよう統合する
		for c in df.columns:
			if c not in normalized.columns:
				normalized[c] = df[c]
		if "ledger_type" not in normalized.columns:
			normalized["ledger_type"] = normalized["type"]
		else:
			normalized["ledger_type"] = normalized["ledger_type"].fillna(normalized["type"])
		ref_cols = [c for c in ["reference_1", "reference_2", "reference_3", "reference_4", "reference_5"] if c in normalized.columns]
		memo_cols = ref_cols + ([c for c in ["quantity_note"] if c in normalized.columns])
		if memo_cols:
			def _join_refs(row: pd.Series) -> str:
				values = []
				for col in memo_cols:
					val = row.get(col, pd.NA)
					if pd.isna(val):
						continue
					text = str(val).strip()
					if text:
						values.append(text)
				return " ".join(values)
			normalized["memo_combined"] = normalized.apply(_join_refs, axis=1)
		else:
			normalized["memo_combined"] = ""
		# 取引行以外のヘッダー行が明示されていれば除外する
		if "entry_type" in df.columns:
			non_tx = {"supplier_header", "customer_header"}
			mask = ~df["entry_type"].isin(non_tx)
			normalized = normalized[mask]
		normalized["search_index"] = _build_search_index(normalized)
	_df_cache = normalized
	return _df_cache


def _run_normalize_script(src: Path, dest: Path) -> None:
	# 個別台帳を正規化スクリプトで TSV に変換する
	cmd = [sys.executable, str(NORMALIZE_SCRIPT), str(src), "--output", str(dest)]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	if proc.returncode != 0:
		stdout_text = proc.stdout.decode("utf-8", errors="ignore")
		stderr_text = proc.stderr.decode("utf-8", errors="ignore")
		message = stderr_text or stdout_text or f"exit code {proc.returncode}"
		raise RuntimeError(f"Failed to normalize {src.name}: {message}")


def _regenerate_normalized_ledgers() -> None:
	# 元データを一時ディレクトリで正規化し、統合ファイルを更新する
	purchase_path = DATA_DIR / _PURCHASE_LEDGER_FILENAME
	sales_path = DATA_DIR / _SALES_LEDGER_FILENAME
	missing: List[str] = []
	if not purchase_path.exists():
		missing.append(str(purchase_path))
	if not sales_path.exists():
		missing.append(str(sales_path))
	if missing:
		raise FileNotFoundError("Missing ledger sources: " + ", ".join(missing))
	with tempfile.TemporaryDirectory() as tmpdir:
		tmpdir_path = Path(tmpdir)
		purchase_tmp = tmpdir_path / "purchase.tsv"
		sales_tmp = tmpdir_path / "sales.tsv"
		_run_normalize_script(purchase_path, purchase_tmp)
		_run_normalize_script(sales_path, sales_tmp)
		with purchase_tmp.open("r", encoding="utf-8-sig") as purchase_fh:
			purchase_content = purchase_fh.read()
		with sales_tmp.open("r", encoding="utf-8-sig") as sales_fh:
			sales_lines = sales_fh.readlines()
	with DATA_FILE.open("w", encoding="utf-8-sig", newline="") as out_fh:
		out_fh.write(purchase_content)
		if sales_lines:
			out_fh.writelines(sales_lines[1:])


@app.get("/")
def index():
	# データファイルが存在するか事前に読み込みを試行して検証する
	try:
		_ = load_data()
	except Exception:
		pass
	today = date.today()
	try:
		start_date = today.replace(year=today.year - 3)
	except ValueError:
		start_date = today.replace(year=today.year - 3, day=28)
	default_end = today.isoformat()
	default_start = start_date.isoformat()
	return render_template("index.html", default_start=default_start, default_end=default_end)


@app.get("/api/transactions")
def api_transactions():
	df = load_data()
	query: pd.DataFrame = df
	# クエリパラメータからフィルター条件を組み立てる
	start = request.args.get("start_date")
	end = request.args.get("end_date")
	types = request.args.getlist("type")  # 例: ["sale", "purchase"]
	keyword = request.args.get("q")

	if start:
		start_ts = _infer_date(start)
		if start_ts is not None:
			query = query[query["date_parsed"].ge(start_ts)]
	if end:
		end_ts = _infer_date(end)
		if end_ts is not None:
			query = query[query["date_parsed"].le(end_ts)]
	if types:
		query = query[query["type_norm"].isin(types)]
	if keyword:
		kw_normalized = _normalize_for_search(keyword)
		if kw_normalized:
			mask = query["search_index"].str.contains(kw_normalized, na=False)
			query = query[mask]
	doc_id = request.args.get("document_id")
	doc_date = request.args.get("document_date")
	if doc_id:
		query = query[query["document_id"].fillna("").astype(str) == doc_id]
	if doc_date:
		doc_ts = _infer_date(doc_date)
		if doc_ts is not None:
			query = query[query["date_parsed"].eq(doc_ts)]

	# 日付の降順・伝票番号の昇順で並べ替える
	query = query.sort_values(by=["date_parsed", "document_id"], ascending=[False, True], na_position="last")
	# UI が必要とするカラムのみを返却する
	fields: List[str] = [
		"date",
		"ledger_type",
		"document_id",
		"counterparty",
		"item",
		"quantity",
		"unit_price",
		"amount",
		"memo_combined",
	]
	base = query[fields].copy()
	base = base.rename(columns={"memo_combined": "memo"})
	# 品名と備考を結合した列を作成
	base["item_memo"] = base.apply(lambda row: 
		f"{row['item'] if pd.notna(row['item']) and str(row['item']).strip() else ''}<br />{row['memo'] if pd.notna(row['memo']) and str(row['memo']).strip() else ''}".strip("<br />"), 
		axis=1)
	# amount と payment を合計した total_amount を計算
	payment_col = "payment" if "payment" in query.columns else None
	if payment_col:
		base["total_amount"] = (
			pd.to_numeric(base["amount"], errors="coerce").fillna(0) + 
			pd.to_numeric(query["payment"], errors="coerce").fillna(0)
		)
	else:
		base["total_amount"] = pd.to_numeric(base["amount"], errors="coerce").fillna(0)
	
	base["type_norm"] = query["type_norm"]
	base["date_iso"] = query["date_parsed"].apply(lambda v: v.strftime("%Y-%m-%d") if pd.notna(v) else "")
	result = base.fillna("").to_dict(orient="records")
	return jsonify({
		"count": len(result),
		"items": result,
	})


@app.post("/api/upload_ledgers")
def api_upload_ledgers():
	global _df_cache
	DATA_DIR.mkdir(exist_ok=True)
	purchase_file = request.files.get("purchase")
	sales_file = request.files.get("sales")
	saved: List[str] = []
	try:
		# アップロードされた台帳を保存し、正規化を実行してキャッシュを更新する
		if purchase_file and purchase_file.filename:
			target = DATA_DIR / _PURCHASE_LEDGER_FILENAME
			purchase_file.save(target)
			saved.append("purchase")
		if sales_file and sales_file.filename:
			target = DATA_DIR / _SALES_LEDGER_FILENAME
			sales_file.save(target)
			saved.append("sales")
		with DATA_LOCK:
			_regenerate_normalized_ledgers()
			_df_cache = None
		load_data(force=True)
	except FileNotFoundError as exc:
		return jsonify({"error": str(exc)}), 400
	except Exception as exc:
		return jsonify({"error": str(exc)}), 500
	return jsonify({"status": "ok", "updated": saved})


@app.post("/api/reload")
def api_reload():
	# 外部で TSV が再生成された場合に再読込を行う
	load_data(force=True)
	return jsonify({"status": "ok"})


if __name__ == "__main__":
	app.run(host="::", port=8080, debug=True)
