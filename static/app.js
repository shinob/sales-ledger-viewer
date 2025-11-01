const $ = (sel) => document.querySelector(sel);
const chartSection = document.getElementById("chartSection");
const uploadSection = document.getElementById("uploadSection");

async function fetchTransactions(params) {
	const qs = new URLSearchParams(params);
	const res = await fetch(`/api/transactions?${qs.toString()}`);
	if (!res.ok) throw new Error("failed to fetch");
	return res.json();
}

function getFilters() {
	const start = $("#start_date").value || "";
	const end = $("#end_date").value || "";
	const typeValue = document.querySelector('input[name="type"]:checked')?.value || "";
	const keyword = $("#keyword").value || "";
	const params = {};
	if (start) params.start_date = start;
	if (end) params.end_date = end;
	if (typeValue === "purchase" || typeValue === "sale") params.type = typeValue;
	if (keyword) params.q = keyword;
	return params;
}

function formatAmount(value) {
	if (value === null || value === undefined || value === "") return "";
	const num = Number(value);
	if (Number.isFinite(num)) return num.toLocaleString();
	return String(value);
}

function renderTable(items) {
	const tbody = $("#results tbody");
	tbody.innerHTML = "";
	for (const it of items) {
		const tr = document.createElement("tr");
		
		// 買掛と売掛の行に色分けクラスを追加
		if (it.type_norm === "purchase") {
			tr.className = "purchase";
		} else if (it.type_norm === "sale") {
			tr.className = "sale";
		}
		const cells = [
			{ value: it.date ?? "" },
			{ value: it.ledger_type ?? it.type_norm ?? "" },
		];
		for (const { value, className } of cells) {
			const td = document.createElement("td");
			if (className) td.className = className;
			td.textContent = value ?? "";
			tr.appendChild(td);
		}
		const docTd = document.createElement("td");
		const documentId = it.document_id ?? "";
		const documentDate = it.date_iso || it.date || "";
		if (documentId) {
			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "doc-link";
			btn.textContent = documentId;
			btn.dataset.doc = documentId;
			if (documentDate) btn.dataset.date = documentDate;
			btn.addEventListener("click", () => {
				const docId = btn.dataset.doc;
				const docDate = btn.dataset.date || "";
				const extra = {};
				if (docId) extra.document_id = docId;
				if (docDate) extra.document_date = docDate;
				search(extra);
			});
			docTd.appendChild(btn);
		}
		tr.appendChild(docTd);
		const tailCells = [
			{ value: it.counterparty ?? "" },
			{ value: it.quantity ?? "", className: "num" },
			{ value: formatAmount(it.unit_price), className: "num" },
			{ value: formatAmount(it.total_amount ?? it.amount), className: "num" },
		];
		
		// 相手先のセルを追加
		const counterpartyTd = document.createElement("td");
		counterpartyTd.textContent = tailCells[0].value;
		tr.appendChild(counterpartyTd);
		
		// 品名/備考のセルを追加（HTMLとして表示）
		const itemMemoTd = document.createElement("td");
		itemMemoTd.innerHTML = it.item_memo ?? "";
		tr.appendChild(itemMemoTd);
		
		// 残りのセル（数量、単価、金額）を追加
		for (let i = 1; i < tailCells.length; i++) {
			const { value, className } = tailCells[i];
			const td = document.createElement("td");
			if (className) td.className = className;
			td.textContent = value ?? "";
			tr.appendChild(td);
		}
		tbody.appendChild(tr);
	}
	$("#count").textContent = String(items.length);
}

let chart;
let lastItems = [];

function clearChart() {
	if (chart) {
		chart.destroy();
		chart = null;
	}
	const canvas = $("#amountChart");
	if (canvas) {
		const ctx = canvas.getContext("2d");
		if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
	}
	chartSection?.classList.add("hidden");
}

function renderChart(items) {
	if (!items || items.length === 0) {
		clearChart();
		return;
	}
	const canvas = $("#amountChart");
	if (!canvas) return;
	const buckets = new Map(); // key: YYYY-MM, values: { sale: sum, purchase: sum }
	for (const it of items) {
		const d = (it.date || "").slice(0, 7);
		if (!d) continue;
		if (!buckets.has(d)) buckets.set(d, { sale: 0, purchase: 0 });
		const b = buckets.get(d);
		const amt = Number(it.total_amount ?? it.amount) || 0;
		if (it.type_norm === "sale") b.sale += amt;
		else if (it.type_norm === "purchase") b.purchase += amt;
	}
	const labels = Array.from(buckets.keys()).sort();
	const saleData = labels.map((k) => buckets.get(k).sale);
	const purchaseData = labels.map((k) => buckets.get(k).purchase);
	if (chart) chart.destroy();
	chart = new Chart(canvas, {
		type: "line",
		data: {
			labels,
			datasets: [
				{ label: "販売", data: saleData, borderColor: "#2c7be5", tension: 0.2 },
				{ label: "仕入", data: purchaseData, borderColor: "#e5532c", tension: 0.2 },
			],
		},
		options: {
			responsive: true,
			scales: { y: { ticks: { callback: (v) => Number(v).toLocaleString() } } },
		},
	});
	chartSection?.classList.remove("hidden");
}

async function search(extraParams = {}) {
	const params = getFilters();
	Object.assign(params, extraParams);
	const data = await fetchTransactions(params);
	lastItems = data.items;
	renderTable(lastItems);
	clearChart();
	// グラフボタンのテキストをリセット
	const chartBtn = $("#chartBtn");
	if (chartBtn) chartBtn.textContent = "グラフ表示";
}

async function reloadData() {
	const res = await fetch("/api/reload", { method: "POST" });
	if (!res.ok) {
		alert("再読込に失敗しました");
		return;
	}
	await search();
}

async function uploadLedgers() {
	const purchaseInput = document.getElementById("purchaseFile");
	const salesInput = document.getElementById("salesFile");
	const btn = document.getElementById("uploadBtn");
	const toggleBtn = document.getElementById("uploadToggleBtn");
	const fd = new FormData();
	const purchase = purchaseInput?.files?.[0];
	const sales = salesInput?.files?.[0];
	if (!purchase && !sales) {
		alert("更新するファイルを選択してください");
		return;
	}
	if (purchase) fd.append("purchase", purchase);
	if (sales) fd.append("sales", sales);
	fd.append("reprocess", "1");
	if (btn) {
		btn.disabled = true;
		btn.dataset.originalText = btn.textContent;
		btn.textContent = "更新中...";
	}
	try {
		const res = await fetch("/api/upload_ledgers", {
			method: "POST",
			body: fd,
		});
		if (!res.ok) {
			const message = await res.text();
			throw new Error(message || "アップロードに失敗しました");
		}
		if (purchaseInput) purchaseInput.value = "";
		if (salesInput) salesInput.value = "";
		await search();
		if (uploadSection && !uploadSection.classList.contains("hidden")) {
			uploadSection.classList.add("hidden");
		}
		if (toggleBtn) {
			toggleBtn.textContent = "ファイル更新";
		}
	} catch (err) {
		alert(err.message || "アップロードに失敗しました");
	} finally {
		if (btn) {
			btn.disabled = false;
			btn.textContent = btn.dataset.originalText || "アップロードして更新";
			delete btn.dataset.originalText;
		}
	}
}

document.addEventListener("DOMContentLoaded", () => {
	$("#searchBtn").addEventListener("click", () => search());
	$("#chartBtn").addEventListener("click", () => {
		const chartBtn = $("#chartBtn");
		if (chartSection && chartSection.classList.contains("hidden")) {
			renderChart(lastItems);
			chartBtn.textContent = "グラフ非表示";
		} else {
			clearChart();
			chartBtn.textContent = "グラフ表示";
		}
	});
	$("#reloadBtn").addEventListener("click", reloadData);
	$("#uploadBtn").addEventListener("click", () => uploadLedgers());
	const uploadToggleBtn = document.getElementById("uploadToggleBtn");
	if (uploadToggleBtn) {
		uploadToggleBtn.addEventListener("click", () => {
			if (!uploadSection) return;
			if (uploadSection.classList.contains("hidden")) {
				uploadSection.classList.remove("hidden");
				uploadToggleBtn.textContent = "閉じる";
			} else {
				uploadSection.classList.add("hidden");
				uploadToggleBtn.textContent = "ファイル更新";
			}
		});
	}
	// initial load
	search().catch(() => {
		// likely the TSV isn't ready yet
	});
});
