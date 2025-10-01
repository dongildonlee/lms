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


// ---------- config: put all symbols here ----------
const ASSETS = ["BTC", "SOL", "ADA", "DOGE", "DOT", "ETH","LINK", "XRP"]; // later you can fetch this from the server

function rowHtml(sym) {
  return `
    <div class="row" data-sym="${sym}">
      <span class="name">${sym}</span>
      <button class="get-csv" data-symbol="${sym}">Get CSV</button>
      <button class="analysis" data-symbol="${sym}">Analysis ▾</button>
      <span class="mini-menu" id="menu-${sym}" style="display:none; margin-left:12px;">
        <a href="/api/analysis/candles/${sym}/" target="_blank">Candlestick chart</a>
        <a href="/api/analysis/cumprofit/${sym}/" target="_blank">Cumulative profit</a>
        <a href="/api/analysis/all/${sym}/" target="_blank">ALL</a> 
      </span>
    </div>`;
}

function renderAssets() {
  const box = document.getElementById("assets");
  const sorted = [...ASSETS].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  box.innerHTML = sorted.map(rowHtml).join("");
}

async function getCsv(symbol, buttonEl) {
  const statusDiv = document.getElementById("csv-status");
  // Build form data
  const fd = new FormData();
  fd.append("symbol", symbol);      // "BTC" / "SOL" / "ADA"
  // fd.append("mode", "full");     // uncomment to force full backfill

  // UI: disable during request
  const prevText = buttonEl.textContent;
  buttonEl.disabled = true;
  buttonEl.textContent = "Working…";

  try {
    const res = await fetch("/api/get-csv/", { method: "POST", body: fd });
    const raw = await res.text();
    let data = {}; try { data = JSON.parse(raw); } catch {}

    if (res.ok && data.ok) {
      statusDiv.textContent =
        `✅ ${symbol} updated: +${data.added_rows} (rows=${data.rows}) [${data.from} → ${data.to}]`;
      statusDiv.style.color = "green";
    } else {
      statusDiv.textContent = `❌ ${symbol} failed (${res.status}) — ${data.error || raw}`;
      statusDiv.style.color = "crimson";
    }
  } catch (err) {
    statusDiv.textContent = `❌ Request error — ${err}`;
    statusDiv.style.color = "crimson";
  } finally {
    buttonEl.disabled = false;
    buttonEl.textContent = prevText;
  }
}

function wireEvents() {
  const assetsBox = document.getElementById("assets");

  // Event delegation keeps this working even if you re-render
  assetsBox.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;

    // Get CSV
    if (t.classList.contains("get-csv")) {
      const sym = t.dataset.symbol;
      if (sym) getCsv(sym, t);
      return;
    }

    // Toggle analysis menu
    if (t.classList.contains("analysis")) {
      const sym = t.dataset.symbol;
      const menu = document.getElementById(`menu-${sym}`);
      if (menu) menu.style.display = (menu.style.display === "none" ? "inline" : "none");
      return;
    }
  });
}

// -------- init --------
renderAssets();
wireEvents();

  