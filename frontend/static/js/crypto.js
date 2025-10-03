// // /static/investments.js  — minimal debug-friendly handler
// document.querySelectorAll(".get-csv button").forEach((btn) => {
//   btn.addEventListener("click", async () => {
//     const symbol = btn.dataset.symbol || btn.dataset.sym || btn.textContent.trim();
//     const statusDiv = document.getElementById("csv-status");

//     // UI: disable during request
//     btn.disabled = true;
//     btn.textContent = "Working…";

//     try {
//       const fd = new FormData();
//       // IMPORTANT: api_get_csv expects "BTC" / "SOL" / "ADA" (short key), not "BTC/USD"
//       const short = symbol.includes("/") ? symbol.split("/")[0] : symbol;
//       fd.append("symbol", short);        // e.g. "SOL"
//       fd.append("mode", "full");      // uncomment to force full backfill

//       const res = await fetch("/api/get-csv/", { method: "POST", body: fd });

//       // read response text first (so we can show tracebacks), then try json
//       const raw = await res.text();
//       let data = {};
//       try { data = JSON.parse(raw); } catch {}

//       if (res.ok && data.ok) {
//         statusDiv.textContent = `✅ ${short} updated: +${data.added_rows} (rows=${data.rows}) [${data.from} → ${data.to}]`;
//         statusDiv.style.color = "green";
//       } else {
//         // show whatever the server sent (JSON error or traceback)
//         statusDiv.textContent = `❌ ${short} failed (${res.status}) — ${data.error || raw}`;
//         statusDiv.style.color = "crimson";
//       }
//     } catch (err) {
//       statusDiv.textContent = `❌ Request error — ${err}`;
//       statusDiv.style.color = "crimson";
//     } finally {
//       btn.disabled = false;
//       btn.textContent = "Get CSV";
//     }
//   });
// });


// /static/js/crypto.js
// Make Crypto behave like Stocks: table + 3 actions, auto CSV check/fill on click.

const ASSETS = ["BTC","ETH","SOL","ADA","XRP","DOGE","DOT","LINK"];  // edit as you like

function rowHTML(sym) {
  const base = `/api/analysis`;
  // mirror stocks.js query string; you can tune tf/start/end/strat later
  const qsC = `?tf=1h&start=2025-09&end=2025-10`;
  const qsE = `?tf=1h&start=2025-09&end=2025-10&strat=ema_stack_long`;
  const qsA = `?tf=1h&start=2025-09&end=2025-10&strat=kalman_cross`;
  return `
    <tr data-sym="${sym}">
      <td><strong>${sym}</strong></td>
      <td class="actions">
        <a class="analysis" href="${base}/candles/${sym}/${qsC}">Candlestick</a>
        <a class="analysis" href="${base}/equity/${sym}/${qsE}">Cumulative</a>
        <a class="analysis" href="${base}/all/${sym}/${qsA}">ALL</a>
      </td>
    </tr>
  `;
}

function renderCrypto() {
  const tbody = document.getElementById("tbody-crypto");
  const rows = [...ASSETS].sort((a,b)=>a.localeCompare(b)).map(rowHTML).join("");
  tbody.innerHTML = rows;
}

/**
 * Ensure CSV exists and is fresh enough.
 * For crypto we: 
 *   1) check via /api/analysis/check_csv/<sym>/?asset=crypto
 *   2) if missing/stale, fill using your existing /api/get-csv/ POST endpoint
 *   3) re-check, then allow navigation
 */
async function ensureCsvCrypto(sym, tf) {
  const short = sym.includes("/") ? sym.split("/")[0] : sym; // server expects "SOL", "BTC", etc.

  // 1) Check
  const checkUrl = `/api/analysis/check_csv/${encodeURIComponent(short)}/?asset=crypto&min_rows=200&fresh_hours=72`;
  let res = await fetch(checkUrl, { method: "GET" });
  let data = await res.json().catch(()=>({}));
  if (res.ok && data.ok) return data;

  // 2) Fill via your existing endpoint
  //    This mirrors your previous investments.js (FormData + symbol + mode)
  const fd = new FormData();
  fd.append("symbol", short);
  // choose a light mode — "quick" or leave blank; use "full" only when you truly want a deep backfill
  fd.append("mode", "quick");

  const fillRes = await fetch("/api/get-csv/", { method: "POST", body: fd });
  const fillData = await fillRes.json().catch(()=>({}));
  if (!fillRes.ok || !fillData.ok) {
    const reason = fillData.reason || `CSV fill failed (${fillRes.status})`;
    throw new Error(reason);
  }

  // 3) Re-check
  res = await fetch(checkUrl, { method: "GET" });
  data = await res.json().catch(()=>({}));
  if (!res.ok || !data.ok) {
    const reason = data.reason || `CSV still not ready (${res.status})`;
    throw new Error(reason);
  }
  return data;
}

/** Click-to-open with pre-check, exactly like stocks.js */
function wireCheckThenGoCrypto() {
  document.addEventListener("click", async (ev) => {
    const a = ev.target.closest("a.analysis");
    if (!a) return;

    ev.preventDefault();
    const tr = a.closest("tr[data-sym]");
    const sym = tr?.getAttribute("data-sym");
    if (!sym) return;

    // Optional: extract timeframe from URL if you want to pass to fill; default 1h
    const url = new URL(a.href, location.origin);
    const tf = url.searchParams.get("tf") || "1h";

    // UI feedback
    a.dataset.oldText = a.textContent;
    a.textContent = "Checking data…";

    try {
      await ensureCsvCrypto(sym, tf);
      location.href = a.href; // proceed to target page
    } catch (err) {
      alert(`Cannot open ${sym}: ${err.message}`);
      a.textContent = a.dataset.oldText || "Open";
    }
  });
}

// init
renderCrypto();
wireCheckThenGoCrypto();


  