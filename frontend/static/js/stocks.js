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
  

// // /static/js/stocks.js

// // ---------------------------
// // Config / helpers
// // ---------------------------
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
//         <a class="analysis-hist" href="${base}/historical/${sym}/?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long&asset=stock">Historical Data</a>
//       </td>
//     </tr>
//   `;
// }

// function renderStocks() {
//   const tbody = document.getElementById("tbody-stocks");
//   if (tbody) tbody.innerHTML = TICKERS.map(rowHTML).join("");
// }

// function getTfFromHref(href) {
//   try { return new URL(href, location.origin).searchParams.get("tf") || "1h"; }
//   catch { return "1h"; }
// }

// // ---------------------------
// // CSV ensure/fill
// // ---------------------------
// async function ensureCsv(sym, asset, tf = "1h") {
//   // 1) check
//   const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
//   let res = await fetch(checkUrl);
//   let data = await res.json().catch(() => ({}));
//   if (res.ok && data.ok) return data;

//   // 2) if missing/stale, try to fill for stocks
//   if (asset === "stock") {
//     const fillUrl = `/api/analysis/fill_csv/${encodeURIComponent(sym)}/?tf=${encodeURIComponent(tf)}`;
//     const fillRes = await fetch(fillUrl);
//     const fillData = await fillRes.json().catch(() => ({}));
//     if (!fillRes.ok || !fillData.ok) {
//       const reason = fillData?.reason || `CSV fill failed (${fillRes.status})`;
//       throw new Error(reason);
//     }
//     // 3) re-check
//     res = await fetch(checkUrl);
//     data = await res.json().catch(() => ({}));
//     if (res.ok && data.ok) return data;
//   }

//   const reason = data?.reason || `CSV check failed (${res.status})`;
//   throw new Error(reason);
// }

// // ---------------------------
// // Link guards (Tickers tab)
// // ---------------------------
// document.addEventListener("click", async (e) => {
//   // analysis links (candles/equity/all)
//   const a = e.target.closest("a.analysis");
//   if (!a) return;

//   e.preventDefault();
//   const tr  = a.closest("tr");
//   const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
//   const tf  = getTfFromHref(a.href);

//   a.dataset.oldText = a.textContent;
//   a.textContent = "Checking data…";
//   try {
//     await ensureCsv(sym, "stock", tf);
//     location.href = a.href; // proceed
//   } catch (err) {
//     alert(`Cannot open ${sym}: ${err.message}`);
//     a.textContent = a.dataset.oldText || "Open";
//   }
// });

// // historical links
// document.addEventListener("click", async (e) => {
//   const a = e.target.closest("a.analysis-hist");
//   if (!a) return;

//   e.preventDefault();
//   const tr  = a.closest("tr");
//   const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();

//   a.dataset.oldText = a.textContent;
//   a.textContent = "Checking historical…";
//   try {
//     const url  = `/api/analysis/check_historical_csv/${encodeURIComponent(sym)}/`;
//     const res  = await fetch(url);
//     const data = await res.json().catch(() => ({}));
//     if (!res.ok || !data.ok) {
//       const reason = data?.reason || `No HistoricalData_${sym}.csv`;
//       throw new Error(reason);
//     }
//     location.href = a.href;
//   } catch (err) {
//     alert(`Cannot open historical for ${sym}: ${err.message}`);
//     a.textContent = a.dataset.oldText || "Historical Data";
//   }
// });

// // ---------------------------
// // Today tab loader (HTML fragment)
// // ---------------------------
// // Call this when #today tab becomes active.
// // wherever you load the Today panel
// async function loadTodayPanel() {
//   const panel = document.getElementById("panel-today");
//   if (!panel) return;
//   const res = await fetch("/stocks/today/", { headers: { "X-Requested-With": "XMLHttpRequest" } });
//   const html = await res.text();
//   panel.innerHTML = html;         // inject markup
//   initTodayFragment(panel);       // <-- run behavior now
// }


// // ---------------------------
// // Tab switch hook
// // ---------------------------
// // If your page has a setTab() already, call loadTodayPanel()
// // when the Today tab becomes active. If not, provide a small hook:
// (function ensureTabHook() {
//   // If a global setTab already exists, we won't override it.
//   if (typeof window.setTab === 'function') {
//     const original = window.setTab;
//     window.setTab = function(hash) {
//       original.call(this, hash);
//       const h = (hash || location.hash || '#tickers').toLowerCase();
//       if (h === '#today') loadTodayPanel();
//     };
//     // run once on load
//     window.setTab();
//   } else {
//     // Minimal fallback: load panel if hash is already #today
//     if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
//     // And watch for hash changes
//     window.addEventListener('hashchange', () => {
//       if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
//     });
//   }
// })();


// // --- Watchlist helpers (localStorage) ---
// const WL_KEY = "watchlist.stocks";

// function wlLoad() {
//   try { return JSON.parse(localStorage.getItem(WL_KEY)) || []; } catch { return []; }
// }
// function wlSave(arr) { localStorage.setItem(WL_KEY, JSON.stringify(arr)); }
// function wlAdd(sym) {
//   sym = (sym || "").trim().toUpperCase();
//   if (!sym) return;
//   const wl = wlLoad();
//   if (!wl.includes(sym)) {
//     wl.push(sym);
//     wl.sort();
//     wlSave(wl);
//   }
// }
// function wlRemove(sym) {
//   wlSave(wlLoad().filter(s => s !== sym));
// }

// function wlRender($root) {
//   const $list = $root.querySelector("#wl-list");
//   if (!$list) return;
//   const wl = wlLoad();
//   $list.innerHTML = "";
//   if (!wl.length) {
//     const li = document.createElement("li");
//     li.textContent = "No tickers yet.";
//     li.style.listStyle = "none";
//     li.className = "hint";
//     $list.appendChild(li);
//     return;
//   }
//   for (const sym of wl) {
//     const li = document.createElement("li");
//     li.className = "wl-item";
//     li.dataset.sym = sym;

//     const left = document.createElement("div");
//     left.className = "wl-sym";
//     left.textContent = sym;

//     const btn = document.createElement("button");
//     btn.className = "wl-remove";
//     btn.type = "button";
//     btn.textContent = "×";
//     btn.title = "Remove from watchlist";

//     li.appendChild(left);
//     li.appendChild(btn);
//     $list.appendChild(li);
//   }
// }

// // --- Populate dropdown with CSV symbols (with timeout + errors) ---
// async function loadCsvSymbolsInto($root) {
//   const $ddl = $root.querySelector("#wl-dropdown");
//   if (!$ddl) return;
//   const controller = new AbortController();
//   const t = setTimeout(() => controller.abort(), 8000);

//   try {
//     const res = await fetch("/api/today/csv_symbols", {
//       headers: { "Accept": "application/json" },
//       signal: controller.signal
//     });
//     clearTimeout(t);
//     const js = await res.json().catch(()=> ({}));
//     $ddl.innerHTML = "";

//     if (!res.ok || !js.ok) {
//       const opt = document.createElement("option");
//       opt.value = "";
//       opt.textContent = `Error: ${js?.error || res.status}`;
//       $ddl.appendChild(opt);
//       return;
//     }
//     const list = Array.isArray(js.symbols) ? js.symbols.slice().sort() : [];
//     if (!list.length) {
//       const opt = document.createElement("option");
//       opt.value = "";
//       opt.textContent = "No CSVs found";
//       $ddl.appendChild(opt);
//       return;
//     }
//     for (const sym of list) {
//       const opt = document.createElement("option");
//       opt.value = sym;
//       opt.textContent = sym;
//       $ddl.appendChild(opt);
//     }
//   } catch (err) {
//     clearTimeout(t);
//     $ddl.innerHTML = "";
//     const opt = document.createElement("option");
//     opt.value = "";
//     opt.textContent = (err.name === "AbortError") ? "Timed out" : "Load error";
//     $ddl.appendChild(opt);
//   }
// }

// // --- Wire the fragment once injected ---
// function initTodayFragment($root) {
//   // render existing WL
//   wlRender($root);

//   // WL interactions
//   const $list = $root.querySelector("#wl-list");
//   const $input = $root.querySelector("#upd-ticker");
//   const $status = $root.querySelector("#upd-status");
//   $list?.addEventListener("click", (e) => {
//     const li = e.target.closest(".wl-item");
//     if (!li) return;
//     const sym = li.dataset.sym;
//     if (e.target.classList.contains("wl-remove")) {
//       wlRemove(sym); wlRender($root);
//       if ($status) $status.textContent = `Removed ${sym} from watchlist`;
//     } else {
//       if ($input) $input.value = sym;
//     }
//   });

//   // Dropdown + plus button
//   const $ddl = $root.querySelector("#wl-dropdown");
//   const $add = $root.querySelector("#wl-add-btn");
//   $add?.addEventListener("click", () => {
//     const sym = ($ddl?.value || "").trim().toUpperCase();
//     if (!sym) return;
//     wlAdd(sym);
//     wlRender($root);
//     if ($status) $status.textContent = `Added ${sym} to watchlist`;
//   });
//   loadCsvSymbolsInto($root);

//   // Update form
//   const $form = $root.querySelector("#upd-form");
//   const $btn  = $root.querySelector("#upd-btn");
//   const csrf  = $form?.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
//   $form?.addEventListener("submit", async (e) => {
//     e.preventDefault();
//     const ticker = ($input?.value || "").trim().toUpperCase();
//     if (!ticker) { if ($status) $status.textContent = "Enter a ticker (e.g., AAPL)"; return; }
//     if ($btn) $btn.disabled = true;
//     if ($status) $status.textContent = "Updating…";
//     try {
//       const fd = new FormData();
//       fd.append("ticker", ticker);
//       const res = await fetch("/api/today/update", {
//         method: "POST",
//         headers: { "X-CSRFToken": csrf },
//         body: fd
//       });
//       const data = await res.json().catch(()=> ({}));
//       if (res.ok && data.ok) {
//         if ($status) $status.textContent = `✓ ${data.ticker}: +${data.rows_added} (total ${data.total_rows ?? "—"})`;
//         wlAdd(ticker); wlRender($root);
//       } else {
//         if ($status) $status.textContent = (data && data.error) ? data.error : `Error ${res.status}`;
//       }
//     } catch (err) {
//       if ($status) $status.textContent = String(err);
//     } finally {
//       if ($btn) $btn.disabled = false;
//     }
//   });
// }



// // ---------------------------
// // Init
// // ---------------------------
// renderStocks();



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
async function loadTodayPanel() {
  const panel = document.getElementById("panel-today");
  if (!panel) return;
  const res = await fetch("/stocks/today/", { headers: { "X-Requested-With": "XMLHttpRequest" } });
  const html = await res.text();
  panel.innerHTML = html;         // inject markup
  initTodayFragment(panel);       // <-- run behavior now
}

// ---------------------------
// Tab switch hook
// ---------------------------
(function ensureTabHook() {
  if (typeof window.setTab === 'function') {
    const original = window.setTab;
    window.setTab = function(hash) {
      original.call(this, hash);
      const h = (hash || location.hash || '#tickers').toLowerCase();
      if (h === '#today') loadTodayPanel();
    };
    window.setTab();
  } else {
    if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    window.addEventListener('hashchange', () => {
      if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    });
  }
})();

// --- Watchlist helpers (localStorage) ---
const WL_KEY = "watchlist.stocks";

function wlLoad() {
  try { return JSON.parse(localStorage.getItem(WL_KEY)) || []; } catch { return []; }
}
function wlSave(arr) { localStorage.setItem(WL_KEY, JSON.stringify(arr)); }
function wlAdd(sym) {
  sym = (sym || "").trim().toUpperCase();
  if (!sym) return;
  const wl = wlLoad();
  if (!wl.includes(sym)) {
    wl.push(sym);
    wl.sort();
    wlSave(wl);
  }
}
function wlRemove(sym) {
  wlSave(wlLoad().filter(s => s !== sym));
}

function wlRender($root) {
  const $list = $root.querySelector("#wl-list");
  if (!$list) return;
  const wl = wlLoad();
  $list.innerHTML = "";
  if (!wl.length) {
    const li = document.createElement("li");
    li.textContent = "No tickers yet.";
    li.style.listStyle = "none";
    li.className = "hint";
    $list.appendChild(li);
    return;
  }
  for (const sym of wl) {
    const li = document.createElement("li");
    li.className = "wl-item";
    li.dataset.sym = sym;

    const left = document.createElement("div");
    left.className = "wl-sym";
    left.textContent = sym;

    const btn = document.createElement("button");
    btn.className = "wl-remove";
    btn.type = "button";
    btn.textContent = "×";
    btn.title = "Remove from watchlist";

    li.appendChild(left);
    li.appendChild(btn);
    $list.appendChild(li);
  }
}

// --- Populate dropdown with CSV symbols (with timeout + errors) ---
async function loadCsvSymbolsInto($root) {
  const $ddl = $root.querySelector("#wl-dropdown");
  if (!$ddl) return;
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 8000);

  try {
    const res = await fetch("/api/today/csv_symbols", {
      headers: { "Accept": "application/json" },
      signal: controller.signal
    });
    clearTimeout(t);
    const js = await res.json().catch(()=> ({}));
    $ddl.innerHTML = "";

    if (!res.ok || !js.ok) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = `Error: ${js?.error || res.status}`;
      $ddl.appendChild(opt);
      return;
    }
    const list = Array.isArray(js.symbols) ? js.symbols.slice().sort() : [];
    if (!list.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No CSVs found";
      $ddl.appendChild(opt);
      return;
    }
    for (const sym of list) {
      const opt = document.createElement("option");
      opt.value = sym;
      opt.textContent = sym;
      $ddl.appendChild(opt);
    }
  } catch (err) {
    clearTimeout(t);
    $ddl.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = (err.name === "AbortError") ? "Timed out" : "Load error";
    $ddl.appendChild(opt);
  }
}

// --- Today’s buy (2 random from WL) ---
function renderTodaysBuy($root) {
  const $out = $root.querySelector("#today-buy");
  if (!$out) return;
  const wl = wlLoad();
  $out.innerHTML = "";
  if (!wl.length) {
    const li = document.createElement("li");
    li.textContent = "Add tickers to your watchlist to see picks here.";
    li.style.listStyle = "none";
    li.className = "hint";
    $out.appendChild(li);
    return;
  }
  // simple shuffle and take 2
  const picks = wl.slice();
  for (let i = picks.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [picks[i], picks[j]] = [picks[j], picks[i]];
  }
  for (const sym of picks.slice(0, Math.min(2, picks.length))) {
    const li = document.createElement("li");
    li.className = "wl-item";
    li.dataset.sym = sym;
    const left = document.createElement("div");
    left.className = "wl-sym";
    left.textContent = sym;
    li.appendChild(left);
    $out.appendChild(li);
  }
}

// --- Update API helpers (used for auto-update + search) ---
async function updateTicker(sym, csrf) {
  const fd = new FormData();
  fd.append("ticker", sym);
  const res = await fetch("/api/today/update", {
    method: "POST",
    headers: { "X-CSRFToken": csrf },
    body: fd
  });
  const data = await res.json().catch(()=> ({}));
  return { ok: res.ok && data.ok, data };
}

async function updateAllWatchlist($root, csrf) {
  const $status = $root.querySelector("#upd-status");
  const wl = wlLoad();
  if (!wl.length) { renderTodaysBuy($root); return; }
  $status && ($status.textContent = `Updating ${wl.length} tickers…`);

  // batch updates (5 at a time)
  const BATCH = 5;
  for (let i = 0; i < wl.length; i += BATCH) {
    const slice = wl.slice(i, i + BATCH);
    await Promise.allSettled(slice.map(sym => updateTicker(sym, csrf)));
  }
  $status && ($status.textContent = `Watchlist up to date.`);
  renderTodaysBuy($root);
}

// --- Wire the fragment once injected ---
function initTodayFragment($root) {
  // render existing WL
  wlRender($root);

  // WL interactions
  const $list = $root.querySelector("#wl-list");
  const $input = $root.querySelector("#upd-ticker");
  const $status = $root.querySelector("#upd-status");
  $list?.addEventListener("click", (e) => {
    const li = e.target.closest(".wl-item");
    if (!li) return;
    const sym = li.dataset.sym;
    if (e.target.classList.contains("wl-remove")) {
      wlRemove(sym); wlRender($root); renderTodaysBuy($root);
      if ($status) $status.textContent = `Removed ${sym} from watchlist`;
    } else {
      if ($input) $input.value = sym;
    }
  });

  // Dropdown + plus button
  const $ddl = $root.querySelector("#wl-dropdown");
  const $add = $root.querySelector("#wl-add-btn");
  $add?.addEventListener("click", () => {
    const sym = ($ddl?.value || "").trim().toUpperCase();
    if (!sym) return;
    wlAdd(sym);
    wlRender($root);
    renderTodaysBuy($root);
    if ($status) $status.textContent = `Added ${sym} to watchlist`;
  });
  loadCsvSymbolsInto($root);

  // Search form
  const $form = $root.querySelector("#upd-form");
  const $btn  = $root.querySelector("#upd-btn");
  const csrf  = $form?.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
  $form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = ($input?.value || "").trim().toUpperCase();
    if (!ticker) { if ($status) $status.textContent = "Enter a ticker (e.g., AAPL)"; return; }
    if ($btn) $btn.disabled = true;
    if ($status) $status.textContent = "Updating…";
    try {
      const r = await updateTicker(ticker, csrf);
      if (r.ok) {
        if ($status) $status.textContent = `✓ ${ticker} updated`;
        wlAdd(ticker); wlRender($root); renderTodaysBuy($root);
      } else {
        if ($status) $status.textContent = r.data?.error || "Update failed";
      }
    } catch (err) {
      if ($status) $status.textContent = String(err);
    } finally {
      if ($btn) $btn.disabled = false;
    }
  });

  // Auto-update all watchlist on load
  updateAllWatchlist($root, csrf);
}

// ---------------------------
// Init
// ---------------------------
renderStocks();
