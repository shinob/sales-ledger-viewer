# 販売大臣NX 買掛・売掛データビュワー Webアプリ

買掛（仕入）と売掛（販売）のデータを読み込み、フォーマットを統一して検索・可視化するシンプルな Web アプリ（Flask）。

## 前提
- `normalized_ledgers.tsv`（UTF-8/UTF-8-SIG の TSV）がプロジェクト直下に存在すること
- 元データとして、販売大臣 NX からエクスポートした `data/買掛台帳.TXT` と `data/売掛台帳.TXT` があること

列名はある程度自動でマッピングされます。

## セットアップ

```bash
git clone https://github.com/shinob/sales-ledger-viewer.git
cd sales-ledger-viewer

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp -r sample_data data
```

## normalized_ledgers.tsv の生成

1. `data/買掛台帳.TXT` と `data/売掛台帳.TXT` を UTF-8 (BOM 可) または CP932 で配置する  
2. プロジェクトルートで正規化スクリプトを実行する

```bash
# ./normalized_ledgers.tsv を生成
bash normalize_ledgers.sh
# または出力先を指定
bash normalize_ledgers.sh ./data/normalized_example.tsv
```

スクリプト内部で `normalize.py` を呼び出し、買掛・売掛を正規化した TSV に変換してから 1 ファイルに結合します。Web アプリ起動後も `/api/upload_ledgers` でファイルを送信すると同じ処理が走り、`normalized_ledgers.tsv` が再生成されます。

## 実行

```bash
FLASK_RUN_PORT=5000 python app.py
```

もしくは

```bash
./run.sh
```
 
 ブラウザで `http://localhost:5000` を開きます。
 
## 機能
- フィルタ: 期間（開始/終了）、種別（販売/仕入）、キーワード（全列まとめた正規化テキスト）
- テーブル表示: 検索結果を一覧表示
- 伝票番号ドリルダウン: 伝票番号をクリックすると同じ日付・同じ伝票の行のみ再表示
- 備考列: `reference_1`〜`reference_4` をスペース区切りで結合して表示
- 単価列: `unit_price` が無い場合は金額÷数量で自動算出し、数量と金額の間に表示
- 月次推移チャート: ボタン操作時だけ最新検索結果を描画（初期表示・検索時は描画しない）
- データ再読込: `normalized_ledgers.tsv` を再読込

### API
- `GET /api/transactions` クエリパラメータ:
  - `start_date` (YYYY-MM-DD)
  - `end_date` (YYYY-MM-DD)
  - `type` (複数可: `sale`, `purchase`)
  - `q` (キーワード: 行内の正規化済みテキストに対する部分一致)
  - `document_id` (完全一致)
  - `document_date` (YYYY-MM-DD, 伝票番号と併用でドリルダウン)
 - `POST /api/reload` データ再読込
 
 ## データについて
- `normalized_ledgers.tsv` が存在しない場合、起動後の初回アクセス時にエラーになるため、先に生成してください。
- 既存の `normalize_ledgers.sh` や `data/` 以下の原本から作成済みの TSV を想定しています。
- 正規化したカラムと画面表示の対応関係は `display_header_mapping.csv` に記載しています。

## 注意
 - Excel（XLS/XLSX）直接読み込みはこのアプリでは行いません。必要に応じて別途 TSV を生成してください。
 - 列名は自動マッピングしますが、`date`/`type`/`counterparty`/`item`/`quantity`/`amount`/`document_id`/`memo` が揃っていると検索・表示が最適です。
