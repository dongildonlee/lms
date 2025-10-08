// // /static/stocks.js

// const TICKERS = ["AAPL","MSFT","NVDA","TSLA","AMZN","GOOGL","META","AMD","NFLX","AVGO"];

// function rowHTML(sym) {
//   const base = `/api/analysis`;
//   return `
//     <tr data-sym="${sym}">
//       <td><strong>${sym}</strong></td>
//       <td class="actions">
//         <a class="analysis" href="${base}/candles/${sym}/?tf=1h&start=2025-09&end=2025-10&asset=stock">Candlestick</a>
//         <a class="analysis" href="${base}/equity/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Cumulative</a>
//         <a class="analysis" href="${base}/all/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=kalman_cross&asset=stock">ALL</a>  
//         <a class="analysis" href="${base}/historical/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Historical Data</a>
//       </td>
//     </tr>
//   `;
// }

// function renderStocks() {
//   const tbody = document.getElementById("tbody-stocks");
//   tbody.innerHTML = TICKERS.map(rowHTML).join("");
// }

// async function ensureCsv(sym, asset) {
//   const url = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
//   const res = await fetch(url, { method: "GET" });
//   const data = await res.json().catch(() => ({}));
//   if (!res.ok || !data.ok) {
//     const reason = (data && data.reason) ? data.reason : `CSV check failed (${res.status})`;
//     throw new Error(reason);
//   }
//   return data;
// }

// // one event listener for all links
// function wireCheckThenGo(assetType) {
//   document.addEventListener("click", async (e) => {
//     const a = e.target.closest("a.analysis");

//     if (!a) return;
//     e.preventDefault();

//     const tr = a.closest("tr");
//     const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
//     a.setAttribute("data-old-text", a.textContent);
//     a.textContent = "Checking data…";

//     try {
//       await ensureCsv(sym, assetType);
//       location.href = a.href; // proceed to plot
//     } catch (err) {
//       alert(`Cannot open ${sym}: ${err.message}`);
//       a.textContent = a.getAttribute("data-old-text");
//     }
//   });
// }

// // separate handler for 'Historical Data' links
// function wireHistoricalCheck() {
//     document.addEventListener("click", async (e) => {
//       const a = e.target.closest("a.analysis-hist");
//       if (!a) return;
//       e.preventDefault();
//       const tr = a.closest("tr");
//       const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
//       a.dataset.oldText = a.textContent;
//       a.textContent = "Checking historical…";
//       try {
//         const url = `/api/analysis/check_historical_csv/${encodeURIComponent(sym)}/`;
//         const res = await fetch(url, { method: "GET" });
//         const data = await res.json().catch(()=> ({}));
//         if (!res.ok || !data.ok) {
//           const reason = data?.reason || `No HistoricalData_${sym}.csv`;
//           throw new Error(reason);
//         }
//         location.href = a.href;
//       } catch (err) {
//         alert(`Cannot open historical for ${sym}: ${err.message}`);
//         a.textContent = a.dataset.oldText || "Historical Data";
//       }
//     });
//   }

// // init
// renderStocks();
// wireCheckThenGo("stock");
// wireHistoricalCheck();

// async function ensureCsv(sym, asset, tf) {
//     // 1) check
//     const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
//     let res = await fetch(checkUrl);
//     let data = await res.json().catch(() => ({}));
//     if (res.ok && data.ok) return data;
  
//     // 2) if missing or stale, try to fill for stocks
//     if (asset === "stock") {
//       const fillUrl = `/api/analysis/fill_csv/${encodeURIComponent(sym)}/?tf=${encodeURIComponent(tf || "1h")}`;
//       const fill = await fetch(fillUrl);
//       const fillData = await fill.json().catch(() => ({}));
//       if (!fill.ok || !fillData.ok) {
//         const reason = fillData.reason || `CSV fill failed (${fill.status})`;
//         throw new Error(reason);
//       }
//       // 3) re-check after fill
//       res = await fetch(checkUrl);
//       data = await res.json().catch(() => ({}));
//       if (res.ok && data.ok) return data;
//     }
  
//     const reason = (data && data.reason) ? data.reason : `CSV check failed (${res.status})`;
//     throw new Error(reason);
//   }
  
//   // parse tf from the link's query (e.g., ?tf=1h&...)
//   function getTfFromHref(href) {
//     try { return new URL(href, location.origin).searchParams.get("tf") || "1h"; }
//     catch { return "1h"; }
//   }
  
//   document.addEventListener("click", async (e) => {
//     const a = e.target.closest("a.analysis");
//     if (!a) return;
//     e.preventDefault();
  
//     const tr = a.closest("tr");
//     const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
//     const tf  = getTfFromHref(a.href);
  
//     a.dataset.oldText = a.textContent;
//     a.textContent = "Checking data…";
  
//     try {
//       await ensureCsv(sym, "stock", tf);
//       location.href = a.href; // proceed to plot
//     } catch (err) {
//       alert(`Cannot open ${sym}: ${err.message}`);
//       a.textContent = a.dataset.oldText || "Open";
//     }
//   });
  

// /static/js/stocks.js

// ---------------------------
// Config / helpers
// ---------------------------
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
        <a class="analysis-hist" href="${base}/historical/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Historical Data</a>
      </td>
    </tr>
  `;
}

function renderStocks() {
  const tbody = document.getElementById("tbody-stocks");
  if (tbody) tbody.innerHTML = TICKERS.map(rowHTML).join("");
}

function getTfFromHref(href) {
  try { return new URL(href, location.origin).searchParams.get("tf") || "1h"; }
  catch { return "1h"; }
}

// ---------------------------
// CSV ensure/fill
// ---------------------------
async function ensureCsv(sym, asset, tf = "1h") {
  // 1) check
  const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
  let res = await fetch(checkUrl);
  let data = await res.json().catch(() => ({}));
  if (res.ok && data.ok) return data;

  // 2) if missing/stale, try to fill for stocks
  if (asset === "stock") {
    const fillUrl = `/api/analysis/fill_csv/${encodeURIComponent(sym)}/?tf=${encodeURIComponent(tf)}`;
    const fillRes = await fetch(fillUrl);
    const fillData = await fillRes.json().catch(() => ({}));
    if (!fillRes.ok || !fillData.ok) {
      const reason = fillData?.reason || `CSV fill failed (${fillRes.status})`;
      throw new Error(reason);
    }
    // 3) re-check
    res = await fetch(checkUrl);
    data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) return data;
  }

  const reason = data?.reason || `CSV check failed (${res.status})`;
  throw new Error(reason);
}

// ---------------------------
// Link guards (Tickers tab)
// ---------------------------
document.addEventListener("click", async (e) => {
  // analysis links (candles/equity/all)
  const a = e.target.closest("a.analysis");
  if (!a) return;

  e.preventDefault();
  const tr  = a.closest("tr");
  const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
  const tf  = getTfFromHref(a.href);

  a.dataset.oldText = a.textContent;
  a.textContent = "Checking data…";
  try {
    await ensureCsv(sym, "stock", tf);
    location.href = a.href; // proceed
  } catch (err) {
    alert(`Cannot open ${sym}: ${err.message}`);
    a.textContent = a.dataset.oldText || "Open";
  }
});

// historical links
document.addEventListener("click", async (e) => {
  const a = e.target.closest("a.analysis-hist");
  if (!a) return;

  e.preventDefault();
  const tr  = a.closest("tr");
  const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();

  a.dataset.oldText = a.textContent;
  a.textContent = "Checking historical…";
  try {
    const url  = `/api/analysis/check_historical_csv/${encodeURIComponent(sym)}/`;
    const res  = await fetch(url);
    const data = await res.json().catch(() => ({}));
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

// ---------------------------
// Today tab loader (HTML fragment)
// ---------------------------
// Call this when #today tab becomes active.
async function loadTodayPanel() {
  const panel = document.getElementById('panel-today');
  if (!panel) return;

  try {
    // Get server-rendered fragment (contains {% csrf_token %} etc.)
    const res  = await fetch('/stocks/today/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    const html = await res.text();
    panel.innerHTML = html;

    // Wire the Update form inside the injected fragment
    const form   = panel.querySelector('#upd-form');
    const input  = panel.querySelector('#upd-ticker');
    const btn    = panel.querySelector('#upd-btn');
    const status = panel.querySelector('#upd-status');
    if (!form || !input || !btn || !status) return;

    const csrf = form.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const ticker = (input.value || '').trim().toUpperCase();
      if (!ticker) { status.textContent = 'Enter a ticker (e.g., AAPL)'; return; }
      status.textContent = 'Updating…';
      btn.disabled = true;
      try {
        const fd = new FormData(form); // includes 'ticker'
        const r  = await fetch('/api/today/update', {
          method: 'POST',
          headers: { 'X-CSRFToken': csrf },
          body: fd
        });
        const js = await r.json().catch(() => ({}));
        if (r.ok && js.ok) {
          status.textContent = `✓ ${js.ticker}: +${js.rows_added} (total ${js.total_rows ?? '—'})`;
        } else {
          status.textContent = js?.error || `Error ${r.status}`;
        }
      } catch (err) {
        status.textContent = String(err);
      } finally {
        btn.disabled = false;
      }
    });
  } catch (e) {
    console.error('Failed to load Today panel:', e);
  }
}

// ---------------------------
// Tab switch hook
// ---------------------------
// If your page has a setTab() already, call loadTodayPanel()
// when the Today tab becomes active. If not, provide a small hook:
(function ensureTabHook() {
  // If a global setTab already exists, we won't override it.
  if (typeof window.setTab === 'function') {
    const original = window.setTab;
    window.setTab = function(hash) {
      original.call(this, hash);
      const h = (hash || location.hash || '#tickers').toLowerCase();
      if (h === '#today') loadTodayPanel();
    };
    // run once on load
    window.setTab();
  } else {
    // Minimal fallback: load panel if hash is already #today
    if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    // And watch for hash changes
    window.addEventListener('hashchange', () => {
      if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    });
  }
})();

// ---------------------------
// Init
// ---------------------------
renderStocks();
