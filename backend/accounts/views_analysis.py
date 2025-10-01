# backend/accounts/views_analysis.py
from pathlib import Path
import json
import pandas as pd
import plotly.graph_objects as go
from django.http import HttpResponse, HttpResponseBadRequest 
from string import Template
from html import escape  # (you already use escape below; keep this too)
from django.urls import reverse
import os, sys, time, subprocess, tempfile, socket
from urllib.parse import quote
import importlib.util
from .analysis_helpers import add_markers_to_candle, build_trades_for_strategy



DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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

def _load_basic_df(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"asset": "string", "source": "string"}, low_memory=False)
    # timestamp (ET-naive)
    df["ts"] = pd.to_datetime(df["date"] + " " + df["time"], errors="coerce")
    # numeric
    for c in ("open","high","low","close","volume","ema20","ema50","ema100"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # clean
    df = df.dropna(subset=["ts","open","high","low","close"]).sort_values("ts").reset_index(drop=True)
    return df

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
  <a class="back" href="/investments">← Back to Investments</a>
  <div id="chart" style="max-width:1200px;"></div>
  <script>
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
    if symbol_key not in SYMBOL_MAP:
        return HttpResponseBadRequest("Unsupported symbol")

    csv_path = _csv_path(symbol_key)
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
        name=f"{symbol_key}/USD"
    ))

    # Optional EMAs if present
    for col, label in [("ema20","EMA20"), ("ema50","EMA50"), ("ema100","EMA100")]:
        if col in tail.columns and tail[col].notna().any():
            fig.add_trace(go.Scatter(x=tail["ts"], y=tail[col], mode="lines", name=label))

    fig.update_layout(
        title=f"{symbol_key}/USD — last {len(tail)} × 5m candles",
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
    if symbol_key not in SYMBOL_MAP:
        return HttpResponseBadRequest("Unsupported symbol")

    csv_path = _csv_path(symbol_key)
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
        title=f"{symbol_key}/USD — Buy & Hold Cumulative Return (last {len(tail)} bars)",
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

def _stack_masks(view):
    long_stack  = ((view["ema20"] > view["ema50"]) & (view["ema50"] > view["ema100"])).fillna(False)
    short_stack = ((view["ema20"] < view["ema50"]) & (view["ema50"] < view["ema100"])).fillna(False)
    return long_stack, short_stack

def _finalize_trades(trades: list) -> pd.DataFrame:
    tdf = pd.DataFrame(trades)
    if not tdf.empty:
        tdf["entry_ts"] = pd.to_datetime(tdf["entry_ts"])
        tdf["exit_ts"]  = pd.to_datetime(tdf["exit_ts"])

        # net P&L is already fee-adjusted in pnl_pct; convert to fraction
        tdf["pnl_frac"] = tdf["pnl_pct"].astype(float) / 100.0

        # COMPOUNDED cumulative, mirrors TradingView equity logic:
        # equity_n = equity_0 * Π(1 + pnl_i)
        tdf["cum_frac"] = (1.0 + tdf["pnl_frac"]).cumprod() - 1.0
        tdf["cum_pnl_pct"] = tdf["cum_frac"] * 100.0
    return tdf


def _append_trade(trades: list, view, side: str, entry_i: int, exit_i: int, fee: float):
    # TradingView-style fills: entry at next bar OPEN, exit at flip bar CLOSE
    entry_px = float(view["open"].iat[entry_i])
    exit_px  = float(view["close"].iat[exit_i])

    pnl_frac = _pnl_long(entry_px, exit_px, fee) if side == "long" else _pnl_short(entry_px, exit_px, fee)

    # window used for MFE/MAE (from entry bar through exit bar inclusive)
    win = view.iloc[entry_i:exit_i+1]
    if side == "long":
        mfe = (win["high"].max() / entry_px - 1.0) * 100.0
        mae = (win["low"].min()  / entry_px - 1.0) * 100.0
    else:
        mfe = (entry_px / win["low"].min()  - 1.0) * 100.0
        mae = (entry_px / win["high"].max() - 1.0) * 100.0

    trades.append({
        "side": side,
        "entry_ts": view["ts"].iat[entry_i],
        "exit_ts":  view["ts"].iat[exit_i],
        "entry_px": entry_px,
        "exit_px":  exit_px,
        "pnl_pct":  pnl_frac * 100.0,
        "runup_pct": mfe,
        "drawdown_pct": mae,
    })


# ===== One generic builder =====
def build_trades(view: pd.DataFrame, *, mode: str, fee: float) -> pd.DataFrame:
    """
    mode: 'long', 'short', or 'both'
    TradingView-like execution:
      - detect flip on bar i
      - EXIT on bar i CLOSE
      - ENTER on bar i+1 OPEN (if a stack is ON)
    """
    long_stack, short_stack = _stack_masks(view)
    N = len(view)
    if N < 2:
        return pd.DataFrame()

    def _enter_idx(i_flip: int) -> int | None:
        j = i_flip + 1
        return j if j < N else None  # need a next bar to enter

    trades: list[dict] = []

    if mode in {"long", "short"}:
        stack = long_stack if mode == "long" else short_stack
        in_pos, entry_i = False, None

        for i in range(N):  # i is the bar we *observe*
            turn_on  = bool(stack.iat[i]) and (not bool(stack.iat[i-1]) if i > 0 else True)
            turn_off = (not bool(stack.iat[i])) and (bool(stack.iat[i-1]) if i > 0 else False)

            if not in_pos and turn_on:
                j = _enter_idx(i)
                if j is not None:
                    in_pos, entry_i = True, j

            elif in_pos and turn_off:
                _append_trade(trades, view, mode, entry_i, i, fee)
                in_pos, entry_i = False, None

        # If still in position at the very end, liquidate on the *last* bar close
        if in_pos and entry_i is not None:
            _append_trade(trades, view, mode, entry_i, N - 1, fee)

        return _finalize_trades(trades)

    # ---- mode == "both": flip between sides with TV-style scheduling ----
    side, entry_i = None, None

    for i in range(N):
        want_long, want_short = bool(long_stack.iat[i]), bool(short_stack.iat[i])

        if side is None:
            # schedule an entry for next bar’s open if any stack is ON now
            if want_long or want_short:
                j = _enter_idx(i)
                if j is not None:
                    side, entry_i = ("long" if want_long else "short"), j

        else:
            # need to close current side on this bar's close?
            need_close = (side == "long" and not want_long) or (side == "short" and not want_short)
            if need_close:
                _append_trade(trades, view, side, entry_i, i, fee)
                side, entry_i = None, None
                # if the opposite stack is ON already on this bar, schedule a new entry for next open
                if want_long or want_short:
                    j = _enter_idx(i)
                    if j is not None:
                        side, entry_i = ("long" if want_long else "short"), j

    # liquidate any open position on the last bar's close
    if side is not None and entry_i is not None:
        _append_trade(trades, view, side, entry_i, N - 1, fee)

    return _finalize_trades(trades)



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

    # symbol
    symbol_key = (symbol_key or "").upper()
    if symbol_key not in SYMBOL_MAP:
        return HttpResponseBadRequest("Unsupported symbol")

    # data
    csv_path = _csv_path(symbol_key)
    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")
    df = _load_basic_df(csv_path)
    if df.empty or df["ts"].isna().all():
        return HttpResponseBadRequest("No data in CSV.")

    # timeframe & window
    tf = (request.GET.get("tf") or "5m").lower()
    tf = tf if tf in {"5m", "1h", "4h", "1d"} else "5m"
    window = compute_period_window(df, request.GET.get("start"), request.GET.get("end"))
    view = slice_and_resample(df, window, tf)

    # strategies (rolled back to 4 options)
    allowed = {"ema_stack_long", "ema_stack_short", "ema_stack_long_short", "lorentzian_advta"}
    strat_key = (request.GET.get("strat") or "ema_stack_long").lower()
    if strat_key not in allowed:
        strat_key = "ema_stack_long"

    trades_df, strat_title = build_trades_for_strategy(view, strat_key, fee)

    # figures
    fig_c = make_candle_fig(view, symbol_key, window, tf)
    fig_p = make_equity_fig(view, trades_df, symbol_key, strat_title, tf)

    # overlay markers for LC only
    if strat_key == "lorentzian_advta":
        add_markers_to_candle(fig_c, view, trades_df)

    # table + js
    table_html = trades_table_html(trades_df)
    js_interactions = trades_table_js(BAR_MS_MAP[tf], pre_bars=36)

    # jsonify figs
    fig_c_json = fig_c.to_json()
    fig_p_json = fig_p.to_json()

    # jupyter link
    start_val = window.start_period.strftime("%Y-%m")
    end_val   = window.end_period.strftime("%Y-%m")
    nb_base = request.build_absolute_uri(reverse("analysis_to_jupyter", args=[symbol_key]))
    jupyter_url = f"{nb_base}?start={start_val}&end={end_val}&tf={tf}&strat={strat_key}&fee={fee:.6f}"

    # dropdown selections
    sel_long  = "selected" if strat_key == "ema_stack_long" else ""
    sel_short = "selected" if strat_key == "ema_stack_short" else ""
    sel_both  = "selected" if strat_key == "ema_stack_long_short" else ""
    sel_lc    = "selected" if strat_key == "lorentzian_advta" else ""

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{symbol_key} — Candles & Strategy</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  body{{font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;padding:16px;}}
  a{{text-decoration:none}}
  .back{{margin-bottom:12px;display:inline-block}}
  .wrap{{max-width:1200px;margin:0 auto;}}
  .toolbar{{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:8px 0 16px 0}}
  .stack{{display:flex;flex-direction:column;gap:24px}}
  .card{{padding:8px;border:1px solid #e5e7eb;border-radius:8px;background:#fff}}
  h2{{margin:0 0 8px 0;font-size:18px;text-align:center}}
  #chart-c, #chart-p{{width:100%;height:600px}}
  @media (max-width:700px){{ #chart-c, #chart-p{{height:420px}} }}
  input[type=month]{{padding:6px}}
  select, button{{padding:6px 10px;cursor:pointer}}
  .hint{{color:#555}}
  .btn{{display:inline-block;padding:6px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#f8fafc;color:#111}}
  .btn:hover{{background:#eef2ff}}
  .tbl{{width:100%;border-collapse:collapse}}
  .tbl th,.tbl td{{border:1px solid #e5e7eb;padding:6px 8px;text-align:left;white-space:nowrap}}
  .tbl thead th{{background:#f8fafc}}
</style>
</head>
<body>
<a class="back" href="/investments">← Back to Investments</a>
<div class="wrap">
  <form class="toolbar" method="get" action="">
    <label for="start">Start month:</label>
    <input type="month" id="start" name="start" min="{window.min_month}" max="{window.max_month}" value="{start_val}">
    <label for="end">End month:</label>
    <input type="month" id="end" name="end" min="{window.min_month}" max="{window.max_month}" value="{end_val}">
    <label for="tf">Timeframe:</label>
    <select id="tf" name="tf">
      <option value="5m" {"selected" if tf=="5m" else ""}>5m</option>
      <option value="1h" {"selected" if tf=="1h" else ""}>1h</option>
      <option value="4h" {"selected" if tf=="4h" else ""}>4h</option>
      <option value="1d" {"selected" if tf=="1d" else ""}>1d</option>
    </select>
    <label for="strat">Strategy:</label>
    <select id="strat" name="strat">
      <option value="ema_stack_long" {sel_long}>EMA Stack — Long</option>
      <option value="ema_stack_short" {sel_short}>EMA Stack — Short</option>
      <option value="ema_stack_long_short" {sel_both}>EMA Stack — Long &amp; Short</option>
      <option value="lorentzian_advta" {sel_lc}>Lorentzian Classification</option>
    </select>
    <button type="submit">Apply</button>
    <a class="btn" id="nbBtn" href="{jupyter_url}">Open in Jupyter</a>
    <span class="hint">Available data: {window.min_month} → {window.max_month}</span>
  </form>
  <div class="stack">
    <div class="card"><h2>Candlestick</h2><div id="chart-c"></div></div>
    <div class="card"><h2>{strat_title}</h2><div id="chart-p"></div></div>
    <div class="card"><h2>Trades</h2><details open><summary>Show trades table</summary><div style="margin-top:10px; overflow:auto;">{table_html}</div></details></div>
  </div>
</div>
<script>
  const figC = {fig_c_json};
  const figP = {fig_p_json};
  Plotly.newPlot("chart-c", figC.data, figC.layout, {{responsive:true}});
  Plotly.newPlot("chart-p", figP.data, figP.layout, {{responsive:true}});
  function wireAutoY(id) {{
    const gd = document.getElementById(id);
    let t=null;
    const kick=()=>{{ if(t)clearTimeout(t); t=setTimeout(()=>{{Plotly.relayout(gd, {{'yaxis.autorange': true}});}},25); }};
    const touchedX=(ev={{}})=>Object.keys(ev).some(k=>k.startsWith('xaxis.'));
    gd.on('plotly_relayout',ev=>{{if(touchedX(ev))kick();}});
    gd.on('plotly_relayouting',ev=>{{if(touchedX(ev))kick();}});
  }}
  wireAutoY('chart-c'); wireAutoY('chart-p');
</script>
<script>{js_interactions}</script>
</body></html>"""
    return HttpResponse(html)







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
    if symbol_key not in SYMBOL_MAP:
        return HttpResponseBadRequest("Unsupported symbol")

    csv_path = _csv_path(symbol_key)
    if not csv_path.exists():
        return HttpResponseBadRequest(f"CSV not found for {symbol_key}. Click 'Get CSV' first.")

    df_full = _load_basic_df(csv_path)
    if df_full.empty:
        return HttpResponseBadRequest("No data in CSV.")

    # --- month window (default last 6 months) ---
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
        except Exception: start_period = end_period - 5
    if start_period > end_period:
        start_period, end_period = end_period, start_period

    # --- resample + window (ALWAYS via resample_ohlc so EMA columns exist) ---
    rule_map = {"5m": None, "1h": "1H", "4h": "4H", "1d": "1D"}
    view_all = resample_ohlc(df_full, rule_map[tf])

    mask = (view_all["ts"].dt.to_period("M") >= start_period) & (view_all["ts"].dt.to_period("M") <= end_period)
    view = view_all.loc[mask].reset_index(drop=True)
    if view.empty:
        return HttpResponseBadRequest("No data in selected window.")

    # --- build trades ---
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




