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
// (function ensureTabHook() {
//   if (typeof window.setTab === 'function') {
//     const original = window.setTab;
//     window.setTab = function(hash) {
//       original.call(this, hash);
//       const h = (hash || location.hash || '#tickers').toLowerCase();
//       if (h === '#today') loadTodayPanel();
//     };
//     window.setTab();
//   } else {
//     if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
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

// // --- Today’s buy (2 random from WL) ---
// function renderTodaysBuy($root) {
//   const $out = $root.querySelector("#today-buy");
//   if (!$out) return;
//   const wl = wlLoad();
//   $out.innerHTML = "";
//   if (!wl.length) {
//     const li = document.createElement("li");
//     li.textContent = "Add tickers to your watchlist to see picks here.";
//     li.style.listStyle = "none";
//     li.className = "hint";
//     $out.appendChild(li);
//     return;
//   }
//   // simple shuffle and take 2
//   const picks = wl.slice();
//   for (let i = picks.length - 1; i > 0; i--) {
//     const j = Math.floor(Math.random() * (i + 1));
//     [picks[i], picks[j]] = [picks[j], picks[i]];
//   }
//   for (const sym of picks.slice(0, Math.min(2, picks.length))) {
//     const li = document.createElement("li");
//     li.className = "wl-item";
//     li.dataset.sym = sym;
//     const left = document.createElement("div");
//     left.className = "wl-sym";
//     left.textContent = sym;
//     li.appendChild(left);
//     $out.appendChild(li);
//   }
// }

// // --- Update API helpers (used for auto-update + search) ---
// async function updateTicker(sym, csrf) {
//   const fd = new FormData();
//   fd.append("ticker", sym);
//   const res = await fetch("/api/today/update", {
//     method: "POST",
//     headers: { "X-CSRFToken": csrf },
//     body: fd
//   });
//   const data = await res.json().catch(()=> ({}));
//   return { ok: res.ok && data.ok, data };
// }

// async function updateAllWatchlist($root, csrf) {
//   const $status = $root.querySelector("#upd-status");
//   const wl = wlLoad();
//   if (!wl.length) { renderTodaysBuy($root); return; }
//   $status && ($status.textContent = `Updating ${wl.length} tickers…`);

//   // batch updates (5 at a time)
//   const BATCH = 5;
//   for (let i = 0; i < wl.length; i += BATCH) {
//     const slice = wl.slice(i, i + BATCH);
//     await Promise.allSettled(slice.map(sym => updateTicker(sym, csrf)));
//   }
//   $status && ($status.textContent = `Watchlist up to date.`);
//   renderTodaysBuy($root);
// }


// const TB_PAGE_SIZE = 10; // 10 dates per page

//   function tb_seededRandom(seed) {
//     // Mulberry32
//     let t = seed + 0x6D2B79F5;
//     return function() {
//       t = Math.imul(t ^ (t >>> 15), 1 | t);
//       t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
//       return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
//     };
//   }
  
//   function tb_buildRows(days = 60) {
//     // Build last N days including today; most recent first
//     const wl = wlLoad();
//     const out = [];
//     const today = new Date(); today.setHours(0,0,0,0);
  
//     for (let d = 0; d < days; d++) {
//       const dt = new Date(today.getTime() - d * 86400000);
//       const iso = dt.toISOString().slice(0,10);
  
//       if (wl.length === 0) {
//         out.push({ date: iso, buys: [], signals: [], other: [] });
//         continue;
//       }
  
//       // deterministic picks per day so pagination is stable
//       const rnd = tb_seededRandom(Number(iso.replace(/-/g,'')));
//       const shuffled = wl.slice();
//       for (let i = shuffled.length - 1; i > 0; i--) {
//         const j = Math.floor(rnd() * (i + 1));
//         [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
//       }
//       const buys = shuffled.slice(0, Math.min(2, shuffled.length));
  
//       // toy signals for placeholder UX
//       const SIGS = ["BR","Kalman","SG_Long","HH","HL","LH","LL"];
//       function pickSigs(n) {
//         const s = [];
//         for (let i = 0; i < n; i++) s.push(SIGS[Math.floor(rnd()*SIGS.length)]);
//         return Array.from(new Set(s));
//       }
//       const signals = buys.map(b => `${b}: ${pickSigs(2).join(", ")}`);
//       const other   = shuffled.slice(2, Math.min(6, shuffled.length)).map(b => `${b}: ${pickSigs(1).join(", ")}`);
  
//       out.push({ date: iso, buys, signals, other });
//     }
//     return out; // [{date, buys:[], signals:[], other:[]}] newest first
//   }
  
//   function tb_renderPage($root, state) {
//     const $tbody = $root.querySelector("#tb-body");
//     const $pages = $root.querySelector("#tb-pages");
//     if (!$tbody || !$pages) return;
  
//     const start = state.page * TB_PAGE_SIZE;
//     const end   = Math.min(start + TB_PAGE_SIZE, state.rows.length);
//     const slice = state.rows.slice(start, end);
  
//     // body
//     $tbody.innerHTML = "";
//     for (const row of slice) {
//       const tr = document.createElement("tr");
  
//       const tdDate = document.createElement("td");
//       tdDate.textContent = row.date;
  
//       const tdBuy = document.createElement("td");
//       if (row.buys.length) {
//         for (const b of row.buys) {
//           const span = document.createElement("span");
//           span.className = "pill buy";
//           span.textContent = b;
//           tdBuy.appendChild(span);
//         }
//       } else {
//         tdBuy.innerHTML = "<span class='hint'>—</span>";
//       }
  
//       const tdSig = document.createElement("td");
//       if (row.signals.length) {
//         for (const s of row.signals) {
//           const span = document.createElement("span");
//           span.className = "pill sig";
//           span.textContent = s;
//           tdSig.appendChild(span);
//         }
//       } else {
//         tdSig.innerHTML = "<span class='hint'>—</span>";
//       }
  
//       const tdOther = document.createElement("td");
//       if (row.other.length) {
//         for (const s of row.other) {
//           const span = document.createElement("span");
//           span.className = "pill other";
//           span.textContent = s;
//           tdOther.appendChild(span);
//         }
//       } else {
//         tdOther.innerHTML = "<span class='hint'>—</span>";
//       }
  
//       tr.appendChild(tdDate);
//       tr.appendChild(tdBuy);
//       tr.appendChild(tdSig);
//       tr.appendChild(tdOther);
//       $tbody.appendChild(tr);
//     }
  
//     // pagination numbers
//     $pages.innerHTML = "";
//     const totalPages = Math.max(1, Math.ceil(state.rows.length / TB_PAGE_SIZE));
//     for (let i = 0; i < totalPages; i++) {
//       const btn = document.createElement("button");
//       btn.className = "page-btn" + (i === state.page ? " active" : "");
//       btn.type = "button";
//       btn.textContent = String(i + 1);
//       btn.addEventListener("click", () => {
//         state.page = i;
//         tb_updateNav($root, state);
//         tb_renderPage($root, state);
//         // scroll to top of card on page change for better UX
//         $root.querySelector("#tb-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
//       });
//       $pages.appendChild(btn);
//     }
//   }
  
//   function tb_updateNav($root, state) {
//     const totalPages = Math.max(1, Math.ceil(state.rows.length / TB_PAGE_SIZE));
//     const $prev = $root.querySelector("#tb-prev");
//     const $next = $root.querySelector("#tb-next");
//     if ($prev) {
//       $prev.disabled = (state.page <= 0);
//       $prev.onclick = () => {
//         if (state.page > 0) { state.page -= 1; tb_updateNav($root, state); tb_renderPage($root, state); }
//       };
//     }
//     if ($next) {
//       $next.disabled = (state.page >= totalPages - 1);
//       $next.onclick = () => {
//         if (state.page < totalPages - 1) { state.page += 1; tb_updateNav($root, state); tb_renderPage($root, state); }
//       };
//     }
//   }
  
//   async function tb_init($root) {
//     const state = { rows: [], page: 0 };
//     // try server first
//     let rows = await tb_fetchRowsFromAPI(wlLoad(), 60);
//     if (!rows.length) {
//       // fallback to placeholder generation (keeps UX alive)
//       rows = tb_buildRows(60);
//     }
//     state.rows = rows;
//     tb_updateNav($root, state);
//     tb_renderPage($root, state);
//     $root.__tb_state = state;
//   }
  
//   async function tb_refresh($root) {
//     if (!$root) return;
//     const state = $root.__tb_state || { page: 0, rows: [] };
//     let rows = await tb_fetchRowsFromAPI(wlLoad(), 60);
//     if (!rows.length) rows = tb_buildRows(60);
//     state.rows = rows;
//     state.page = Math.min(state.page, Math.max(0, Math.ceil(state.rows.length / TB_PAGE_SIZE) - 1));
//     tb_updateNav($root, state);
//     tb_renderPage($root, state);
//     $root.__tb_state = state;
//   }


//   // --- Fetch real rows from server ---
// async function tb_fetchRowsFromAPI(watchlist, days = 60) {
//   if (!Array.isArray(watchlist) || !watchlist.length) return [];
//   try {
//     const res = await fetch("/api/today/recommendations", {
//       method: "POST",
//       headers: { "Content-Type": "application/json", "Accept": "application/json" },
//       body: JSON.stringify({ symbols: watchlist, days })
//     });
//     const js = await res.json().catch(() => ({}));
//     if (!res.ok || !js.ok) return [];
//     // rows: [{date, buys, signals, other}] newest-first
//     return Array.isArray(js.rows) ? js.rows : [];
//   } catch {
//     return [];
//   }
// }



// // --- Wire the fragment once injected ---
// function initTodayFragment($root) {
//   // render existing WL
//   wlRender($root);
//   // Initialize Today’s buy table now
//   tb_init($root);

//   // WL interactions
//   const $list = $root.querySelector("#wl-list");
//   const $input = $root.querySelector("#upd-ticker");
//   const $status = $root.querySelector("#upd-status");
//   $list?.addEventListener("click", (e) => {
//     const li = e.target.closest(".wl-item");
//     if (!li) return;
//     const sym = li.dataset.sym;
//     if (e.target.classList.contains("wl-remove")) {
//       wlRemove(sym); wlRender($root); renderTodaysBuy($root);
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
//     renderTodaysBuy($root);
//     if ($status) $status.textContent = `Added ${sym} to watchlist`;
//   });
//   loadCsvSymbolsInto($root);

//   // Search form
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
//       const r = await updateTicker(ticker, csrf);
//       if (r.ok) {
//         if ($status) $status.textContent = `✓ ${ticker} updated`;
//         wlAdd(ticker); wlRender($root); renderTodaysBuy($root);
//       } else {
//         if ($status) $status.textContent = r.data?.error || "Update failed";
//       }
//     } catch (err) {
//       if ($status) $status.textContent = String(err);
//     } finally {
//       if ($btn) $btn.disabled = false;
//     }
    
//   });

//   // Auto-update all watchlist on load
//   updateAllWatchlist($root, csrf);

//   // Auto-update all watchlist on load (already present)
//   updateAllWatchlist($root, csrf).then(() => {
//     // refresh table after updates so it reflects current WL
//     tb_refresh($root);
//   });

// }

// // ---------------------------
// // Init
// // ---------------------------
// renderStocks();



// /static/js/stocks.js  — clean, de-duped

// ---------------------------
// Legacy Tickers tab (kept)
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
  const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(sym)}/?asset=${asset}&min_rows=200&fresh_hours=72`;
  let res = await fetch(checkUrl);
  let data = await res.json().catch(() => ({}));
  if (res.ok && data.ok) return data;

  if (asset === "stock") {
    const fillUrl = `/api/analysis/fill_csv/${encodeURIComponent(sym)}/?tf=${encodeURIComponent(tf)}`;
    const fillRes = await fetch(fillUrl);
    const fillData = await fillRes.json().catch(() => ({}));
    if (!fillRes.ok || !fillData.ok) {
      throw new Error(fillData?.reason || `CSV fill failed (${fillRes.status})`);
    }
    res = await fetch(checkUrl);
    data = await res.json().catch(() => ({}));
    if (res.ok && data.ok) return data;
  }
  throw new Error(data?.reason || `CSV check failed (${res.status})`);
}

// ---------------------------
// Link guards (Tickers tab)
// ---------------------------
document.addEventListener("click", async (e) => {
  const a = e.target.closest("a.analysis");
  if (!a) return;
  e.preventDefault();

  const tr  = a.closest("tr");
  const sym = tr?.dataset?.sym || a.dataset.symbol || a.textContent.trim();
  const tf  = getTfFromHref(a.href);

  a.dataset.oldText = a.textContent;
  a.textContent = "Checking data…";
  try { await ensureCsv(sym, "stock", tf); location.href = a.href; }
  catch (err) { alert(`Cannot open ${sym}: ${err.message}`); a.textContent = a.dataset.oldText || "Open"; }
});

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
    if (!res.ok || !data.ok) throw new Error(data?.reason || `No HistoricalData_${sym}.csv`);
    location.href = a.href;
  } catch (err) {
    alert(`Cannot open historical for ${sym}: ${err.message}`);
    a.textContent = a.dataset.oldText || "Historical Data";
  }
});

// ---------------------------
// Today tab loader (fragment)
// ---------------------------
async function loadTodayPanel() {
  const panel = document.getElementById("panel-today");
  if (!panel) return;
  const res  = await fetch("/stocks/today/", { headers: { "X-Requested-With": "XMLHttpRequest" } });
  const html = await res.text();
  panel.innerHTML = html;
  initTodayFragment(panel);
}

// Hook into your existing setTab or hash changes (once)
(function ensureTabHook() {
  if (typeof window.setTab === 'function') {
    const original = window.setTab;
    window.setTab = function(hash) {
      original.call(this, hash);
      if ((hash || location.hash || '#tickers').toLowerCase() === '#today') loadTodayPanel();
    };
    window.setTab();
  } else {
    if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    window.addEventListener('hashchange', () => {
      if ((location.hash || '').toLowerCase() === '#today') loadTodayPanel();
    });
  }
})();

// ---------------------------
// Watchlist helpers
// ---------------------------
const WL_KEY = "watchlist.stocks";
function wlLoad(){ try { return JSON.parse(localStorage.getItem(WL_KEY)) || []; } catch { return []; } }
function wlSave(a){ localStorage.setItem(WL_KEY, JSON.stringify(a)); }
function wlAdd(s){ s=(s||"").trim().toUpperCase(); if(!s) return; const w=wlLoad(); if(!w.includes(s)){ w.push(s); w.sort(); wlSave(w);} }
function wlRemove(s){ wlSave(wlLoad().filter(x=>x!==s)); }
function wlRender($root){
  const $list = $root.querySelector("#wl-list");
  if (!$list) return;
  const wl = wlLoad();
  $list.innerHTML = "";
  if (!wl.length){ const li=document.createElement("li"); li.textContent="No tickers yet."; li.style.listStyle="none"; li.className="hint"; $list.appendChild(li); return; }
  for (const sym of wl){
    const li=document.createElement("li"); li.className="wl-item"; li.dataset.sym=sym;
    const left=document.createElement("div"); left.className="wl-sym"; left.textContent=sym;
    const btn=document.createElement("button"); btn.className="wl-remove"; btn.type="button"; btn.textContent="×"; btn.title="Remove from watchlist";
    li.appendChild(left); li.appendChild(btn); $list.appendChild(li);
  }
}

// CSV-backed dropdown
async function loadCsvSymbolsInto($root){
  const $ddl = $root.querySelector("#wl-dropdown");
  if (!$ddl) return;
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 8000);
  try {
    const res = await fetch("/api/today/csv_symbols", { headers:{Accept:"application/json"}, signal: controller.signal });
    clearTimeout(t);
    const js = await res.json().catch(()=> ({}));
    $ddl.innerHTML = "";
    if (!res.ok || !js.ok){ const o=document.createElement("option"); o.value=""; o.textContent=`Error: ${js?.error||res.status}`; $ddl.appendChild(o); return; }
    const list = Array.isArray(js.symbols) ? js.symbols.slice().sort() : [];
    if (!list.length){ const o=document.createElement("option"); o.value=""; o.textContent="No CSVs found"; $ddl.appendChild(o); return; }
    for (const sym of list){ const o=document.createElement("option"); o.value=sym; o.textContent=sym; $ddl.appendChild(o); }
  } catch (err) {
    clearTimeout(t);
    $ddl.innerHTML = "";
    const o=document.createElement("option"); o.value=""; o.textContent=(err.name==="AbortError")?"Timed out":"Load error"; $ddl.appendChild(o);
  }
}

// ---------------------------
// Today’s table (real data)
// ---------------------------
const TB_PAGE_SIZE = 10;

async function tb_fetchRowsFromAPI(watchlist, days=60){
  if (!Array.isArray(watchlist) || !watchlist.length) return [];
  try{
    const res = await fetch("/api/today/recommendations", {
      method:"POST", headers:{ "Content-Type":"application/json", "Accept":"application/json" },
      body: JSON.stringify({ symbols: watchlist, days })
    });
    const js = await res.json().catch(()=> ({}));
    if (!res.ok || !js.ok) return [];
    return Array.isArray(js.rows) ? js.rows : [];
  }catch{ return []; }
}

async function ts_fetchRowsFromAPI(watchlist, days = 60) {
  if (!Array.isArray(watchlist) || !watchlist.length) return [];
  try {
    const res = await fetch("/api/today/recommendations/sell", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ symbols: watchlist, days })
    });
    const js = await res.json().catch(() => ({}));
    if (!res.ok || !js.ok) return [];
    // rows: [{date, sells, signals, other}] newest-first
    return Array.isArray(js.rows) ? js.rows : [];
  } catch {
    return [];
  }
}


// minimal placeholder (only if API returns nothing)
function tb_buildRowsPlaceholder(days=10){
  const out=[], today=new Date(); today.setHours(0,0,0,0);
  for (let d=0; d<days; d++){
    const iso = new Date(today.getTime()-d*86400000).toISOString().slice(0,10);
    out.push({ date: iso, buys: [], signals: [], other: [] });
  }
  return out;
}

function tb_updateNav($root, state){
  const totalPages = Math.max(1, Math.ceil(state.rows.length / TB_PAGE_SIZE));
  const $prev = $root.querySelector("#tb-prev");
  const $next = $root.querySelector("#tb-next");
  if ($prev){ $prev.disabled = (state.page<=0); $prev.onclick = ()=>{ if(state.page>0){ state.page--; tb_updateNav($root,state); tb_renderPage($root,state);} }; }
  if ($next){ $next.disabled = (state.page>=totalPages-1); $next.onclick = ()=>{ if(state.page<totalPages-1){ state.page++; tb_updateNav($root,state); tb_renderPage($root,state);} }; }
}

function tb_renderPage($root, state){
  const $tbody = $root.querySelector("#tb-body");
  const $pages = $root.querySelector("#tb-pages");
  if (!$tbody || !$pages) return;

  const start = state.page * TB_PAGE_SIZE;
  const end   = Math.min(start + TB_PAGE_SIZE, state.rows.length);
  const slice = state.rows.slice(start, end);

  $tbody.innerHTML = "";
  for (const row of slice){
    const tr = document.createElement("tr");

    const tdDate = document.createElement("td");
    tdDate.textContent = row.date;

    const tdBuy = document.createElement("td");
    if (row.buys?.length){ for (const b of row.buys){ const s=document.createElement("span"); s.className="pill buy"; s.textContent=b; tdBuy.appendChild(s);} }
    else { tdBuy.innerHTML = "<span class='hint'>—</span>"; }

    const tdSig = document.createElement("td");
    if (row.signals?.length){ for (const sTxt of row.signals){ const s=document.createElement("span"); s.className="pill sig"; s.textContent=sTxt; tdSig.appendChild(s);} }
    else { tdSig.innerHTML = "<span class='hint'>—</span>"; }

    const tdOther = document.createElement("td");
    if (row.other?.length){ for (const oTxt of row.other){ const s=document.createElement("span"); s.className="pill other"; s.textContent=oTxt; tdOther.appendChild(s);} }
    else { tdOther.innerHTML = "<span class='hint'>—</span>"; }

    tr.appendChild(tdDate); tr.appendChild(tdBuy); tr.appendChild(tdSig); tr.appendChild(tdOther);
    $tbody.appendChild(tr);
  }

  $pages.innerHTML = "";
  const totalPages = Math.max(1, Math.ceil(state.rows.length / TB_PAGE_SIZE));
  for (let i=0;i<totalPages;i++){
    const btn=document.createElement("button");
    btn.className = "page-btn" + (i===state.page ? " active" : "");
    btn.type="button"; btn.textContent=String(i+1);
    btn.addEventListener("click", ()=>{ state.page=i; tb_updateNav($root,state); tb_renderPage($root,state); $root.querySelector("#tb-card")?.scrollIntoView({behavior:"smooth",block:"start"}); });
    $pages.appendChild(btn);
  }
}

async function tb_init($root){
  const state = { rows: [], page: 0 };
  let rows = await tb_fetchRowsFromAPI(wlLoad(), 60);
  if (!rows.length) rows = tb_buildRowsPlaceholder(10);
  state.rows = rows;
  tb_updateNav($root, state);
  tb_renderPage($root, state);
  $root.__tb_state = state;
}

async function tb_refresh($root){
  if (!$root) return;
  const state = $root.__tb_state || { rows: [], page: 0 };
  let rows = await tb_fetchRowsFromAPI(wlLoad(), 60);
  if (!rows.length) rows = tb_buildRowsPlaceholder(10);
  state.rows = rows;
  state.page = Math.min(state.page, Math.max(0, Math.ceil(state.rows.length / TB_PAGE_SIZE) - 1));
  tb_updateNav($root, state);
  tb_renderPage($root, state);
  $root.__tb_state = state;
}


// ====== SELL TABLE SCAFFOLD (structure only; signals wired next) ======
const TS_PAGE_SIZE = 10; // 10 dates per page

// function ts_buildRows(days = 60) {
//   // For now, just mirror the date range used by buy table; empty sell columns.
//   const out = [];
//   const today = new Date(); today.setHours(0,0,0,0);
//   for (let d = 0; d < days; d++) {
//     const dt = new Date(today.getTime() - d * 86400000);
//     const iso = dt.toISOString().slice(0,10);
//     out.push({ date: iso, sells: [], signals: [], other: [] });
//   }
//   return out; // newest first
// }

function ts_renderPage($root, state) {
  const $tbody = $root.querySelector("#ts-body");
  const $pages = $root.querySelector("#ts-pages");
  if (!$tbody || !$pages) return;

  const start = state.page * TS_PAGE_SIZE;
  const end   = Math.min(start + TS_PAGE_SIZE, state.rows.length);
  const slice = state.rows.slice(start, end);

  // body
  $tbody.innerHTML = "";
  for (const row of slice) {
    const tr = document.createElement("tr");

    const tdDate = document.createElement("td");
    tdDate.textContent = row.date;

    const tdSell = document.createElement("td");
    if (row.sells.length) {
      for (const s of row.sells) {
        const span = document.createElement("span");
        span.className = "pill buy";  // reuse pill style
        span.textContent = s;
        tdSell.appendChild(span);
      }
    } else {
      tdSell.innerHTML = "<span class='hint'>—</span>";
    }

    const tdSig = document.createElement("td");
    if (row.signals.length) {
      for (const s of row.signals) {
        const span = document.createElement("span");
        span.className = "pill sig";
        span.textContent = s;
        tdSig.appendChild(span);
      }
    } else {
      tdSig.innerHTML = "<span class='hint'>—</span>";
    }

    const tdOther = document.createElement("td");
    if (row.other.length) {
      for (const s of row.other) {
        const span = document.createElement("span");
        span.className = "pill other";
        span.textContent = s;
        tdOther.appendChild(span);
      }
    } else {
      tdOther.innerHTML = "<span class='hint'>—</span>";
    }

    tr.appendChild(tdDate);
    tr.appendChild(tdSell);
    tr.appendChild(tdSig);
    tr.appendChild(tdOther);
    $tbody.appendChild(tr);
  }

  // pagination numbers
  $pages.innerHTML = "";
  const totalPages = Math.max(1, Math.ceil(state.rows.length / TS_PAGE_SIZE));
  for (let i = 0; i < totalPages; i++) {
    const btn = document.createElement("button");
    btn.className = "page-btn" + (i === state.page ? " active" : "");
    btn.type = "button";
    btn.textContent = String(i + 1);
    btn.addEventListener("click", () => {
      state.page = i;
      ts_updateNav($root, state);
      ts_renderPage($root, state);
      $root.querySelector("#ts-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $pages.appendChild(btn);
  }
}

function ts_init($root) {
  const state = { rows: [], page: 0 };
  $root.__ts_state = state;
  ts_updateNav($root, state);
  ts_renderPage($root, state);
  // first real fetch
  ts_refresh($root);
}

async function ts_refresh($root) {
  if (!$root) return;
  const state = $root.__ts_state || { rows: [], page: 0 };

  const symbols = wlLoad();
  if (!symbols.length) {
    state.rows = [];
    ts_updateNav($root, state);
    ts_renderPage($root, state);
    $root.__ts_state = state;
    return;
  }

  try {
    state.rows = await ts_fetchRowsFromAPI(symbols, 60);
    const totalPages = Math.max(1, Math.ceil(state.rows.length / (typeof TS_PAGE_SIZE !== "undefined" ? TS_PAGE_SIZE : 10)));
    state.page = Math.min(state.page, totalPages - 1);
  } catch (err) {
    console.error("Sell rows fetch failed:", err);
    state.rows = [];
  }

  ts_updateNav($root, state);
  ts_renderPage($root, state);
  $root.__ts_state = state;
}


function ts_updateNav($root, state) {
  const totalPages = Math.max(1, Math.ceil(state.rows.length / TS_PAGE_SIZE));
  const $prev = $root.querySelector("#ts-prev");
  const $next = $root.querySelector("#ts-next");
  if ($prev) {
    $prev.disabled = (state.page <= 0);
    $prev.onclick = () => {
      if (state.page > 0) { state.page -= 1; ts_updateNav($root, state); ts_renderPage($root, state); }
    };
  }
  if ($next) {
    $next.disabled = (state.page >= totalPages - 1);
    $next.onclick = () => {
      if (state.page < totalPages - 1) { state.page += 1; ts_updateNav($root, state); ts_renderPage($root, state); }
    };
  }
}

// function ts_init($root) {
//   const state = { rows: ts_buildRows(60), page: 0 };
//   ts_updateNav($root, state);
//   ts_renderPage($root, state);
//   $root.__ts_state = state;
// }

// function ts_refresh($root) {
//   if (!$root) return;
//   const state = $root.__ts_state || { page: 0 };
//   state.rows = ts_buildRows(60);
//   state.page = Math.min(state.page, Math.max(0, Math.ceil(state.rows.length / TS_PAGE_SIZE) - 1));
//   ts_updateNav($root, state);
//   ts_renderPage($root, state);
//   $root.__ts_state = state;
// }



// ---------------------------
// Wire the fragment (once)
// ---------------------------
function initTodayFragment($root){
  wlRender($root);

  const $list   = $root.querySelector("#wl-list");
  const $ddl    = $root.querySelector("#wl-dropdown");
  const $add    = $root.querySelector("#wl-add-btn");
  const $form   = $root.querySelector("#upd-form");
  const $input  = $root.querySelector("#upd-ticker");
  const $btn    = $root.querySelector("#upd-btn");
  const $status = $root.querySelector("#upd-status");
  const csrf    = $form?.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';

  // WL list clicks
  $list?.addEventListener("click", (e) => {
    const li = e.target.closest(".wl-item"); if (!li) return;
    const sym = li.dataset.sym;
    if (e.target.classList.contains("wl-remove")){
      wlRemove(sym);
      wlRender($root);
      // refresh BOTH tables
      tb_refresh($root);
      ts_refresh($root);
      $status && ($status.textContent=`Removed ${sym}`);
    } else {
      if ($input) $input.value = sym;
    }
  });

  // Dropdown + add
  $add?.addEventListener("click", () => {
    const sym = ($ddl?.value||"").trim().toUpperCase(); if (!sym) return;
    wlAdd(sym);
    wlRender($root);
    // refresh BOTH tables
    tb_refresh($root);
    ts_refresh($root);
    $status && ($status.textContent=`Added ${sym}`);
  });
  loadCsvSymbolsInto($root);

  // Search -> update CSV then refresh tables
  $form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const ticker = ($input?.value||"").trim().toUpperCase();
    if (!ticker){ $status && ($status.textContent="Enter a ticker (e.g., AAPL)"); return; }
    if ($btn) $btn.disabled = true;
    $status && ($status.textContent="Updating…");
    try{
      const fd=new FormData(); fd.append("ticker", ticker);
      const res = await fetch("/api/today/update", { method:"POST", headers:{ "X-CSRFToken": csrf }, body: fd });
      const js  = await res.json().catch(()=> ({}));
      if (res.ok && js.ok){
        wlAdd(ticker);
        wlRender($root);
        // refresh BOTH tables
        await tb_refresh($root);
        await ts_refresh($root);
        $status && ($status.textContent=`✓ ${ticker} updated`);
      } else {
        $status && ($status.textContent = js?.error || `Error ${res.status}`);
      }
    }catch(err){
      $status && ($status.textContent=String(err));
    } finally {
      if ($btn) $btn.disabled=false;
    }
  });

  // First render of BOTH tables
  tb_init($root);
  ts_init($root);   // <-- add this

  // Background auto-update of WL, then refresh BOTH
  (async () => {
    const wl = wlLoad(); if (!wl.length) return;
    $status && ($status.textContent = `Updating ${wl.length} tickers…`);
    const BATCH=5;
    for (let i=0;i<wl.length;i+=BATCH){
      await Promise.allSettled(
        wl.slice(i,i+BATCH).map(async sym=>{
          const fd=new FormData(); fd.append("ticker", sym);
          await fetch("/api/today/update", { method:"POST", headers:{ "X-CSRFToken": csrf }, body: fd });
        })
      );
    }
    $status && ($status.textContent = "Watchlist up to date.");
    await tb_refresh($root);
    await ts_refresh($root);  // <-- add this
  })();
}


// ---------------------------
// Init
// ---------------------------
renderStocks();
