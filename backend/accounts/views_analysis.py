# backend/accounts/views_analysis.py
from pathlib import Path
import json
import pandas as pd
import plotly.graph_objects as go
from django.http import JsonResponse, HttpRequest
from django.http import HttpResponse, HttpResponseBadRequest
 
from string import Template
from html import escape  # (you already use escape below; keep this too)
from django.urls import reverse
import re, os, sys, time, subprocess, tempfile, socket
from urllib.parse import quote
import importlib.util
from .analysis_helpers import add_markers_to_candle, build_trades_for_strategy, render_all_like_page
from . import views_data
from django.utils import timezone
from django.shortcuts import render
from .strategies.ema_stack import build_trades 
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Anchor from this file → .../backend → .../backend/data/stocks
_ACCOUNTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR  = _ACCOUNTS_DIR.parent
_HIST_DIR     = (_BACKEND_DIR / "data" / "stocks").resolve()


SYMBOL_MAP = {
    "BTC": "BTC/USD",
    "SOL": "SOL/USD",
    "ADA": "ADA/USD",
    "DOGE": "DOGE/USD",
    "ETH": "ETH/USD",
    "LINK": "LINK/USD",
    "DOT": "DOT/USD",
    "XRP": "XRP/USD"
}

def _csv_path(symbol_key: str) -> Path:
    return DATA_DIR / f"{symbol_key.lower()}usd_5m_coinbase.csv"


def _historical_csv_path(symbol_key: str):
    """
    Look for HistoricalData_<TICKER>.csv under backend/data/stocks,
    tolerating case and extension (.csv/.CSV).
    """
    sym_up = (symbol_key or "").strip().upper()
    if not sym_up:
        return None
    candidates = [
        _HIST_DIR / f"HistoricalData_{sym_up}.csv",
        _HIST_DIR / f"HistoricalData_{sym_up}.CSV",
        _HIST_DIR / f"historicaldata_{sym_up}.csv",  # just in case
        _HIST_DIR / f"historicaldata_{sym_up}.CSV",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Last-ditch: glob anything that contains the ticker
    for p in _HIST_DIR.glob(f"*{sym_up}*.csv"):
        if p.is_file():
            return p
    for p in _HIST_DIR.glob(f"*{sym_up}*.CSV"):
        if p.is_file():
            return p
    return None


# --- replace the whole _load_basic_df with this ---
def _load_basic_df(path: Path) -> pd.DataFrame:
    import pandas as pd

    df = pd.read_csv(path)

    # Normalize column lookup (case-insensitive)
    colmap = {c.lower(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in colmap:
                return colmap[n]
        return None

    # ---------- timestamp ----------
    ts = None
    if "ts" in df.columns:
        ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    elif {"date", "time"}.issubset({c.lower() for c in df.columns}):
        dcol, tcol = pick("date"), pick("time")
        ts = pd.to_datetime(df[dcol].astype(str) + " " + df[tcol].astype(str), utc=True, errors="coerce")
    elif pick("date") is not None:
        dcol = pick("date")
        ts = pd.to_datetime(df[dcol], utc=True, errors="coerce")
    else:
        # last-ditch: first datetime-parsable column
        for c in df.columns:
            s = pd.to_datetime(df[c], utc=True, errors="coerce")
            if s.notna().any():
                ts = s
                break
    if ts is None:
        raise ValueError("CSV must contain a datetime-like column (ts or date[/time]).")

    # ---------- choose OHLCV with synonyms ----------
    open_col  = pick("open")
    high_col  = pick("high")
    low_col   = pick("low")
    # Apple/Yahoo often use "Close/Last" or "Adj Close"
    close_col = pick("close", "close/last", "adj close", "adj_close", "adjclose")
    vol_col   = pick("volume", "vol")

    # Fallbacks (use ‘Open’/’High’/’Low’ title case if present)
    if open_col is None and "Open" in df.columns:  open_col = "Open"
    if high_col is None and "High" in df.columns:  high_col = "High"
    if low_col  is None and "Low"  in df.columns:  low_col  = "Low"

    if close_col is None:
        # Apple order is usually Date, Close/Last, Volume, Open, High, Low
        if "Close/Last" in df.columns: close_col = "Close/Last"
        else:
            # very last resort: second column if it looks numeric, otherwise first numeric column
            for c in list(df.columns)[1:] + list(df.columns)[:1]:
                s = pd.to_numeric(df[c], errors="coerce")
                if s.notna().any():
                    close_col = c
                    break

    # ---------- build canonical frame ----------
    out = pd.DataFrame({
        "ts": ts,
        "open":  df[open_col]  if open_col  in df.columns else df[close_col],
        "high":  df[high_col]  if high_col  in df.columns else df[close_col],
        "low":   df[low_col]   if low_col   in df.columns else df[close_col],
        "close": df[close_col],
    })
    out["volume"] = df[vol_col] if (vol_col and vol_col in df.columns) else 0

    # ---------- coerce numerics (strip $, ,) ----------
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            s = out[c].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False)
            out[c] = pd.to_numeric(s, errors="coerce")

    # Clean + sort
    out = out.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return out



# def _render_plot_html(fig: go.Figure, page_title: str) -> HttpResponse:
#     # Use Plotly's built-in serializer
#     fig_json = fig.to_json()  # returns a JSON string with data+layout
#     html = f"""<!doctype html>
# <html lang="en">
# <head>
#   <meta charset="utf-8" />
#   <title>{page_title}</title>
#   <meta name="viewport" content="width=device-width, initial-scale=1" />
#   <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
#   <style>
#     body{{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;padding:16px;}}
#     a{{text-decoration:none}}
#     .back{{margin-bottom:12px;display:inline-block}}
#   </style>
# </head>
# <body>
#   <a class="back" href="/investments">← Back to Investments</a>
#   <div id="chart" style="max-width:1200px;"></div>
#   <script>
#     const fig = {fig_json};
#     Plotly.newPlot("chart", fig.data, fig.layout, {{responsive:true}});
#   </script>
# </body>
# </html>"""
#     return HttpResponse(html)

def _render_plot_html(fig: go.Figure, page_title: str) -> HttpResponse:
    # Use Plotly's built-in serializer
    fig_json = fig.to_json()  # returns a JSON string with data+layout
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{page_title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
  <style>
    body{{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;padding:16px;}}
    a{{text-decoration:none}}
    .back{{margin-bottom:12px;display:inline-block}}
  </style>
</head>
<body>
  <!-- changed: give the link an id and neutral default -->
  <a id="back-link" class="back" href="/crypto">← Back</a>

  <div id="chart" style="max-width:1200px;"></div>

  <script>
    // NEW: set back link based on ?asset=...
    (function() {{
      const params = new URLSearchParams(location.search);
      const asset = (params.get('asset') || '').toLowerCase();
      const back = document.getElementById('back-link');
      if (asset === 'stock') {{
        back.href = '/stocks';
        back.textContent = '← Back to stocks';
      }} else {{
        back.href = '/crypto';
        back.textContent = '← Back to crypto';
      }}
    }})();

    // Plotly render
    const fig = {fig_json};
    Plotly.newPlot("chart", fig.data, fig.layout, {{responsive:true}});
  </script>
</body>
</html>"""
    return HttpResponse(html)



# def _pick_free_port(host: str = "127.0.0.1") -> int:
#     """Pick an available TCP port on the given host."""
#     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#         s.bind((host, 0))
#         return s.getsockname()[1]

# def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
#     """Wait until a TCP connection to (host, port) succeeds or timeout expires."""
#     deadline = time.time() + timeout
#     while time.time() < deadline:
#         try:
#             with socket.create_connection((host, port), timeout=0.3):
#                 return True
#         except OSError:
#             time.sleep(0.25)
#     return False

# def _module_available(modname: str) -> bool:
#     """Check if a module can be imported (without importing it)."""
#     return importlib.util.find_spec(modname) is not None

# import os, sys, time, subprocess, tempfile, socket
# from urllib.parse import quote
# import importlib.util

def _module_available(modname: str) -> bool:
    return importlib.util.find_spec(modname) is not None

def _pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.25)
    return False

def _read_log(path: str, max_bytes: int = 20000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"(could not read log: {e})"



def analysis_candles(request, symbol_key: str):
    symbol_key = (symbol_key or "").upper()

    # --- Resolve CSV path (crypto via SYMBOL_MAP; otherwise treat as stock) ---
    if symbol_key in SYMBOL_MAP:
        csv_path = _csv_path(symbol_key)
        display = f"{symbol_key}/USD"
    else:
        p = _find_csv_for_symbol(symbol_key, asset="stock")
        if p is None:
            return HttpResponseBadRequest("CSV not found for symbol. Click 'Get CSV' first.")
        csv_path = p
        display = symbol_key  # neutral label for stocks

    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")

    df = _load_basic_df(csv_path)

    # allow ?n=300 to control how many candles we show (default 300)
    try:
        N = int(request.GET.get("n", "300"))
    except ValueError:
        N = 300

    tail = df.tail(N).copy()
    

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail["ts"], open=tail["open"], high=tail["high"], low=tail["low"], close=tail["close"],
        name=display
    ))

    # Optional EMAs if present (unchanged)
    for col, label in [("ema20","EMA20"), ("ema50","EMA50"), ("ema100","EMA100")]:
        if col in tail.columns and tail[col].notna().any():
            fig.add_trace(go.Scatter(x=tail["ts"], y=tail[col], mode="lines", name=label))
    
    
    # Keep existing styling (unchanged)
    fig.update_layout(
        title=f"{display} — last {len(tail)} × 5m candles",
        xaxis_rangeslider_visible=True,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
    fig.update_yaxes(title_text="Price (USD)")

    return _render_plot_html(fig, f"{symbol_key} Candles")


def analysis_cumprofit(request, symbol_key: str):
    """Simple buy-and-hold cumulative profit curve from close-to-close returns."""
    symbol_key = (symbol_key or "").upper()

    # --- Resolve CSV path (crypto via SYMBOL_MAP; otherwise treat as stock) ---
    if symbol_key in SYMBOL_MAP:
        csv_path = _csv_path(symbol_key)
        display = f"{symbol_key}/USD"
    else:
        p = _find_csv_for_symbol(symbol_key, asset="stock")
        if p is None:
            return HttpResponseBadRequest("CSV not found for symbol. Click 'Get CSV' first.")
        csv_path = p
        display = symbol_key  # neutral label for stocks

    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")

    df = _load_basic_df(csv_path)

    # cumulative buy & hold % return
    df["ret"] = df["close"].pct_change().fillna(0.0)
    df["cum"] = (1.0 + df["ret"]).cumprod() - 1.0  # fraction

    # allow ?n= to control window shown
    try:
        N = int(request.GET.get("n", "5000"))
    except ValueError:
        N = 5000
    tail = df.tail(N).copy()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=tail["ts"], y=(tail["cum"] * 100.0),
        mode="lines", name="Cumulative % (buy & hold)"
    ))
    fig.update_layout(
        title=f"{display} — Buy & Hold Cumulative Return (last {len(tail)} bars)",
        xaxis_rangeslider_visible=True,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=50, b=30),
        yaxis_title="Cumulative Return (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
    return _render_plot_html(fig, f"{symbol_key} Cumulative Profit")



def stepwise_equity_from_trades(trades_df, time_index, start_value=1.0):
    """
    One jump per trade at the exit bar, flat otherwise.
    Needs 'exit_ts' (datetime-like) and either 'pct' (fraction) or 'pnl_pct' (percent).
    """
    idx = pd.to_datetime(time_index)
    eq = pd.Series(start_value, index=idx)

    if trades_df is None or trades_df.empty:
        return eq

    # choose a return column and normalize to fraction
    if "pct" in trades_df.columns:
        pnl_frac = trades_df["pct"].astype(float)
    elif "pnl_pct" in trades_df.columns:
        pnl_frac = trades_df["pnl_pct"].astype(float) / 100.0
    else:
        # nothing to jump with
        return eq

    exits = pd.to_datetime(trades_df["exit_ts"])
    cur = float(start_value)

    for t, r in zip(exits, pnl_frac):
        pos = idx.searchsorted(pd.Timestamp(t), side="left")
        if pos < len(idx):
            cur *= (1.0 + float(r))
            eq.iloc[pos:] = cur

    return eq

# ===== DRY helpers =====
FEE_DEFAULT = 0.001  # 0.1% per fill

def _pnl_long(entry_px: float, exit_px: float, fee: float) -> float:
    return (exit_px / entry_px) * (1 - fee) * (1 - fee) - 1.0  # fraction

def _pnl_short(entry_px: float, exit_px: float, fee: float) -> float:
    return (entry_px / exit_px) * (1 - fee) * (1 - fee) - 1.0  # fraction

def _mfe_mae(view, side: str, entry_i: int, exit_i: int, entry_px: float) -> tuple[float,float]:
    win = view.iloc[entry_i:exit_i+1]
    if side == "long":
        mfe = (win["high"].max() / entry_px - 1.0) * 100.0
        mae = (win["low"].min()  / entry_px - 1.0) * 100.0
    else:
        mfe = (entry_px / win["low"].min()  - 1.0) * 100.0
        mae = (entry_px / win["high"].max() - 1.0) * 100.0
    return mfe, mae

# def _append_trade(trades: list, view, side: str, entry_i: int, exit_i: int, fee: float):
#     entry_px = float(view["close"].iat[entry_i])
#     exit_px  = float(view["close"].iat[exit_i])
#     pnl_frac = _pnl_long(entry_px, exit_px, fee) if side == "long" else _pnl_short(entry_px, exit_px, fee)
#     mfe, mae = _mfe_mae(view, side, entry_i, exit_i, entry_px)
#     trades.append({
#         "side": side,
#         "entry_ts": view["ts"].iat[entry_i],
#         "exit_ts":  view["ts"].iat[exit_i],
#         "entry_px": entry_px,
#         "exit_px":  exit_px,
#         "pnl_pct":  pnl_frac * 100.0,
#         "runup_pct": mfe,
#         "drawdown_pct": mae,
#     })




# # ===== One generic builder =====
# def build_trades(view: pd.DataFrame, *, mode: str, fee: float) -> pd.DataFrame:
#     """
#     mode: 'long', 'short', or 'both'
#     TradingView-like execution:
#       - detect flip on bar i
#       - EXIT on bar i CLOSE
#       - ENTER on bar i+1 OPEN (if a stack is ON)
#     """
#     long_stack, short_stack = _stack_masks(view)
#     N = len(view)
#     if N < 2:
#         return pd.DataFrame()

#     def _enter_idx(i_flip: int) -> int | None:
#         j = i_flip + 1
#         return j if j < N else None  # need a next bar to enter

#     trades: list[dict] = []

#     if mode in {"long", "short"}:
#         stack = long_stack if mode == "long" else short_stack
#         in_pos, entry_i = False, None

#         for i in range(N):  # i is the bar we *observe*
#             turn_on  = bool(stack.iat[i]) and (not bool(stack.iat[i-1]) if i > 0 else True)
#             turn_off = (not bool(stack.iat[i])) and (bool(stack.iat[i-1]) if i > 0 else False)

#             if not in_pos and turn_on:
#                 j = _enter_idx(i)
#                 if j is not None:
#                     in_pos, entry_i = True, j

#             elif in_pos and turn_off:
#                 _append_trade(trades, view, mode, entry_i, i, fee)
#                 in_pos, entry_i = False, None

#         # If still in position at the very end, liquidate on the *last* bar close
#         if in_pos and entry_i is not None:
#             _append_trade(trades, view, mode, entry_i, N - 1, fee)

#         return _finalize_trades(trades)

#     # ---- mode == "both": flip between sides with TV-style scheduling ----
#     side, entry_i = None, None

#     for i in range(N):
#         want_long, want_short = bool(long_stack.iat[i]), bool(short_stack.iat[i])

#         if side is None:
#             # schedule an entry for next bar’s open if any stack is ON now
#             if want_long or want_short:
#                 j = _enter_idx(i)
#                 if j is not None:
#                     side, entry_i = ("long" if want_long else "short"), j

#         else:
#             # need to close current side on this bar's close?
#             need_close = (side == "long" and not want_long) or (side == "short" and not want_short)
#             if need_close:
#                 _append_trade(trades, view, side, entry_i, i, fee)
#                 side, entry_i = None, None
#                 # if the opposite stack is ON already on this bar, schedule a new entry for next open
#                 if want_long or want_short:
#                     j = _enter_idx(i)
#                     if j is not None:
#                         side, entry_i = ("long" if want_long else "short"), j

#     # liquidate any open position on the last bar's close
#     if side is not None and entry_i is not None:
#         _append_trade(trades, view, side, entry_i, N - 1, fee)

#     return _finalize_trades(trades)



def resample_ohlc(df_in: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV data with EMAs."""
    if not rule:  # passthrough for 5m
        out = df_in.copy()
    else:
        x = df_in.set_index("ts")
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }
        out = (
            x.resample(rule)
             .agg(agg)
             .dropna(subset=["open", "high", "low", "close"])
             .reset_index()
        )
    for span in (20, 50, 100):
        col = f"ema{span}"
        out[col] = out["close"].ewm(span=span, adjust=False, min_periods=span).mean()
    return out


# In backend/accounts/views_analysis.py
from django.http import HttpResponse, HttpResponseBadRequest
from django.urls import reverse
import pandas as pd
import plotly.graph_objects as go

# import the new helpers
from .analysis_helpers import (
    compute_period_window,
    slice_and_resample,
    build_trades_for_strategy,
    make_candle_fig,
    make_equity_fig,
    trades_table_html,
    trades_table_js,
    BAR_MS_MAP,
)


def analysis_all(request, symbol_key: str):
    """
    Candles + cumulative + Trades table (sortable, row-click zoom).
    Lean version: EMA stack (long/short/both) and Lorentzian only.
    """
    # lazy imports to avoid circulars
    from .analysis_helpers import (
        FEE_DEFAULT,
        BAR_MS_MAP,
        compute_period_window,
        slice_and_resample,
        make_candle_fig,
        make_equity_fig,
        add_markers_to_candle,
        trades_table_html,
        trades_table_js,
        build_trades_for_strategy,
    )

    # fee
    try:
        fee = float(request.GET.get("fee", str(FEE_DEFAULT)))
    except Exception:
        fee = float(FEE_DEFAULT)

    # ---- symbol (crypto map OR stock fallback) ----
    symbol_key = (symbol_key or "").upper()
    if symbol_key in SYMBOL_MAP:
        csv_path = _csv_path(symbol_key)                       # crypto path (unchanged)
    else:
        p = _find_csv_for_symbol(symbol_key, asset="stock")    # <-- stock CSV discovery
        if p is None:
            return HttpResponseBadRequest("CSV not found for symbol. Click 'Get CSV' first.")
        csv_path = p

    # data
    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")
    df = _load_basic_df(csv_path)
    if df.empty or df["ts"].isna().all():
        return HttpResponseBadRequest("No data in CSV.")

    # timeframe & window (unchanged)
    tf = (request.GET.get("tf") or "5m").lower()
    tf = tf if tf in {"5m", "1h", "4h", "1d"} else "5m"
    window = compute_period_window(df, request.GET.get("start"), request.GET.get("end"))
    view = slice_and_resample(df, window, tf)

    # strategies (rolled back to 4 options) (unchanged)
    allowed = {
        "ema_stack_long", "ema_stack_short", "ema_stack_long_short",
        "lorentzian_advta", "kalman_cross","kalman_long","kalman_short"}
    strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
    if strat_key not in allowed:
        strat_key = "ema_stack_long"
        
        
    # def _on(name: str) -> bool:
    # # consider the checkbox ON if the key is present at all
    #     return name in request.GET
    
    # --- EMA toggles as a list (default OFF) ---
    ema_raw = request.GET.getlist("ema")  # e.g. ["20","50"]
    try:
        ema_spans = [s for s in (int(x) for x in ema_raw) if s in (20, 50, 100)]
    except ValueError:
        ema_spans = []

    # booleans for backwards-compatibility (used by context, if you still need them)
    ema20  = 20 in ema_spans
    ema50  = 50 in ema_spans
    ema100 = 100 in ema_spans
    ema_spans = [s for s, ok in ((20, ema20), (50, ema50), (100, ema100)) if ok]
    regdn = request.GET.get("regdn") in {"1","true","on","yes"} or ("regdn" in request.GET)


    trades_df, strat_title = build_trades_for_strategy(view, strat_key, fee)

    # figures (unchanged)
    fig_c = make_candle_fig(view, symbol_key, window, tf, ema_spans=ema_spans, show_regdn=regdn, reg_scope="any_bar")
    fig_p = make_equity_fig(view, trades_df, symbol_key, strat_title, tf)

    # overlay markers for LC only (unchanged)
    if strat_key == "lorentzian_advta":
        add_markers_to_candle(fig_c, view, trades_df)

    # table + js (unchanged)
    table_html = trades_table_html(trades_df)
    js_interactions = trades_table_js(BAR_MS_MAP[tf], pre_bars=36)

    # jsonify figs (unchanged)
    fig_c_json = fig_c.to_json()
    fig_p_json = fig_p.to_json()

    # jupyter link (unchanged)
    start_val = window.start_period.strftime("%Y-%m")
    end_val   = window.end_period.strftime("%Y-%m")
    nb_base = request.build_absolute_uri(reverse("analysis_to_jupyter", args=[symbol_key]))
    jupyter_url = f"{nb_base}?start={start_val}&end={end_val}&tf={tf}&strat={strat_key}&fee={fee:.6f}"

    # dropdown selections (unchanged)
    sel_long  = "selected" if strat_key == "ema_stack_long" else ""
    sel_short = "selected" if strat_key == "ema_stack_short" else ""
    sel_both  = "selected" if strat_key == "ema_stack_long_short" else ""
    sel_lc    = "selected" if strat_key == "lorentzian_advta" else ""
    sel_kcross  = "selected" if strat_key == "kalman_cross"  else ""
    sel_klong  = "selected" if strat_key == "kalman_long"  else ""
    sel_kshort = "selected" if strat_key == "kalman_short" else ""

    context = {
    "symbol_key": symbol_key,
    "window": window,
    "tf": tf,
    "strat_title": strat_title,

    # IMPORTANT: these are JSON STRINGS; your template will JSON.parse them
    "fig_c_json": fig_c.to_json(),
    "fig_p_json": fig_p.to_json(),

    # HTML/JS strings for the table & interactions
    "table_html": table_html,                      # you already computed this above
    "js_interactions": js_interactions,            # same

    # toolbar/jupyter bits
    "jupyter_url": jupyter_url,
    "start_val": start_val,
    "end_val": end_val,

    # select states
    "sel_long":   sel_long,
    "sel_short":  sel_short,
    "sel_both":   sel_both,
    "sel_lc":     sel_lc,
    "sel_kcross": sel_kcross,
    "sel_klong":  sel_klong,
    "sel_kshort": sel_kshort,
    
    "ema20": ema20,
    "ema50": ema50,
    "ema100": ema100,
    "ema_checked": set(ema_spans),
}

    return render(request, "chart_and_table.html", context)


# add at top with imports
import nbformat as nbf
import io

# def _safe_to_csv(df: pd.DataFrame) -> str:
#     if df is None or df.empty:
#         return "EMPTY\n"
#     # keep timestamps readable
#     out = df.copy()
#     for c in ("ts", "entry_ts", "exit_ts"):
#         if c in out.columns:
#             out[c] = pd.to_datetime(out[c])
#     return out.to_csv(index=False)

from string import Template

# def analysis_notebook(request):
#     """
#     Pyodide notebook with '+ Add cell' and 'Run all' buttons.
#     """
#     html = Template(r"""<!doctype html>
# <html lang="en">
# <head>
#   <meta charset="utf-8" />
#   <title>$title</title>
#   <meta name="viewport" content="width=device-width,initial-scale=1" />
#   <style>
#     :root { color-scheme: dark; }
#     body { margin:0; background:#0b0b0c; color:#e6e6e6; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }
#     header { position:sticky; top:0; z-index:10; background:#0b0b0c; border-bottom:1px solid #222; padding:10px 14px; display:flex; gap:10px; align-items:center; }
#     h1 { margin:0; font-size:16px; color:#9bd; font-weight:600; }
#     .pill { font-size:12px; padding:2px 8px; border:1px solid #333; border-radius:999px; }
#     #status { font-size:12px; opacity:0.9; }
#     main { max-width: 1000px; margin: 0 auto; padding: 14px; }
#     button { background:#1e1f24; color:#e6e6e6; border:1px solid #35363a; border-radius:8px; padding:8px 12px; cursor:pointer; }
#     button:hover { background:#23252b; }
#     .toolbar { display:flex; gap:8px; align-items:center; margin: 8px 0 12px; }
#     .cell { border:1px solid #2b2c30; padding:10px; border-radius:10px; margin:12px 0; background:#0f1013; }
#     .cell textarea.code { width:100%; height:160px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size:13px; line-height:1.4; color:#e6e6e6; background:#0b0b0c; border:1px solid #2b2c30; border-radius:8px; padding:10px; box-sizing:border-box; }
#     .cell .actions { margin-top:8px; display:flex; gap:8px; align-items:center; }
#     .cell pre.output { background:#0b0b0c; border:1px solid #2b2c30; border-radius:8px; padding:10px; white-space:pre-wrap; min-height:22px; margin-top:10px; }
#   </style>
# </head>
# <body>
#   <header>
#     <h1>$title</h1>
#     <span class="pill">Pyodide Notebook</span>
#     <span id="status" class="pill">Loading Python…</span>
#     <span style="margin-left:auto;font-size:12px;color:#9aa">⌘/Ctrl+Enter to run cell</span>
#   </header>

#   <main>
#     <div class="toolbar">
#       <button id="add-cell-btn">+ Add cell</button>
#       <button id="run-all-btn">Run all</button>
#     </div>
#     <div id="cells"></div>
#   </main>

#   <!-- Pyodide loader -->
#   <script>
#     (function ensurePyodide(){
#       if (!window._pyodideScript) {
#         const s = document.createElement('script');
#         s.src = "https://cdn.jsdelivr.net/pyodide/v0.24.1/full/pyodide.js";
#         s.defer = true;
#         window._pyodideScript = s;
#         document.head.appendChild(s);
#       }
#     })();
#   </script>

#   <script>
#     // Load Pyodide and set status
#     window.pyReady = (async () => {
#       while (typeof loadPyodide === "undefined") { await new Promise(r=>setTimeout(r, 50)); }
#       const pyodide = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.24.1/full/" });
#       window.pyodide = pyodide;
#       document.getElementById('status').textContent = "Python ready";
#       return pyodide;
#     })();

#     // Build a code cell
#     function buildCell(initialCode=""):
#       HTMLElement {
#       const wrap = document.createElement('div'); wrap.className = 'cell';
#       const ta = document.createElement('textarea'); ta.className = 'code'; ta.value = initialCode;
#       const actions = document.createElement('div'); actions.className = 'actions';
#       const runBtn = document.createElement('button'); runBtn.textContent = 'Run';
#       const clearBtn = document.createElement('button'); clearBtn.textContent = 'Clear output';
#       const delBtn = document.createElement('button'); delBtn.textContent = 'Delete cell';
#       const out = document.createElement('pre'); out.className = 'output';

#       async function run(){
#         const status = document.getElementById('status');
#         try {
#           status.textContent = 'Running…';
#           await window.pyReady;
#           const code = ta.value;
#           const hook = `
# import sys, io
# _sys_stdout = sys.stdout
# _buf = io.StringIO()
# sys.stdout = _buf
# __VAL__ = None
# try:
# ${code.split('\\n').map(l=>'    '+l).join('\\n')}
# finally:
#     sys.stdout = _sys_stdout
#     __OUT__ = _buf.getvalue()
# `;
#           await window.pyodide.runPythonAsync(hook);
#           const pyOut = window.pyodide.globals.get("__OUT__");
#           const pyVal = window.pyodide.globals.has("__VAL__") and window.pyodide.globals.get("__VAL__");
#           out.textContent = (pyOut || "") + (pyVal ? String(pyVal) : "");
#           if (window.pyodide.globals.has("__OUT__")) window.pyodide.runPython('del __OUT__');
#           if (window.pyodide.globals.has("__VAL__")) window.pyodide.runPython('del __VAL__');
#         } catch (e) {
#           out.textContent = String(e);
#         } finally {
#           status.textContent = 'Python ready';
#         }
#       }

#       runBtn.onclick = run;
#       clearBtn.onclick = () => { out.textContent = ""; };
#       delBtn.onclick = () => { wrap.remove(); };
#       ta.addEventListener('keydown', (ev) => {
#         if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { ev.preventDefault(); run(); }
#       });

#       actions.append(runBtn, clearBtn, delBtn);
#       wrap.append(ta, actions, out);
#       return wrap;
#     }

#     function addCell(initialCode=""){
#       const host = document.getElementById('cells');
#       host.appendChild(buildCell(initialCode));
#     }

#     async function runAll(){
#       const cells = Array.from(document.querySelectorAll('.cell'));
#       for (const c of cells){
#         const btn = c.querySelector('.actions button'); // first is Run
#         if (btn){ btn.click(); await new Promise(r=>setTimeout(r, 10)); }
#       }
#     }

#     document.addEventListener('DOMContentLoaded', () => {
#       document.getElementById('add-cell-btn').addEventListener('click', () => addCell());
#       document.getElementById('run-all-btn').addEventListener('click', runAll);
#       addCell(""); // initial empty cell
#     });
#   </script>
# </body>
# </html>
# """).substitute(title="Analysis Notebook")
#     return HttpResponse(html, content_type="text/html")



from django.http import HttpResponse, HttpResponseBadRequest
from string import Template
from html import escape

def analysis_inspect(request, symbol_key: str):
    # --- query params ---
    try:
        fee = float(request.GET.get("fee", str(FEE_DEFAULT)))
    except Exception:
        fee = FEE_DEFAULT

    tf = (request.GET.get("tf") or "5m").lower()
    tf = tf if tf in {"5m","1h","4h","1d"} else "5m"

    strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
    if strat_key not in {"ema_stack_long"}:
        strat_key = "ema_stack_long"

    symbol_key = (symbol_key or "").upper()
    if symbol_key not in SYMBOL_MAP:
        return HttpResponseBadRequest("Unsupported symbol")

    csv_path = _csv_path(symbol_key)
    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")

    df_full = _load_basic_df(csv_path)
    if df_full.empty:
        return HttpResponseBadRequest("No data in CSV.")

    # --- month range (default last 6 months) ---
    ts_max = pd.to_datetime(df_full["ts"].max())
    start_month_str = request.GET.get("start")
    end_month_str   = request.GET.get("end")

    if not end_month_str:
        end_period = ts_max.to_period("M"); start_period = (end_period - 5)
    else:
        try: end_period = pd.Period(end_month_str, freq="M")
        except Exception: end_period = ts_max.to_period("M")
    if not start_month_str:
        start_period = (end_period - 5)
    else:
        try: start_period = pd.Period(start_month_str, freq="M")
        except Exception: start_period = (end_period - 5)
    if start_period > end_period:
        start_period, end_period = end_period, start_period

    # --- resample to TF (ALWAYS via resample_ohlc to ensure EMA columns exist) ---
    rule_map = {"5m": None, "1h": "1H", "4h": "4H", "1d": "1D"}
    view_all = resample_ohlc(df_full, rule_map[tf])

    # --- window filter ---
    mask = (view_all["ts"].dt.to_period("M") >= start_period) & (view_all["ts"].dt.to_period("M") <= end_period)
    view = view_all.loc[mask].reset_index(drop=True)
    if view.empty:
        return HttpResponseBadRequest("No data in selected window.")

    # --- build trades (keyword-only args in your code) ---
    trades = build_trades(view, mode=strat_key, fee=fee)

    # --- normalize trades -> DataFrame ---
    EMPTY_COLS = ["side","entry_i","exit_i","entry_ts","exit_ts","entry_px","exit_px","ret_frac","pnl_frac"]
    if trades is None:
        trades_df = pd.DataFrame(columns=EMPTY_COLS)
    elif isinstance(trades, pd.DataFrame):
        trades_df = trades.copy()
        for c in EMPTY_COLS:
            if c not in trades_df.columns:
                trades_df[c] = pd.Series(dtype="float64")
    elif isinstance(trades, (list, tuple)):
        trades_df = pd.DataFrame(trades)
        if trades_df.empty:
            trades_df = pd.DataFrame(columns=EMPTY_COLS)
        else:
            for c in EMPTY_COLS:
                if c not in trades_df.columns:
                    trades_df[c] = pd.Series(dtype="float64")
    else:
        try:
            trades_df = pd.DataFrame(trades)
            if trades_df.empty:
                trades_df = pd.DataFrame(columns=EMPTY_COLS)
        except Exception:
            trades_df = pd.DataFrame(columns=EMPTY_COLS)

    # --- CSV strings for Pyodide side ---
    price_csv = view.to_csv(index=False)
    trades_csv = trades_df.to_csv(index=False)

    # --- HTML (inline onclick + global addCell) ---
    html = Template(r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>$page_title</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
  <script src="https://cdn.jsdelivr.net/pyodide/v0.24.1/full/pyodide.js"></script>
  <style>
    :root { color-scheme: dark; }
    body{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#0b1020;color:#e5e7eb}
    header{padding:12px 16px;border-bottom:1px solid #1f2937;display:flex;gap:10px;align-items:center}
    .meta{opacity:.85}
    .wrap{max-width:1200px;margin:0 auto;padding:16px}
    .btn{display:inline-block;padding:8px 12px;border:1px solid #374151;border-radius:8px;background:#111827;color:#e5e7eb;cursor:pointer;text-decoration:none}
    .btn:hover{background:#0b132a}
    .pill{display:inline-block;background:#111827;border:1px solid #374151;border-radius:999px;padding:2px 8px;margin-right:6px;font-size:12px}
    .toolbar{display:flex;gap:8px;align-items:center;margin:12px 0}
    .cell{border:1px solid #374151;background:#0f172a;border-radius:10px;padding:10px;margin:12px 0}
    .cell textarea{width:100%;height:160px;box-sizing:border-box;background:#0b1020;color:#e5e7eb;border:1px solid #374151;border-radius:8px;padding:10px;font-family:ui-monospace,Consolas,Menlo,monospace;font-size:13px;line-height:1.4}
    .cell .actions{margin-top:8px;display:flex;gap:8px;align-items:center}
    .cell .output{white-space:pre-wrap;background:#0b1020;border:1px solid #374151;border-radius:8px;padding:10px;margin-top:10px;min-height:22px}
    #log{white-space:pre-wrap;background:#0b1020;border:1px dashed #374151;border-radius:8px;padding:10px;margin-top:10px;min-height:22px}
  </style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:10px">
    <span class="pill">$symbol</span>
    <span class="pill">TF: $tf</span>
    <span class="pill">Strat: $strat_key</span>
    <span class="pill">Fee: $fee_per_fill / fill</span>
    <span id="status" class="pill">Loading Python…</span>
  </div>
  <div class="meta" style="margin-left:auto">Window: $start_period → $end_period</div>
</header>

<div class="wrap">
  <h2 style="margin:0 0 10px 0;">In-browser Python (Pyodide)</h2>
  <p>Preloaded: <b>df_price</b> and <b>df_trades</b>. Add cells, write Python, and run.</p>

  <div class="toolbar">
    <button class="btn" id="add-cell" onclick="window.addCell('')">+ Add cell</button>
    <button class="btn" id="run-all" onclick="window.runAll()">Run all</button>
  </div>

  <div id="cells"></div>

  <h3 style="margin-top:20px">Session log</h3>
  <div id="log"></div>
</div>

<script>
(function(){
  // --- logging helper
  function log(msg){
    var el = document.getElementById('log');
    if (!el) return;
    el.textContent += (el.textContent ? "\n" : "") + msg;
    el.scrollTop = el.scrollHeight;
  }

  // --- build a single code cell
  function buildCell(initialCode){
    var wrap = document.createElement('div'); wrap.className = 'cell';
    var ta = document.createElement('textarea'); ta.value = initialCode || "";
    var actions = document.createElement('div'); actions.className = 'actions';
    var runBtn = document.createElement('button'); runBtn.className='btn'; runBtn.textContent = 'Run';
    var clrBtn = document.createElement('button'); clrBtn.className='btn'; clrBtn.textContent = 'Clear output';
    var delBtn = document.createElement('button'); delBtn.className='btn'; delBtn.textContent = 'Delete cell';
    var out = document.createElement('div'); out.className='output';

    async function run(){
      var status = document.getElementById('status');
      try{
        status.textContent = "Running…";
        if (!window.pyodide){ out.textContent = "Python not ready yet"; return; }
        var code = ta.value;
        // indent lines (avoid ${} templates!)
        var lines = code.split('\n'); for (var i=0;i<lines.length;i++){ lines[i] = '    ' + lines[i]; }
        var hook =
"import sys, io\n"
+"_sys_stdout = sys.stdout\n"
+"_buf = io.StringIO()\n"
+"sys.stdout = _buf\n"
+"__VAL__ = None\n"
+"try:\n"
+ lines.join('\n') + "\n"
+"finally:\n"
+"    sys.stdout = _sys_stdout\n"
+"    __OUT__ = _buf.getvalue()\n";

        await window.pyodide.runPythonAsync(hook);
        var pyOut = window.pyodide.globals.get("__OUT__");
        var valExists = window.pyodide.globals.has("__VAL__");
        var val = valExists ? window.pyodide.globals.get("__VAL__") : null;
        out.textContent = (pyOut || "") + (val != null ? String(val) : "");
        if (window.pyodide.globals.has("__OUT__")) window.pyodide.runPython('del __OUT__');
        if (valExists) window.pyodide.runPython('del __VAL__');
      }catch(e){
        out.textContent = String(e);
      }finally{
        status.textContent = "Python ready";
      }
    }

    ta.addEventListener('keydown', function(ev){
      if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter'){ ev.preventDefault(); run(); }
    });
    runBtn.onclick = run;
    clrBtn.onclick = function(){ out.textContent = ""; };
    delBtn.onclick = function(){ wrap.remove(); };

    actions.append(runBtn, clrBtn, delBtn);
    wrap.append(ta, actions, out);
    return wrap;
  }

  // --- expose globals used by inline onclick
  window.addCell = function(initialCode){
    var host = document.getElementById('cells');
    if (!host){ log("cells container missing"); return; }
    var cell = buildCell(initialCode || "");
    host.appendChild(cell);
    return cell;
  };

  window.runAll = async function(){
    var cells = Array.from(document.querySelectorAll('.cell'));
    for (var i=0; i<cells.length; i++){
      var btn = cells[i].querySelector('.actions .btn'); // first is Run
      if (btn){ btn.click(); await new Promise(r=>setTimeout(r, 10)); }
    }
  };

  // --- load Pyodide, then seed initial data and add first cell
  (async function boot(){
    var status = document.getElementById('status');
    try{
      while (typeof loadPyodide === "undefined"){ await new Promise(r=>setTimeout(r,50)); }
      var pyodide = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.24.1/full/" });
      window.pyodide = pyodide;
      status.textContent = "Loading data…";

      pyodide.globals.set("PRICE_CSV", "$price_json");
      pyodide.globals.set("TRADES_CSV", "$trades_json");
      await pyodide.runPythonAsync(
"from io import StringIO\n"
"import pandas as pd\n"
"df_price  = pd.read_csv(StringIO(PRICE_CSV), parse_dates=['ts'])\n"
"try:\n"
"    df_trades = pd.read_csv(StringIO(TRADES_CSV), parse_dates=['entry_ts','exit_ts'])\n"
"except Exception:\n"
"    df_trades = pd.read_csv(StringIO(TRADES_CSV))\n"
      );
      log("Python ready. df_price rows=" + await window.pyodide.runPythonAsync("len(df_price)") + ", df_trades rows=" + await window.pyodide.runPythonAsync("len(df_trades)"));

      // create one initial cell immediately (no event dependency)
      window.addCell(
"# Preview heads\n"
"print(df_price.head().to_string())\n"
"print(df_trades.head().to_string())\n"
      );
      status.textContent = "Python ready";
    }catch(e){
      log("Boot error: " + String(e));
      status.textContent = "Boot failed";
    }
  })();
})();
</script>
</body>
</html>
""").safe_substitute(
        page_title=f"{symbol_key} — Interactive Inspect",
        symbol=escape(symbol_key),
        tf=tf,
        strat_key=strat_key,
        fee_per_fill=f"{fee:.4f}",
        start_period=str(start_period),
        end_period=str(end_period),
        price_json=price_csv.replace("\\", "\\\\").replace("`", "\\`"),
        trades_json=trades_csv.replace("\\", "\\\\").replace("`", "\\`"),
    )

    return HttpResponse(html)







# ─────────────────────────────────────────────────────────────────────────────
# ADD IMPORTS (near the top of views_analysis.py if not present yet)
# ─────────────────────────────────────────────────────────────────────────────
import os, json, time, subprocess, tempfile
from pathlib import Path
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from html import escape

# Assumes you already have:
#   - pd (pandas), SYMBOL_MAP, FEE_DEFAULT, _csv_path, _load_basic_df, resample_ohlc, build_trades


# ─────────────────────────────────────────────────────────────────────────────
# Helper: write a minimal notebook that preloads df_price/df_trades from CSVs
# ─────────────────────────────────────────────────────────────────────────────
def _write_inspect_notebook(nb_path: Path, price_csv_path: Path, trades_csv_path: Path):
    """Create a .ipynb that loads df_price/df_trades from given CSVs."""
    # Keep sources as a list of lines (nbformat style)
    src1 = [
        "import pandas as pd\n",
        "import numpy as np\n",
        "import matplotlib.pyplot as plt\n",
        f"PRICE_CSV  = r'''{price_csv_path}'''\n",
        f"TRADES_CSV = r'''{trades_csv_path}'''\n",
        "df_price  = pd.read_csv(PRICE_CSV, parse_dates=['ts'])\n",
        "try:\n",
        "    df_trades = pd.read_csv(TRADES_CSV, parse_dates=['entry_ts','exit_ts'])\n",
        "except Exception:\n",
        "    df_trades = pd.read_csv(TRADES_CSV)\n",
        "print('df_price rows:', len(df_price))\n",
        "print('df_trades rows:', len(df_trades))\n",
        "display(df_price.head())\n",
        "display(df_trades.head())\n",
    ]
    src2 = [
        "# Quick equity preview if pnl_frac exists\n",
        "if 'pnl_frac' in df_trades.columns:\n",
        "    eq = (1.0 + df_trades['pnl_frac']).cumprod()\n",
        "    eq.plot(title='Trade Equity (cumulative)')\n",
        "    plt.show()\n",
    ]
    nb = {
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": src1, "outputs": [], "execution_count": None},
            {"cell_type": "code", "metadata": {}, "source": src2, "outputs": [], "execution_count": None},
        ],
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    nb_path.write_text(json.dumps(nb, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: route to Jupyter with preloaded DataFrames
# URL idea: path("api/analysis/jupyter/<str:symbol_key>/", views.analysis_to_jupyter)
# ─────────────────────────────────────────────────────────────────────────────
# def analysis_to_jupyter(request, symbol_key: str):
#     """
#     Prepare df_price/df_trades, write temp CSVs + .ipynb, start Jupyter (Lab if available,
#     else Classic), wait for server, then redirect to the notebook. On failure, show log.
#     """
#     # --- params ---
#     try:
#         fee = float(request.GET.get("fee", str(FEE_DEFAULT)))
#     except Exception:
#         fee = FEE_DEFAULT

#     tf = (request.GET.get("tf") or "5m").lower()
#     tf = tf if tf in {"5m", "1h", "4h", "1d"} else "5m"

#     strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
#     if strat_key not in {"ema_stack_long", "ema_stack_short", "ema_stack_long_short"}:
#         strat_key = "ema_stack_long"

#     symbol_key = (symbol_key or "").upper()
#     if symbol_key not in SYMBOL_MAP:
#         return HttpResponseBadRequest("Unsupported symbol")
    

#     if not csv_path.exists():
#         return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")


#     csv_path = _csv_path(symbol_key)
#     if not csv_path.exists():
#         return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")

#     df_full = _load_basic_df(csv_path)
#     if df_full.empty:
#         return HttpResponseBadRequest("No data in CSV.")

#     # --- month window (default last 6 months) ---
#     ts_max = pd.to_datetime(df_full["ts"].max())
#     start_month_str = request.GET.get("start")
#     end_month_str   = request.GET.get("end")

#     if not end_month_str:
#         end_period = ts_max.to_period("M"); start_period = (end_period - 5)
#     else:
#         try: end_period = pd.Period(end_month_str, freq="M")
#         except Exception: end_period = ts_max.to_period("M")
#     if not start_month_str:
#         start_period = (end_period - 5)
#     else:
#         try: start_period = pd.Period(start_month_str, freq="M")
#         except Exception: start_period = end_period - 5
#     if start_period > end_period:
#         start_period, end_period = end_period, start_period

#     # --- resample + window (ALWAYS via resample_ohlc so EMA columns exist) ---
#     rule_map = {"5m": None, "1h": "1H", "4h": "4H", "1d": "1D"}
#     view_all = resample_ohlc(df_full, rule_map[tf])

#     mask = (view_all["ts"].dt.to_period("M") >= start_period) & (view_all["ts"].dt.to_period("M") <= end_period)
#     view = view_all.loc[mask].reset_index(drop=True)
#     if view.empty:
#         return HttpResponseBadRequest("No data in selected window.")

#     # --- build trades ---
#     if strat_key == "ema_stack_long":
#         trades = build_trades(view, mode="long", fee=fee)
#     elif strat_key == "ema_stack_short":
#         trades = build_trades(view, mode="short", fee=fee)
#     else:
#         trades = build_trades(view, mode="both", fee=fee)

#     cols = ["side","entry_i","exit_i","entry_ts","exit_ts","entry_px","exit_px","ret_frac","pnl_frac"]
#     trades_df = trades.copy() if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
#     for c in cols:
#         if c not in trades_df.columns:
#             trades_df[c] = pd.Series(dtype="float64")

#     # --- write temp files ---
#     tmp_dir = Path(tempfile.mkdtemp(prefix="inspect_nb_"))
#     price_csv_path  = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}_price.csv"
#     trades_csv_path = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}_trades.csv"
#     nb_path         = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}.ipynb"

#     view.to_csv(price_csv_path, index=False)
#     trades_df.to_csv(trades_csv_path, index=False)
#     _write_inspect_notebook(nb_path, price_csv_path, trades_csv_path)

#     # --- pick server (Lab preferred) or fail early if neither installed ---
#     have_lab = _module_available("jupyterlab")
#     have_nb  = _module_available("notebook")
#     if not have_lab and not have_nb:
#         return HttpResponseBadRequest(
#             "Neither JupyterLab nor Classic Notebook is installed in this virtualenv.\n\n"
#             "Install one of the following and retry:\n"
#             "  pip install jupyterlab\n"
#             "  # or\n"
#             "  pip install notebook\n"
#         )

#     host = os.environ.get("JUPYTER_HOST", "127.0.0.1")
#     port = _pick_free_port(host)
#     log_path = tmp_dir / "jupyter_server.log"
#     log_fh = open(log_path, "ab", buffering=0)

#     if have_lab:
#         cmd = [
#             sys.executable, "-m", "jupyterlab",
#             f"--ServerApp.root_dir={str(tmp_dir)}",
#             "--ServerApp.token=",
#             "--ServerApp.password=",
#             "--no-browser",
#             f"--port={port}",
#             f"--ip={host}",
#         ]
#         final_url = f"http://{host}:{port}/lab/tree/{quote(nb_path.name)}"
#     else:
#         cmd = [
#             sys.executable, "-m", "notebook",
#             f"--notebook-dir={str(tmp_dir)}",
#             "--NotebookApp.token=",
#             "--NotebookApp.password=",
#             "--no-browser",
#             f"--port={port}",
#             f"--ip={host}",
#         ]
#         final_url = f"http://{host}:{port}/notebooks/{quote(nb_path.name)}"

#     # --- spawn & wait ---
#     try:
#         subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, cwd=str(tmp_dir))
#     except Exception as e:
#         log_fh.close()
#         return HttpResponseBadRequest(
#             f"Failed to start Jupyter ({'Lab' if have_lab else 'Notebook'}): {e}\n"
#             f"Command: {' '.join(cmd)}\n"
#         )

#     if not _wait_for_port(host, port, timeout=15.0):
#         log_fh.close()
#         log_txt = _read_log(str(log_path))
#         return HttpResponseBadRequest(
#             "Jupyter server did not start in time (connection refused).\n\n"
#             f"Command: {' '.join(cmd)}\n"
#             f"Log file: {log_path}\n\n"
#             f"--- LOG TAIL ---\n{log_txt}"
#         )

#     log_fh.close()
#     return HttpResponseRedirect(final_url)

def analysis_to_jupyter(request, symbol_key: str):
    """
    Prepare df_price/df_trades, write temp CSVs + .ipynb, start Jupyter (Lab if available,
    else Classic), wait for server, then redirect to the notebook. On failure, show log.
    """

    # --- params ---
    try:
        fee = float(request.GET.get("fee", str(FEE_DEFAULT)))
    except Exception:
        fee = FEE_DEFAULT

    tf = (request.GET.get("tf") or "5m").lower()
    tf = tf if tf in {"5m", "1h", "4h", "1d"} else "5m"

    strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
    if strat_key not in {"ema_stack_long", "ema_stack_short", "ema_stack_long_short"}:
        strat_key = "ema_stack_long"

    symbol_key = (symbol_key or "").upper()
    if symbol_key in SYMBOL_MAP:
        csv_path = _csv_path(symbol_key)           # crypto CSV (e.g., btcusd_5m_coinbase.csv)
        display = f"{symbol_key}/USD"
    else:
        p = _find_csv_for_symbol(symbol_key, asset="stock")  # data/stocks/HistoricalData_<SYM>.csv
        if p is None:
            return HttpResponseBadRequest("Unsupported symbol")
        csv_path = p
        display = symbol_key
    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")


    # --- load raw dataframe ---
    df_full = _load_basic_df(csv_path)
    if df_full.empty:
        return HttpResponseBadRequest("No data in CSV.")

    # --- month window (default to last 6 months) ---
    ts_max = pd.to_datetime(df_full["ts"].max())
    start_month_str = request.GET.get("start")
    end_month_str   = request.GET.get("end")

    if not end_month_str:
        end_period = ts_max.to_period("M"); start_period = (end_period - 5)
    else:
        try:
            end_period = pd.Period(end_month_str, freq="M")
        except Exception:
            end_period = ts_max.to_period("M")

    if not start_month_str:
        start_period = (end_period - 5)
    else:
        try:
            start_period = pd.Period(start_month_str, freq="M")
        except Exception:
            start_period = end_period - 5

    if start_period > end_period:
        start_period, end_period = end_period, start_period

    # --- resample + window (ALWAYS via resample_ohlc so EMA columns exist) ---
    rule_map = {"5m": None, "1h": "1H", "4h": "4H", "1d": "1D"}
    view_all = resample_ohlc(df_full, rule_map[tf])

    mask = (view_all["ts"].dt.to_period("M") >= start_period) & (view_all["ts"].dt.to_period("M") <= end_period)
    view = view_all.loc[mask].reset_index(drop=True)
    if view.empty:
        return HttpResponseBadRequest("No data in selected window.")

    # --- build trades (EMA strategies only, matching original intent) ---
    if strat_key == "ema_stack_long":
        trades = build_trades(view, mode="long", fee=fee)
    elif strat_key == "ema_stack_short":
        trades = build_trades(view, mode="short", fee=fee)
    else:
        trades = build_trades(view, mode="both", fee=fee)

    cols = ["side","entry_i","exit_i","entry_ts","exit_ts","entry_px","exit_px","ret_frac","pnl_frac"]
    trades_df = trades.copy() if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    for c in cols:
        if c not in trades_df.columns:
            # keep dtype stable; timestamps will be strings if missing
            trades_df[c] = pd.Series(dtype="float64")

    # --- write temp files ---
    tmp_dir = Path(tempfile.mkdtemp(prefix="inspect_nb_"))
    price_csv_path  = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}_price.csv"
    trades_csv_path = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}_trades.csv"
    nb_path         = tmp_dir / f"{symbol_key}_{tf}_{start_period}_{end_period}.ipynb"

    view.to_csv(price_csv_path, index=False)
    trades_df.to_csv(trades_csv_path, index=False)
    _write_inspect_notebook(nb_path, price_csv_path, trades_csv_path)

    # --- pick server (Lab preferred) or fail early if neither installed ---
    have_lab = _module_available("jupyterlab")
    have_nb  = _module_available("notebook")
    if not have_lab and not have_nb:
        return HttpResponseBadRequest(
            "Neither JupyterLab nor Classic Notebook is installed in this virtualenv.\n\n"
            "Install one of the following and retry:\n"
            "  pip install jupyterlab\n"
            "  # or\n"
            "  pip install notebook\n"
        )

    host = os.environ.get("JUPYTER_HOST", "127.0.0.1")
    port = _pick_free_port(host)
    log_path = tmp_dir / "jupyter_server.log"
    log_fh = open(log_path, "ab", buffering=0)

    if have_lab:
        cmd = [
            sys.executable, "-m", "jupyterlab",
            f"--ServerApp.root_dir={str(tmp_dir)}",
            "--ServerApp.token=",
            "--ServerApp.password=",
            "--no-browser",
            f"--port={port}",
            f"--ip={host}",
        ]
        final_url = f"http://{host}:{port}/lab/tree/{quote(nb_path.name)}"
    else:
        cmd = [
            sys.executable, "-m", "notebook",
            f"--notebook-dir={str(tmp_dir)}",
            "--NotebookApp.token=",
            "--NotebookApp.password=",
            "--no-browser",
            f"--port={port}",
            f"--ip={host}",
        ]
        final_url = f"http://{host}:{port}/notebooks/{quote(nb_path.name)}"

    # --- spawn & wait ---
    try:
        subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, cwd=str(tmp_dir))
    except Exception as e:
        log_fh.close()
        return HttpResponseBadRequest(
            f"Failed to start Jupyter ({'Lab' if have_lab else 'Notebook'}): {e}\n"
            f"Command: {' '.join(cmd)}\n"
        )

    if not _wait_for_port(host, port, timeout=15.0):
        log_fh.close()
        log_txt = _read_log(str(log_path))
        return HttpResponseBadRequest(
            "Jupyter server did not start in time (connection refused).\n\n"
            f"Command: {' '.join(cmd)}\n"
            f"Log file: {log_path}\n\n"
            f"--- LOG TAIL ---\n{log_txt}"
        )

    log_fh.close()
    return HttpResponseRedirect(final_url)


def _find_csv_for_symbol(symbol: str, asset: str | None = None) -> Path | None:
    """
    Tolerant CSV discovery.
    - Crypto default: match like 'btcusd_5m_coinbase.csv', 'solusd_5m_coinbase.csv'
    - Stocks default: any '<sym>*csv' (we pick the most recently modified)
    You can tighten this pattern later if you standardize filenames.
    """
    sym = symbol.lower()
    candidates: list[Path] = []

    # Prefer explicit crypto naming if present
    crypto_names = [f"{sym}usd_5m_coinbase.csv", f"{sym}usd_1h_coinbase.csv"]
    for name in crypto_names:
        p = DATA_DIR / name
        if p.exists():
            candidates.append(p)

    # Fallback: any CSV that starts with the symbol (for stocks or custom feeds)
    # e.g., aapl_1h_yahoo.csv, nvda_daily.csv, msft.csv, etc.
    for p in DATA_DIR.glob(f"{sym}*.csv"):
        if p.is_file():
            candidates.append(p)

    if not candidates:
        return None

    # Pick the most recently modified as the best guess
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]

def _latest_ts_from_csv(path: Path) -> pd.Timestamp | None:
    """Read just enough to get latest timestamp (supports 'ts' or 'date'+'time')."""
    try:
        df = pd.read_csv(path, usecols=None, low_memory=False)
    except Exception:
        return None
    if "ts" in df.columns:
        ts = pd.to_datetime(df["ts"], errors="coerce")
        ts = ts.dropna()
        return None if ts.empty else ts.iloc[-1]
    # common crypto layout in your codebase: date, time
    if {"date", "time"} <= set(df.columns):
        ts = pd.to_datetime(df["date"] + " " + df["time"], errors="coerce")
        ts = ts.dropna()
        return None if ts.empty else ts.iloc[-1]
    # last-ditch: try any datetime-like column
    for c in df.columns:
        s = pd.to_datetime(df[c], errors="coerce")
        if s.notna().sum() > 0:
            return s.dropna().iloc[-1]
    return None

# backend/accounts/views_analysis.py  (or wherever the view lives)
from pathlib import Path
import pandas as pd
from django.http import JsonResponse
from django.utils import timezone

def analysis_check_csv(request, symbol: str):
    """
    GET /api/analysis/check_csv/<symbol>/?asset=crypto|stock&min_rows=500&fresh_hours=48
    Returns: { ok, exists, path, rows, latest_ts, fresh, reason }
    """
    asset = (request.GET.get("asset", "") or "").lower() or None
    min_rows = int(request.GET.get("min_rows", "100"))
    fresh_hours = int(request.GET.get("fresh_hours", "48"))

    path = _find_csv_for_symbol(symbol, asset=asset)  # your existing helper
    if path is None:
        return JsonResponse(
            {"ok": False, "exists": False, "reason": "No CSV found for symbol."},
            status=404,
        )

    path = Path(path)

    # ---- quick line count (header-aware) ------------------------------------
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            rows = sum(1 for _ in f) - 1  # minus header
        if rows < 0:
            rows = 0
    except Exception:
        rows = None

    # ---- latest timestamp (coerce to UTC-aware) -----------------------------
    latest_ts = _latest_ts_from_csv(path)  # may return str/naive/aware
    if latest_ts is not None:
        latest_ts = pd.Timestamp(latest_ts)
        if latest_ts.tzinfo is None or latest_ts.tz is None:
            latest_ts = latest_ts.tz_localize("UTC")
        else:
            latest_ts = latest_ts.tz_convert("UTC")

    # Use Django-aware 'now' (UTC) and convert to pandas Timestamp in UTC
    now_pd = pd.Timestamp(timezone.now()).tz_convert("UTC")

    fresh = (latest_ts is not None) and (
        (now_pd - latest_ts) <= pd.Timedelta(hours=fresh_hours)
    )

    latest_iso = None if latest_ts is None else latest_ts.isoformat()

    # ---- size check ---------------------------------------------------------
    if rows is None or rows < min_rows:
        return JsonResponse(
            {
                "ok": False,
                "exists": True,
                "path": str(path),
                "rows": rows,
                "latest_ts": latest_iso,
                "fresh": bool(fresh),
                "reason": f"CSV too small: need >= {min_rows} rows.",
            },
            status=409,
        )

    # ---- freshness check ----------------------------------------------------
    if not fresh:
        return JsonResponse(
            {
                "ok": False,
                "exists": True,
                "path": str(path),
                "rows": rows,
                "latest_ts": latest_iso,
                "fresh": False,
                "reason": f"CSV not fresh (>{fresh_hours}h old).",
            },
            status=409,
        )

    # ---- all good -----------------------------------------------------------
    return JsonResponse(
        {
            "ok": True,
            "exists": True,
            "path": str(path),
            "rows": rows,
            "latest_ts": latest_iso,
            "fresh": True,
        }
    )


def analysis_check_historical_csv(request, symbol: str):
    sym = (symbol or "").strip()
    p = _historical_csv_path(sym)
    if p is None:
        exists_dir = _HIST_DIR.exists()
        listing = []
        try:
            if exists_dir:
                # limit to 200 names to avoid huge payloads
                listing = sorted(os.listdir(_HIST_DIR))[:200]
        except Exception as e:
            listing = [f"<error reading dir: {e}>"]
        return JsonResponse(
            {
                "ok": False,
                "exists": False,
                "reason": f"No HistoricalData_{sym.upper()}.csv",
                "searched_dir": str(_HIST_DIR),
                "dir_exists": exists_dir,
                "dir_listing_sample": listing,
            },
            status=404,
        )

    # Found
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            rows = max(0, sum(1 for _ in f) - 1)
    except Exception:
        rows = None
    return JsonResponse(
        {"ok": True, "exists": True, "path": str(p), "rows": rows, "searched_dir": str(_HIST_DIR)}
    )


def analysis_historical(request, symbol_key: str):
    """
    Same output as /api/analysis/all/<symbol>/, but forces CSV from data/stocks/HistoricalData_<SYM>.csv
    """
    from django.http import HttpResponse, HttpResponseBadRequest
    from django.urls import reverse
    from .analysis_helpers import (
        FEE_DEFAULT, BAR_MS_MAP, compute_period_window, slice_and_resample,
        make_candle_fig, make_equity_fig, add_markers_to_candle,
        trades_table_html, trades_table_js, build_trades_for_strategy,
        render_all_like_page,  # <- your updated template helper
    )

    symbol_key = (symbol_key or "").upper()

    # 1) CSV (force backend/data/stocks/HistoricalData_<SYM>.csv)
    csv_path = _historical_csv_path(symbol_key)
    if not csv_path or not csv_path.exists():
        return HttpResponseBadRequest(f"HistoricalData_{symbol_key}.csv not found in data/stocks.")

    # 2) Load + validate
    df = _load_basic_df(csv_path)
    if df.empty or df["ts"].isna().all():
        return HttpResponseBadRequest("No data in CSV.")

    # 3) Params
    try:
        fee = float(request.GET.get("fee", str(FEE_DEFAULT)))
    except Exception:
        fee = float(FEE_DEFAULT)

    tf = (request.GET.get("tf") or "5m").lower()
    if tf not in {"5m", "1h", "4h", "1d"}:
        tf = "5m"

    # 4) Window + resample
    window = compute_period_window(df, request.GET.get("start"), request.GET.get("end"))
    view = slice_and_resample(df, window, tf)

    # 5) Strategy
    allowed = {"ema_stack_long","ema_stack_short","ema_stack_long_short",
               "lorentzian_advta","kalman_cross","kalman_long","kalman_short"}
    strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
    if strat_key not in allowed:
        strat_key = "ema_stack_long"

    trades_df, strat_title = build_trades_for_strategy(view, strat_key, fee)
    
    
    # --- EMA toggles from the form (default OFF) ---
    ema_raw = request.GET.getlist("ema")  # e.g. ["20","50"]
    try:
        ema_spans = [s for s in (int(x) for x in ema_raw) if s in (20, 50, 100)]
    except ValueError:
        ema_spans = []

    # booleans for backwards-compatibility (used by context, if you still need them)
    ema20  = 20 in ema_spans
    ema50  = 50 in ema_spans
    ema100 = 100 in ema_spans
    ema_spans = [s for s, ok in ((20, ema20), (50, ema50), (100, ema100)) if ok]
    regdn = request.GET.get("regdn") in {"1","true","on","yes"} or ("regdn" in request.GET)

    # 6) Figures (+ markers if LC)
    # fig_c = make_candle_fig(view, symbol_key, window, tf, ema_spans=ema_spans)
    fig_c = make_candle_fig(
        view, symbol_key, window, tf,
        ema_spans=ema_spans,
        show_regdn=regdn,          # ← add this
        reg_scope="any_bar",       # ← same scope you used in crypto
    )

    fig_p = make_equity_fig(view, trades_df, symbol_key, strat_title, tf)
    if strat_key == "lorentzian_advta":
        add_markers_to_candle(fig_c, view, trades_df)

    # 7) Table + interactions
    table_html = trades_table_html(trades_df)
    js_interactions = trades_table_js(BAR_MS_MAP[tf], pre_bars=36)

    start_val = window.start_period.strftime("%Y-%m")
    end_val   = window.end_period.strftime("%Y-%m")
    nb_base   = request.build_absolute_uri(reverse("analysis_to_jupyter", args=[symbol_key]))
    jupyter_url = f"{nb_base}?start={start_val}&end={end_val}&tf={tf}&strat={strat_key}&fee={fee:.6f}"

    sel_long   = "selected" if strat_key == "ema_stack_long"        else ""
    sel_short  = "selected" if strat_key == "ema_stack_short"       else ""
    sel_both   = "selected" if strat_key == "ema_stack_long_short"  else ""
    sel_lc     = "selected" if strat_key == "lorentzian_advta"      else ""
    sel_kcross = "selected" if strat_key == "kalman_cross"          else ""
    sel_klong  = "selected" if strat_key == "kalman_long"           else ""
    sel_kshort = "selected" if strat_key == "kalman_short"          else ""

    context = {
        "symbol_key": symbol_key,
        "window": window,
        "tf": tf,
        "strat_title": strat_title,
        # IMPORTANT: pass JSON strings; parse them in the template
        "fig_c_json": fig_c.to_json(),
        "fig_p_json": fig_p.to_json(),
        "table_html": table_html,
        "js_interactions": js_interactions,
        "jupyter_url": jupyter_url,
        "start_val": start_val,
        "end_val": end_val,
        "sel_long": sel_long,
        "sel_short": sel_short,
        "sel_both": sel_both,
        "sel_lc": sel_lc,
        "sel_kcross": sel_kcross,
        "sel_klong": sel_klong,
        "sel_kshort": sel_kshort,
        "ema20": ema20,
        "ema50": ema50,
        "ema100": ema100,
        "ema_checked": set(ema_spans),
        "regdn": regdn,
    }

    return render(request, "chart_and_table.html", context)


try:
    from .nasdaq import update_symbol
except ImportError:
    from accounts.nasdaq import update_symbol



@require_GET
def api_today_stocks(request: HttpRequest):
   """
   Minimal payload to satisfy the page’s initial fetch.
   You can swap this list for your real logic later.
   """
   items = [{"symbol": s} for s in ["AAPL","MSFT","NVDA","TSLA","AMZN","GOOGL","META","AMD","NFLX","AVGO"]]
   return JsonResponse({"ok": True, "total": len(items), "items": items})


@require_POST
def api_today_update(request: HttpRequest):
   sym = (request.POST.get("ticker") or "").upper().strip()
   if not sym.isalnum():
       return JsonResponse({"ok": False, "error": "Invalid ticker."}, status=400)
   try:
       data = update_symbol(sym)
       if not isinstance(data, dict):
           return JsonResponse({"ok": False, "error": "Unexpected response from updater."}, status=500)
       # If there are simply no new rows, keep it 200 so the UI shows “+0”
       status_code = 200 if data.get("ok") else 404 if "No rows" in str(data.get("error", "")) else 500
       return JsonResponse(data, status=status_code)
   except Exception as e:
       # optional: add logging here
       return JsonResponse({"ok": False, "error": str(e)}, status=500)


import logging


logger = logging.getLogger(__name__)

@require_GET
def api_today_csv_symbols(request):
    """
    Return all tickers that have a CSV on disk:
    HistoricalData_<TICKER>.csv
    We try multiple likely roots and pick the first that exists.
    """
    #print("DEBUG: api_today_csv_symbols called")

    
    try:
        here = Path(__file__).resolve()
        candidates = [
            # most accurate for your tree: backend/data/stocks
            here.parents[1] / "data" / "stocks",              # backend/data/stocks
            here.parents[2] / "data" / "stocks",              # lms/data/stocks (just in case)
        ]

        stocks_dir = next((p for p in candidates if p.exists()), None)

        if not stocks_dir:
            # Return an empty list rather than hanging
            logger.warning("api_today_csv_symbols: no stocks dir found in %s", candidates)
            return JsonResponse({"ok": True, "symbols": [], "count": 0, "path": None})

        symbols = []
        # Fast glob through HistoricalData_*.csv
        for p in stocks_dir.glob("HistoricalData_*.csv"):
            stem = p.stem  # e.g. HistoricalData_AAPL
            t = stem.replace("HistoricalData_", "", 1).strip().upper()
            if t and t.isalnum():
                symbols.append(t)

        symbols = sorted(set(symbols))
        return JsonResponse({"ok": True, "symbols": symbols, "count": len(symbols), "path": str(stocks_dir)})
    except Exception as e:
        logger.exception("api_today_csv_symbols failed")
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
    
    

# signal imports (as you described)
from accounts.strategies.signals import (
    isKalmanUptrend, isKalmanBuy, isKalmanSell,
    is_hh_hl, is_lh_ll, isLorentzianBuy, isLorentzianSell,
    is_broke_above_resis, is_broke_below_supp,
)
from accounts.strategies.sg import sg_indicators_bool

# signals
from accounts.strategies.signals import (
    isKalmanBuy,      # KB
    isLorentzianBuy,  # LB
    is_hh_hl,         # HH, HL
    is_broke_above_resis,  # BR
)
from accounts.strategies.sg import sg_indicators_bool  # SG_Long

# ---- helpers ---------------------------------------------------------------

def _stocks_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "data" / "stocks",  # backend/data/stocks
        here.parents[2] / "data" / "stocks",  # lms/data/stocks (fallback)
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def _load_symbol_df(sym: str) -> pd.DataFrame | None:
    base = _stocks_dir()
    if not base:
        return None
    f = base / f"HistoricalData_{sym}.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f)
    except Exception:
        return None

    # Normalize columns
    # Try common date columns: 'date', 'Date', 'ts'
    if "date" in df.columns:
        dt = pd.to_datetime(df["date"], errors="coerce")
    elif "Date" in df.columns:
        dt = pd.to_datetime(df["Date"], errors="coerce")
    elif "ts" in df.columns:
        dt = pd.to_datetime(df["ts"], errors="coerce")
    else:
        return None

    df = df.copy()
    df["__date"] = dt.dt.date  # pure date for grouping
    df = df.dropna(subset=["__date"])

    # If prices have leading $ strings from Nasdaq CSV, strip to float where useful
    for col in ["Open", "High", "Low", "Close", "Close/Last", "open", "high", "low", "close"]:
        if col in df.columns and df[col].dtype == object:
            df[col] = (
                df[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
                  .replace("", pd.NA).astype(float)
            )

    return df

def _compute_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Boolean columns for key signals:
      - BR (broke above resistance)
      - KB (Kalman Buy)
      - LB (Lorentzian Buy)
      - SG (SG_Long)
      - HH / HL (from is_hh_hl)
    Ensures proper timestamp and column naming, and applies a minimum signal requirement (>=2).
    """

    # --- Normalize column names ---
    df = df.rename(columns=str.lower)

    # --- Fix close column naming ---
    if "close/last" in df.columns and "close" not in df.columns:
        df["close"] = df["close/last"]
    if "adj close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj close"]

    # --- Ensure timestamp column exists ---
    if "ts" not in df.columns:
        if "date" in df.columns:
            df["ts"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        elif "time" in df.columns:
            df["ts"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
        else:
            raise ValueError("No timestamp column ('date', 'time', or 'ts') found in CSV")

    # --- Ensure volume column ---
    if "volume" not in df.columns:
        df["volume"] = 0.0

    # --- Compute signals ---
    BR = is_broke_above_resis(df)
    KB = isKalmanBuy(df)
    LB = isLorentzianBuy(df)
    SG = sg_indicators_bool(df).get("SG_Long")
    HH, HL = is_hh_hl(df)

    # --- Safety: make sure everything is boolean and sized to df ---
    def as_bool(x):
        s = pd.Series(x)
        if len(s) != len(df):
            s = s.reindex(range(len(df))).fillna(False)
        return s.astype(bool)

    BR = as_bool(BR)
    KB = as_bool(KB)
    LB = as_bool(LB)
    SG = as_bool(SG)
    HH = as_bool(HH)
    HL = as_bool(HL)

    # --- Build unified boolean table ---
    out = df.copy()
    out["BR"] = BR
    out["KB"] = KB
    out["LB"] = LB
    out["SG"] = SG
    out["HH"] = HH
    out["HL"] = HL

    # --- ✅ Apply the ">= 2 total signals" rule ---
    # Count all True signals per row (including hard + favorable)
    signal_cols = ["BR", "KB", "LB", "SG", "HL"]
    out["signal_count"] = out[signal_cols].sum(axis=1)

    # Hard requirement mask: BR + KB must be True
    out["meets_hard_requirements"] = out["BR"] & out["KB"]

    # Meets at least 2 signals (total) condition
    out["meets_min_signals"] = out["signal_count"] >= 2

    # Combined filter (for convenience): Hard + min signals
    out["meets_criteria"] = out["meets_hard_requirements"] & out["meets_min_signals"]

    return out


# ---- API -------------------------------------------------------------------

@csrf_exempt
@require_POST
def api_today_recommendations(request: HttpRequest):
    """
    POST JSON: { "symbols": ["AAPL","TSLA",...], "days": 60 }
    Returns:
      { ok: true, rows: [
          { date: "YYYY-MM-DD",
            buys:   ["AAPL","TSLA"],
            signals:["AAPL: BR, KB, SG", ...],
            other:  ["MSFT: SG", "NVDA: LB, HL"]
          }, ...
        ]}

    Requirements:
      ✅ Hard requirement: BR == True and KB == True (same row/date)
      ✅ Total signals (BR, KB, SG, LB, HL) ≥ 2
      ✅ "Other" includes any ticker that fails the hard requirement but has at least one favorable (SG/LB/HL)
    """
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    symbols = body.get("symbols") or []
    if not isinstance(symbols, list):
        return JsonResponse({"ok": False, "error": "symbols must be a list"}, status=400)

    days = int(body.get("days") or 60)
    days = max(1, min(days, 400))

    if not symbols:
        return JsonResponse({"ok": True, "rows": []})

    # --- Load and compute flags ---
    by_sym: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        s = (str(sym) or "").upper().strip()
        if not s:
            continue
        df = _load_symbol_df(s)
        if df is None or df.empty:
            continue
        by_sym[s] = _compute_flags(df)

    if not by_sym:
        return JsonResponse({"ok": True, "rows": []})

    # --- Build date set (newest first) ---
    all_dates = set()
    for df in by_sym.values():
        all_dates.update(df["__date"].unique().tolist())
    if not all_dates:
        return JsonResponse({"ok": True, "rows": []})

    dates_sorted = sorted(all_dates, reverse=True)[:days]
    rows: List[Dict[str, Any]] = []

    # --- Daily loop ---
    for d in dates_sorted:
        buys: List[str] = []
        signals_col: List[str] = []
        other_col: List[str] = []

        for sym, df in by_sym.items():
            day_df = df[df["__date"] == d]
            if day_df.empty:
                continue
            last = day_df.iloc[-1]

            br = bool(last.get("BR", False))
            kb = bool(last.get("KB", False))
            lb = bool(last.get("LB", False))
            sg = bool(last.get("SG", False))
            hl = bool(last.get("HL", False))

            # Count how many signals are True
            total_signals = sum([br, kb, lb, sg, hl])

            # ✅ Hard buy condition: BR & KB must both be True AND total ≥ 2
            if br and kb and total_signals >= 2:
                extra = []
                if sg: extra.append("SG")
                if lb: extra.append("LB")
                if hl: extra.append("HL")
                label_bits = ["BR", "KB"] + extra
                signals_col.append(f"{sym}: {', '.join(label_bits)}")
                buys.append(sym)
            else:
                # ✅ Favorable but not full buy
                fav = []
                if sg: fav.append("SG")
                if lb: fav.append("LB")
                if hl: fav.append("HL")
                if len(fav) >= 2:
                    other_col.append(f"{sym}: {', '.join(fav)}")

        rows.append({
            "date": pd.to_datetime(d).strftime("%Y-%m-%d"),
            "buys": buys,
            "signals": signals_col,
            "other": other_col,
        })

    return JsonResponse({"ok": True, "rows": rows})
