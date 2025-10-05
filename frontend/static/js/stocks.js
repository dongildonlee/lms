// /static/stocks.js

const TICKERS = ["AAPL","MSFT","NVDA","TSLA","AMZN","GOOGL","META","AMD","NFLX","AVGO"];

function rowHTML(sym) {
  const base = `/api/analysis`;
  return `
    <tr data-sym="${sym}">
      <td><strong>${sym}</strong></td>
      <td class="actions">
        <a class="analysis" href="${base}/candles/${sym}/?tf=1h&start=2025-09&end=2025-10&asset=stock">Candlestick</a>
        <a class="analysis" href="${base}/equity/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Cumulative</a>
        <a class="analysis" href="${base}/all/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=kalman_cross&asset=stock">ALL</a>  
        <a class="analysis" href="${base}/historical/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Historical Data</a>
      </td>
    </tr>
  `;
}

function renderStocks() {
  const tbody = document.getElementById("tbody-stocks");
  tbody.innerHTML = TICKERS.map(rowHTML).join("");
}

async function ensureCsv(sym, asset) {
  const url = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    const reason = (data && data.reason) ? data.reason : `CSV check failed (${res.status})`;
    throw new Error(reason);
  }
  return data;
}

// one event listener for all links
function wireCheckThenGo(assetType) {
  document.addEventListener("click", async (e) => {
    const a = e.target.closest("a.analysis");

    if (!a) return;
    e.preventDefault();

    const tr = a.closest("tr");
    const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
    a.setAttribute("data-old-text", a.textContent);
    a.textContent = "Checking data…";

    try {
      await ensureCsv(sym, assetType);
      location.href = a.href; // proceed to plot
    } catch (err) {
      alert(`Cannot open ${sym}: ${err.message}`);
      a.textContent = a.getAttribute("data-old-text");
    }
  });
}

// separate handler for 'Historical Data' links
function wireHistoricalCheck() {
    document.addEventListener("click", async (e) => {
      const a = e.target.closest("a.analysis-hist");
      if (!a) return;
      e.preventDefault();
      const tr = a.closest("tr");
      const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
      a.dataset.oldText = a.textContent;
      a.textContent = "Checking historical…";
      try {
        const url = `/api/analysis/check_historical_csv/${encodeURIComponent(sym)}/`;
        const res = await fetch(url, { method: "GET" });
        const data = await res.json().catch(()=> ({}));
        if (!res.ok || !data.ok) {
          const reason = data?.reason || `No HistoricalData_${sym}.csv`;
          throw new Error(reason);
        }
        location.href = a.href;
      } catch (err) {
        alert(`Cannot open historical for ${sym}: ${err.message}`);
        a.textContent = a.dataset.oldText || "Historical Data";
      }
    });
  }

// init
renderStocks();
wireCheckThenGo("stock");
wireHistoricalCheck();

async function ensureCsv(sym, asset, tf) {
    // 1) check
    const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
    let res = await fetch(checkUrl);
    let data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) return data;
  
    // 2) if missing or stale, try to fill for stocks
    if (asset === "stock") {
      const fillUrl = `/api/analysis/fill_csv/${encodeURIComponent(sym)}/?tf=${encodeURIComponent(tf || "1h")}`;
      const fill = await fetch(fillUrl);
      const fillData = await fill.json().catch(() => ({}));
      if (!fill.ok || !fillData.ok) {
        const reason = fillData.reason || `CSV fill failed (${fill.status})`;
        throw new Error(reason);
      }
      // 3) re-check after fill
      res = await fetch(checkUrl);
      data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) return data;
    }
  
    const reason = (data && data.reason) ? data.reason : `CSV check failed (${res.status})`;
    throw new Error(reason);
  }
  
  // parse tf from the link's query (e.g., ?tf=1h&...)
  function getTfFromHref(href) {
    try { return new URL(href, location.origin).searchParams.get("tf") || "1h"; }
    catch { return "1h"; }
  }
  
  document.addEventListener("click", async (e) => {
    const a = e.target.closest("a.analysis");
    if (!a) return;
    e.preventDefault();
  
    const tr = a.closest("tr");
    const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
    const tf  = getTfFromHref(a.href);
  
    a.dataset.oldText = a.textContent;
    a.textContent = "Checking data…";
  
    try {
      await ensureCsv(sym, "stock", tf);
      location.href = a.href; // proceed to plot
    } catch (err) {
      alert(`Cannot open ${sym}: ${err.message}`);
      a.textContent = a.dataset.oldText || "Open";
    }
  });
  

