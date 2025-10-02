# backend/accounts/analysis_helpers.py
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Tuple
import plotly.graph_objects as go
from .strategy_lorentzian import lorentzian_trades_advta
import mplfinance as mpf


RULE_MAP = {"5m": None, "1h": "1H", "4h": "4H", "1d": "1D"}
BAR_MS_MAP = {"5m": 5*60*1000, "1h": 60*60*1000, "4h": 4*60*60*1000, "1d": 24*60*60*1000}
FEE_DEFAULT: float = 0.002

@dataclass
class PeriodWindow:
    start_period: pd.Period
    end_period: pd.Period
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    ts_min: pd.Timestamp
    ts_max: pd.Timestamp
    min_month: str
    max_month: str
    

def compute_period_window(df: pd.DataFrame, start_month_str: str | None, end_month_str: str | None) -> PeriodWindow:
    ts_min = pd.to_datetime(df["ts"].min())
    ts_max = pd.to_datetime(df["ts"].max())
    min_month = ts_min.strftime("%Y-%m")
    max_month = ts_max.strftime("%Y-%m")

    if not end_month_str:
        end_period = ts_max.to_period("M"); start_period = (end_period - 5)
    else:
        try: end_period = pd.Period(end_month_str, freq="M")
        except Exception: end_period = ts_max.to_period("M")

    if not start_month_str:
        start_period = locals().get("start_period") or (end_period - 5)
    else:
        try: start_period = pd.Period(start_month_str, freq="M")
        except Exception: start_period = end_period - 5

    if start_period > end_period:
        start_period, end_period = end_period, start_period

    start_ts = start_period.to_timestamp(how="start")
    end_ts   = (end_period + 1).to_timestamp(how="start") - pd.Timedelta(seconds=1)

    return PeriodWindow(
        start_period=start_period,
        end_period=end_period,
        start_ts=start_ts,
        end_ts=end_ts,
        ts_min=ts_min,
        ts_max=ts_max,
        min_month=min_month,
        max_month=max_month,
    )
    

def tf_to_rule(tf: str) -> str:
    """
    Normalize a timeframe string to a pandas resample rule.
    Accepts forms like 5m/5min, 60m, 1h/1H, 4h, 1d/1D, etc.
    Raises ValueError for unsupported values.
    """
    if not tf:
        raise ValueError("Empty timeframe")

    tf = str(tf).strip()
    # Fast path for common aliases
    if tf in RULE_MAP:
        return RULE_MAP[tf]

    # Generic patterns like "60m", "2h", "3d"
    m = re.match(r"^(\d+)\s*([mMhHdD])$", tf)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "m":
            return f"{n}min"
        if unit == "h":
            return f"{n}H"
        if unit == "d":
            return f"{n}D"

    # Some UIs use D1/H1 style
    m = re.match(r"^[dDhH](\d+)$", tf)
    if m:
        n = int(m.group(1))
        if tf[0].lower() == "h":
            return f"{n}H"
        return f"{n}D"

    # Last-ditch: common words
    if tf.lower() in {"day", "daily"}:
        return "1D"
    if tf.lower() in {"hour", "hourly"}:
        return "1H"
    if tf.lower() in {"min", "minute", "minutes"}:
        return "1min"

    raise ValueError(f"Unsupported timeframe: {tf!r}")


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample OHLCV to a higher timeframe with right-closed/right-labeled bars.
    Requires columns: ts, open, high, low, close (volume optional -> filled with 0.0).
    Returns a DataFrame with the same columns, ts in UTC.
    """
    if "volume" not in df.columns:
        df = df.copy()
        df["volume"] = 0.0

    # Ensure datetime index in UTC
    out = df.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce")
    out = out.dropna(subset=["ts"]).set_index("ts").sort_index()

    agg = {
        "open":  "first",
        "high":  "max",
        "low":   "min",
        "close": "last",
        "volume":"sum",
    }

    res = (
        out.resample(rule, label="right", closed="right")
           .agg(agg)
           .dropna(subset=["open", "close"])
    )
    res = res.reset_index()  # ts back to a column
    return res


def slice_and_resample(df: pd.DataFrame, window: PeriodWindow, tf: str) -> pd.DataFrame:
    """Slice to month window on 5m then resample."""
    view_5m = df[(df["ts"] >= window.start_ts) & (df["ts"] <= window.end_ts)].copy()
    tf_s = str(tf).strip()
    if tf_s in ("5m", "5min"):
        view = view_5m.copy()
    else:
        rule = tf_to_rule(tf_s)      # robust normalization (we added this earlier)
        view = resample_ohlc(view_5m, rule)

    # NEW: make sure EMA columns exist on the returned view
    ensure_ema_cols(view, spans=(20, 50, 100))
    return view

def build_trades_for_strategy(view: pd.DataFrame, strat_key: str, fee: float) -> tuple[pd.DataFrame, str]:
    """
    Given a sliced/resampled `view`, produce a trades DataFrame and a title
    for the chosen strategy key. Keeps imports local to avoid circulars.
    """
    # NOTE: `fee` here is round-trip (e.g., 0.002). Kalman funcs expect per-side.
    fee_side = float(fee) / 2.0

    # Lazy import to avoid circular import at module load time
    from .views_analysis import build_trades  # EMA stack lives there
    try:
        # Kalman lives in strategies.py (already added by you)
        from .strategies import kalman_long, kalman_short, kalman_cross
    except Exception:
        kalman_long = kalman_short = kalman_cross = None  # noqa: F841

    if strat_key == "ema_stack_long":
        title = "EMA 20/50/100 Stack — Long"
        trades_df = build_trades(view, mode="long", fee=fee)
    elif strat_key == "ema_stack_short":
        title = "EMA 20/50/100 Stack — Short"
        trades_df = build_trades(view, mode="short", fee=fee)
    elif strat_key == "ema_stack_long_short":
        title = "EMA 20/50/100 Stack — Long & Short"
        trades_df = build_trades(view, mode="both", fee=fee)

    elif strat_key == "lorentzian_advta":
        title = "Lorentzian Classification — Equity"
        trades_df = lorentzian_trades_advta(view, fee_frac=fee)

    elif strat_key in {"kalman_long", "kalman_short", "kalman_cross"}:
        title_map = {
            "kalman_long":  "Kalman Cross — Long Only",
            "kalman_short": "Kalman Cross — Short Only",
            "kalman_cross": "Kalman Cross — Flip Long/Short",
        }
        title = title_map[strat_key]

        v2 = attach_kalman_cols(view)
        long_mask  = (v2["kal_slope_s"] > v2["kal_slope_l"])
        short_mask = (v2["kal_slope_s"] < v2["kal_slope_l"])
        mode = "long" if strat_key == "kalman_long" else ("short" if strat_key == "kalman_short" else "both")

        trades_df = build_trades_from_masks(v2, long_mask, short_mask, mode=mode, fee=fee)

        # 🔧 Ensure the four columns the table expects:
        trades_df = _attach_trade_stats(v2, trades_df)

    else:
        # fallback keeps old default
        title = "EMA 20/50/100 Stack — Long"
        trades_df = build_trades(view, mode="long", fee=fee)

    return (trades_df if isinstance(trades_df, pd.DataFrame) else pd.DataFrame(trades_df)), title



def build_trades_from_masks(view: pd.DataFrame, long_mask: pd.Series, short_mask: pd.Series, *, mode: str = "both", fee: float = 0.002) -> pd.DataFrame:
    view = _ensure_ts_index(view)
    idx = view.index
    close = pd.to_numeric(view["close"], errors="coerce")
    trades = []
    pos = 0  # 1 long, -1 short, 0 flat
    ent_i = None; ent_px = np.nan; bars = 0

    def _append(side, ei, ep, xi, xp, held, reason):
        gross = (xp / ep) if side == "long" else (ep / xp)
        net_factor = float(gross * (1.0 - float(fee)))  # one round-trip
        trades.append({"side": side, "entry_ts": idx[ei], "entry_px": float(ep), "exit_ts": idx[xi], "exit_px": float(xp), "bars_held": int(held), "net_factor": net_factor, "reason": reason})

    for i in range(1, len(idx)):
        lm = bool(long_mask.iloc[i])
        sm = bool(short_mask.iloc[i])

        if mode == "long":
            if pos == 0 and lm:
                pos, ent_i, ent_px, bars = 1, i, close.iat[i], 0
            elif pos == 1 and not lm:
                _append("long", ent_i, ent_px, i, close.iat[i], bars + 1, "break"); pos, ent_i, ent_px, bars = 0, None, np.nan, 0
            else:
                if pos: bars += 1

        elif mode == "short":
            if pos == 0 and sm:
                pos, ent_i, ent_px, bars = -1, i, close.iat[i], 0
            elif pos == -1 and not sm:
                _append("short", ent_i, ent_px, i, close.iat[i], bars + 1, "break"); pos, ent_i, ent_px, bars = 0, None, np.nan, 0
            else:
                if pos: bars += 1

        else:  # both (flip)
            if lm and (pos <= 0):
                if pos == -1:
                    _append("short", ent_i, ent_px, i, close.iat[i], bars + 1, "flip")
                pos, ent_i, ent_px, bars = 1, i, close.iat[i], 0
            elif sm and (pos >= 0):
                if pos == 1:
                    _append("long", ent_i, ent_px, i, close.iat[i], bars + 1, "flip")
                pos, ent_i, ent_px, bars = -1, i, close.iat[i], 0
            else:
                if pos: bars += 1

    df_tr = pd.DataFrame(trades)
    if df_tr.empty:
        return pd.DataFrame(columns=["side","entry_ts","entry_px","exit_ts","exit_px","bars_held","net_factor","reason"])
    return df_tr.sort_values("exit_ts").reset_index(drop=True)






def make_candle_fig(view: pd.DataFrame, symbol_key: str, window: PeriodWindow, tf: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=view["ts"], open=view["open"], high=view["high"], low=view["low"], close=view["close"],
        name=f"{symbol_key}/USD"
    ))
    for col, label in [("ema20","EMA20"), ("ema50","EMA50"), ("ema100","EMA100")]:
        if col in view.columns and view[col].notna().any():
            fig.add_trace(go.Scatter(x=view["ts"], y=view[col], mode="lines", name=label))

    fig.update_layout(
        title=f"{symbol_key}/USD — {window.start_period.strftime('%Y-%m')} → {window.end_period.strftime('%Y-%m')}  (tf={tf})",
        xaxis_rangeslider_visible=True,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom", xanchor="left"),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
    fig.update_yaxes(title_text="Price (USD)")
    return fig

def make_equity_fig(view: pd.DataFrame, trades_df: pd.DataFrame, symbol_key: str, strat_title: str, tf: str) -> go.Figure:
    fig = go.Figure()
    if not trades_df.empty:
        time_index = view["ts"]
        step_eq  = stepwise_equity_from_trades(trades_df, time_index, start_value=1.0)
        step_pct = (step_eq - 1.0) * 100.0
        fig.add_trace(go.Scatter(
            x=time_index, y=step_pct,
            mode="lines", line_shape="hv",
            name="Cumulative % (stepwise)",
            line=dict(width=2)
        ))
    fig.update_layout(
        title=f"{symbol_key}/USD — {strat_title} (tf={tf})",
        xaxis_rangeslider_visible=True,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=50, b=30),
        yaxis_title="Cumulative Return (%)",
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom", xanchor="left"),
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1)
    return fig

def trades_table_html(trades_df: pd.DataFrame) -> str:
    """Return HTML table with sort buttons and row data attributes for zooming."""
    if trades_df.empty:
        return "<p>No closed trades in this window.</p>"

    df_show = trades_df.copy()
    for c in ("entry_ts", "exit_ts"):
        if c in df_show.columns:
            df_show[c] = pd.to_datetime(df_show[c]).dt.strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for r in df_show.itertuples(index=False):
        side_val = str(getattr(r, "side", "")).lower()
        entry_ts = getattr(r, "entry_ts", "")
        exit_ts  = getattr(r, "exit_ts", "")

        # Side badge becomes a button; also carries entry/exit for direct zoom
        if side_val == "long":
            side_badge = (
                f"<button type='button' class='badge long side-btn' "
                f"data-entry='{entry_ts}' data-exit='{exit_ts}' "
                f"title='Center charts on this trade'>LONG</button>"
            )
        else:
            side_badge = (
                f"<button type='button' class='badge short side-btn' "
                f"data-entry='{entry_ts}' data-exit='{exit_ts}' "
                f"title='Center charts on this trade'>SHORT</button>"
            )

        entry_px = float(getattr(r, "entry_px", 0.0))
        exit_px  = float(getattr(r, "exit_px", 0.0))
        pnl      = float(getattr(r, "pnl_pct", 0.0))
        runup    = float(getattr(r, "runup_pct", 0.0)) if hasattr(r, "runup_pct") else 0.0
        drawdown = float(getattr(r, "drawdown_pct", 0.0)) if hasattr(r, "drawdown_pct") else 0.0
        cum      = float(getattr(r, "cum_pnl_pct", 0.0)) if hasattr(r, "cum_pnl_pct") else 0.0
        pnl_class = "pos" if pnl >= 0 else "neg"
        cum_class = "pos" if cum >= 0 else "neg"

        rows.append(
            f"<tr class='trade-row' data-entry='{entry_ts}' data-exit='{exit_ts}'>"
            f"<td data-type='text'>{side_badge}</td>"
            f"<td data-type='date'>{entry_ts}</td>"
            f"<td data-type='date'>{exit_ts}</td>"
            f"<td data-type='num' style='text-align:right'>{entry_px:.6f}</td>"
            f"<td data-type='num' style='text-align:right'>{exit_px:.6f}</td>"
            f"<td data-type='num' class='{pnl_class}' style='text-align:right'>{pnl: .2f}%</td>"
            f"<td data-type='num' style='text-align:right'>{runup: .2f}%</td>"
            f"<td data-type='num' style='text-align:right'>{drawdown: .2f}%</td>"
            f"<td data-type='num' class='{cum_class}' style='text-align:right'>{cum: .2f}%</td>"
            f"</tr>"
        )

    table = (
        "<table class='tbl' id='tradesTbl'>"
        "<thead><tr>"
        "<th><button class='th-sort' data-idx='0' data-type='text'>Side</button></th>"
        "<th><button class='th-sort' data-idx='1' data-type='date'>Entry time</button></th>"
        "<th><button class='th-sort' data-idx='2' data-type='date'>Exit time</button></th>"
        "<th><button class='th-sort' data-idx='3' data-type='num'>Entry px</button></th>"
        "<th><button class='th-sort' data-idx='4' data-type='num'>Exit px</button></th>"
        "<th><button class='th-sort' data-idx='5' data-type='num'>Net P&L</button></th>"
        "<th><button class='th-sort' data-idx='6' data-type='num'>Run-up</button></th>"
        "<th><button class='th-sort' data-idx='7' data-type='num'>Drawdown</button></th>"
        "<th><button class='th-sort' data-idx='8' data-type='num'>Cumulative</button></th>"
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )
    return table


from string import Template

def trades_table_js(bar_ms: int, pre_bars: int = 36) -> str:
    """
    Interactive JS for the Trades table:
      • Sort columns by header button
      • Click a row or Side badge to zoom both charts to [entry - pre_bars, exit]
      • Candlestick y-axis auto-rescales to visible x-range and stays locked
    Uses Template to avoid f-string brace conflicts.
    """
    js_tpl = Template(r"""
/* ---- Trades table interactions + sticky y-autoscale on x-zoom ---- */
(function() {
  const tbl  = document.getElementById('tradesTbl');
  const cand = document.getElementById('chart-c'); // candlestick
  const eqty = document.getElementById('chart-p'); // cumulative / equity
  if (!tbl) return;

  const BAR_MS  = ${bar_ms};
  const PRE_BARS = ${pre_bars};

  // ---------- Helpers ----------
  const toMs = v => (v instanceof Date ? +v : new Date(v).getTime());

  // Compute y-range from the *visible* candles in current x-window
  function computeVisibleYRange(gd) {
    if (!gd || !gd._fullLayout || !Array.isArray(gd._fullData)) return null;
    const fl = gd._fullLayout;
    const tr = gd._fullData.find(t => t && (t.type === 'candlestick' || t.type === 'scatter' || t.type === 'ohlc'));
    if (!tr || !fl.xaxis) return null;

    let xr = fl.xaxis.range;
    if (!xr || xr.length !== 2) return null;

    const x0 = toMs(xr[0]);
    const x1 = toMs(xr[1]);

    const xs = tr.x || [];
    const lows  = tr.low  || null;
    const highs = tr.high || null;
    const opens = tr.open || null;
    const closes= tr.close|| null;
    const ys    = tr.y    || null;

    let ymin =  Infinity;
    let ymax = -Infinity;

    for (let i = 0; i < xs.length; i++) {
      const xi = toMs(xs[i]);
      if (xi >= x0 && xi <= x1) {
        if (lows && highs) {
          const lo = +lows[i], hi = +highs[i];
          if (Number.isFinite(lo) && lo < ymin) ymin = lo;
          if (Number.isFinite(hi) && hi > ymax) ymax = hi;
        } else if (opens && closes) {
          const a = Math.min(+opens[i], +closes[i]);
          const b = Math.max(+opens[i], +closes[i]);
          if (Number.isFinite(a) && a < ymin) ymin = a;
          if (Number.isFinite(b) && b > ymax) ymax = b;
        } else if (ys) {
          const yi = +ys[i];
          if (Number.isFinite(yi) && yi < ymin) ymin = yi;
          if (Number.isFinite(yi) && yi > ymax) ymax = yi;
        }
      }
    }

    if (ymin ===  Infinity || ymax === -Infinity) return null;

    const pad = (ymax - ymin) * 0.05 || Math.max(1e-9, Math.abs(ymax) * 0.001);
    return [ymin - pad, ymax + pad];
  }

  // Apply explicit y-range and *disable* autorange so it doesn't snap back
  function applyStickyY(gd) {
    const yr = computeVisibleYRange(gd);
    if (!yr) {
      Plotly.relayout(gd, { 'yaxis.autorange': true }).then(() => {
        requestAnimationFrame(() => {
          Plotly.relayout(gd, { 'yaxis.autorange': false });
        });
      });
      return;
    }
    Plotly.relayout(gd, { 'yaxis.range': yr, 'yaxis.autorange': false });
  }

  // Debounced/staged sticky y so our change wins any internal relayout timing
  let rafToken = null;
  function stickyNowAndAfter(gd) {
    applyStickyY(gd);
    if (rafToken) cancelAnimationFrame(rafToken);
    rafToken = requestAnimationFrame(() => {
      applyStickyY(gd);
      setTimeout(() => applyStickyY(gd), 0);
    });
  }

  function zoomBoth(entryMs, exitMs) {
    const pad = PRE_BARS * BAR_MS;
    const x0 = new Date(entryMs - pad);
    const x1 = new Date(exitMs);

    if (cand) {
      Plotly.relayout(cand, { 'xaxis.range': [x0, x1] }).then(() => {
        stickyNowAndAfter(cand);
      });
    }
    if (eqty) {
      Plotly.relayout(eqty, { 'xaxis.range': [x0, x1], 'yaxis.autorange': true });
    }
  }

  // ---------- Sorting (kept from your working version) ----------
  function cmp(a, b, type) {
    if (type === 'num') {
      const na = parseFloat(a.replace(/[^0-9.+-]/g,'')) || 0;
      const nb = parseFloat(b.replace(/[^0-9.+-]/g,'')) || 0;
      return na - nb;
    } else if (type === 'date') {
      return new Date(a).getTime() - new Date(b).getTime();
    } else {
      return String(a).localeCompare(String(b));
    }
  }
  let sortState = { col: null, asc: true };
  tbl.querySelectorAll('thead .th-sort').forEach(btn => {
    btn.addEventListener('click', () => {
      const col = parseInt(btn.dataset.idx, 10);
      const type = btn.dataset.type || 'text';
      const rows = Array.from(tbl.querySelectorAll('tbody tr'));
      const asc = (sortState.col === col) ? !sortState.asc : true;
      sortState = { col, asc };
      rows.sort((r1, r2) => {
        const t1 = r1.children[col]?.textContent?.trim() || '';
        const t2 = r2.children[col]?.textContent?.trim() || '';
        const d = cmp(t1, t2, type);
        return asc ? d : -d;
      });
      const tb = tbl.querySelector('tbody');
      rows.forEach(r => tb.appendChild(r));
    });
  });

  // ---------- Row click -> zoom ----------
  tbl.querySelectorAll('tbody tr.trade-row').forEach(tr => {
    tr.addEventListener('click', (ev) => {
      if (ev.target?.closest('button')) return; // side button handles itself
      const entryStr = tr.getAttribute('data-entry');
      const exitStr  = tr.getAttribute('data-exit');
      if (!entryStr || !exitStr) return;
      zoomBoth(new Date(entryStr).getTime(), new Date(exitStr).getTime());
    });

    // Turn the Side badge into a clickable button that also zooms
    const badge = tr.querySelector('.badge.long, .badge.short');
    if (badge) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = badge.className + ' btn-side';
      btn.style.padding = '2px 8px';
      btn.style.cursor = 'pointer';
      btn.textContent = badge.textContent;
      badge.replaceWith(btn);

      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const entryStr = tr.getAttribute('data-entry');
        const exitStr  = tr.getAttribute('data-exit');
        if (!entryStr || !exitStr) return;
        zoomBoth(new Date(entryStr).getTime(), new Date(exitStr).getTime());
      });
    }
  });

  // ---------- Keep candle y scaled while dragging & after release ----------
  if (cand && typeof cand.on === 'function') {
    cand.on('plotly_relayouting', (e) => {
      const touchedX = e && Object.keys(e).some(k => k.startsWith('xaxis.'));
      if (!touchedX) return;
      applyStickyY(cand);
    });

    cand.on('plotly_relayout', (e) => {
      const touchedX = e && Object.keys(e).some(k => k.startsWith('xaxis.'));
      if (!touchedX) return;
      stickyNowAndAfter(cand);
    });

    cand.on('plotly_doubleclick', () => {
      Plotly.relayout(cand, { 'xaxis.autorange': true, 'yaxis.autorange': true });
      setTimeout(() => Plotly.relayout(cand, { 'yaxis.autorange': false }), 0);
    });
  }

  // Initial pass once the first draw is in the DOM
  if (cand) setTimeout(() => stickyNowAndAfter(cand), 60);
})();
""")
    return js_tpl.safe_substitute(bar_ms=bar_ms, pre_bars=pre_bars)



def add_markers_to_candle(fig: go.Figure, view: pd.DataFrame, trades_df: pd.DataFrame) -> None:
    if trades_df.empty:
        return
    px_map = view.set_index("ts")["close"]
    longs  = trades_df.loc[trades_df["side"] == "long",  "entry_ts"]
    shorts = trades_df.loc[trades_df["side"] == "short", "entry_ts"]

    if len(longs):
        x = pd.to_datetime(longs);  y = px_map.reindex(x, method="nearest").values
        fig.add_scatter(x=x, y=y, mode="markers", name="LC BUY",
                        marker_symbol="triangle-up", marker_size=10)
    if len(shorts):
        x = pd.to_datetime(shorts); y = px_map.reindex(x, method="nearest").values
        fig.add_scatter(x=x, y=y, mode="markers", name="LC SELL",
                        marker_symbol="triangle-down", marker_size=10)



def ensure_ema_cols(df: pd.DataFrame, spans: tuple[int, ...] = (20, 50, 100)) -> pd.DataFrame:
    """
    Ensure ema{span} columns exist on df using EWM over 'close'.
    Leaves existing EMA columns untouched. Returns the same df (mutates in place).
    """
    if "close" not in df.columns:
        raise KeyError("close column missing; cannot compute EMAs")
    for span in spans:
        col = f"ema{span}"
        if col not in df.columns:
            df[col] = df["close"].ewm(span=span, adjust=False, min_periods=span).mean()
    return df


def stepwise_equity_from_trades(trades_df: pd.DataFrame, time_index: pd.Series, start_value: float = 1.0) -> pd.Series:
    """
    Build a stepwise equity curve aligned to `time_index` that jumps at each trade exit.
    `trades_df` should have at least ['exit_ts'] and either:
      - 'pnl_pct' (percent), or
      - 'pnl' / 'ret' as decimal, or
      - ['side','entry_px','exit_px'] to compute a gross multiplier.
    Returns a pd.Series indexed by `time_index`.
    """
    ti = pd.to_datetime(time_index, utc=True, errors="coerce")
    ti = ti.dropna()
    if trades_df is None or trades_df.empty or len(ti) == 0:
        return pd.Series(start_value, index=ti)

    df = trades_df.copy()
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["exit_ts"]).sort_values("exit_ts")

    # Determine multiplicative P&L per trade
    if "pnl_pct" in df.columns:
        mult = 1.0 + df["pnl_pct"].astype(float) / 100.0
    elif "pnl" in df.columns:
        mult = 1.0 + df["pnl"].astype(float)
    elif "ret" in df.columns:
        mult = 1.0 + df["ret"].astype(float)
    elif {"side", "entry_px", "exit_px"}.issubset(df.columns):
        # fallback, no fees applied here (assume already included upstream if needed)
        is_long = (df["side"] == "long").to_numpy()
        entry = df["entry_px"].astype(float).to_numpy()
        exit_ = df["exit_px"].astype(float).to_numpy()
        gross = np.where(is_long, exit_ / entry, entry / exit_)
        mult = pd.Series(gross, index=df.index)
    else:
        # nothing we can do; flat line
        return pd.Series(start_value, index=ti)

    exit_ts = df["exit_ts"].to_numpy()
    mult_vals = np.asarray(mult, dtype=float)

    eq_vals = np.empty(len(ti), dtype=float)
    value = float(start_value)
    cursor = 0

    for ts, m in zip(exit_ts, mult_vals):
        j = int(ti.searchsorted(ts, side="right") - 1)  # nearest bar at or before exit
        if j < 0:
            value *= m
            continue
        if j >= cursor:
            eq_vals[cursor : j + 1] = value
            cursor = j + 1
        value *= m

    if cursor < len(ti):
        eq_vals[cursor:] = value

    return pd.Series(eq_vals, index=ti)


def _normalize_trade_cols(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce arbitrary trades into the canonical schema expected by the UI:
    ['side','entry_ts','entry_px','exit_ts','exit_px','bars_held','net_factor','reason']
    """
    if trades_df is None or trades_df.empty:
        return pd.DataFrame(columns=[
            "side","entry_ts","entry_px","exit_ts","exit_px","bars_held","net_factor","reason"
        ])

    df = trades_df.copy()

    # Rename common synonyms to canonical names
    rename = {}
    if "entry_time"   in df.columns and "entry_ts" not in df.columns:   rename["entry_time"]   = "entry_ts"
    if "exit_time"    in df.columns and "exit_ts"  not in df.columns:   rename["exit_time"]    = "exit_ts"
    if "entry"        in df.columns and "entry_ts" not in df.columns:   rename["entry"]        = "entry_ts"
    if "exit"         in df.columns and "exit_ts"  not in df.columns:   rename["exit"]         = "exit_ts"
    if "entry_price"  in df.columns and "entry_px" not in df.columns:   rename["entry_price"]  = "entry_px"
    if "exit_price"   in df.columns and "exit_px"  not in df.columns:   rename["exit_price"]   = "exit_px"
    if "price_entry"  in df.columns and "entry_px" not in df.columns:   rename["price_entry"]  = "entry_px"
    if "price_exit"   in df.columns and "exit_px"  not in df.columns:   rename["price_exit"]   = "exit_px"
    if "n_bars"       in df.columns and "bars_held" not in df.columns:  rename["n_bars"]       = "bars_held"
    df = df.rename(columns=rename)

    # Ensure required columns exist with correct dtypes
    for col in ("entry_ts","exit_ts"):
        if col not in df.columns:
            df[col] = pd.NaT
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    for col in ("entry_px","exit_px"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "side" in df.columns:
        df["side"] = (
            df["side"]
            .astype(str).str.lower()
            .map({"long":"long","short":"short","1":"long","-1":"short"})
            .fillna("long")
        )
    else:
        df["side"] = "long"

    if "bars_held" not in df.columns:
        df["bars_held"] = 0
    else:
        df["bars_held"] = pd.to_numeric(df["bars_held"], errors="coerce").fillna(0).astype(int)

    if "net_factor" not in df.columns:
        # If returns exist in pct terms, convert; else leave NaN (your equity code may recompute anyway)
        if "ret" in df.columns:
            df["net_factor"] = 1.0 + pd.to_numeric(df["ret"], errors="coerce")
        else:
            df["net_factor"] = np.nan

    if "reason" not in df.columns:
        df["reason"] = ""

    # It’s fine to keep open trades (NaT exit_ts); but if your equity/table code dislikes them, drop them:
    # df = df.dropna(subset=["exit_ts","exit_px"])

    return df[["side","entry_ts","entry_px","exit_ts","exit_px","bars_held","net_factor","reason"]].sort_values(
        ["entry_ts","exit_ts"], na_position="last"
    ).reset_index(drop=True)

# --- Kalman (Pine-like) on-the-fly ------------------------------------------

def _kalman_filter_series(close: pd.Series, length: int, R: float = 0.01, Q: float = 0.1) -> pd.Series:
    """Single-state 1D Kalman filter like the Pine snippet (no trend term)."""
    x = pd.to_numeric(close, errors="coerce").to_numpy(dtype="float64")
    n = len(x)
    est = np.empty(n, dtype="float64"); est[:] = np.nan
    err = 1.0
    err_meas = R * max(1, int(length))
    for i in range(n):
        xi = x[i]
        if np.isnan(xi):
            est[i] = est[i-1] if i else np.nan
            continue
        if i == 0 or np.isnan(est[i-1]):
            # Pine uses close[1] seed; we approximate by seeding with current close on first valid.
            est[i] = xi
            continue
        gain = err / (err + err_meas)
        est[i] = est[i-1] + gain * (xi - est[i-1])
        err = (1.0 - gain) * err + Q / max(1, int(length))
    return pd.Series(est, index=close.index)

def attach_kalman_cols(view: pd.DataFrame, *, short_len: int = 50, long_len: int = 150,
                       slope_ema: int = 5, extra_smooth: int = 12) -> pd.DataFrame:
    """Append Kalman levels, smoothed slopes, and buy/sell cross flags to `view`."""
    v = view.copy()
    # ensure numeric, sorted
    v = v.sort_values("ts") if "ts" in v.columns else v.sort_index()
    for c in ("open","high","low","close"):
        if c in v.columns:
            v[c] = pd.to_numeric(v[c], errors="coerce")

    k_short = _kalman_filter_series(v["close"], short_len)
    k_long  = _kalman_filter_series(v["close"], long_len)

    s_raw = k_short - k_short.shift(1)
    l_raw = k_long  - k_long.shift(1)

    def _ema(s, n):
        return pd.to_numeric(s, errors="coerce").ewm(span=max(1, int(n)), adjust=False).mean()

    s_ema = _ema(s_raw, slope_ema)
    l_ema = _ema(l_raw,  slope_ema)
    s_sm  = _ema(s_ema,  extra_smooth)
    l_sm  = _ema(l_ema,  extra_smooth)

    buy  = (s_sm.shift(1) <= l_sm.shift(1)) & (s_sm > l_sm)   # fast crosses up
    sell = (s_sm.shift(1) >= l_sm.shift(1)) & (s_sm < l_sm)   # fast crosses down

    v["kal_s"]        = k_short
    v["kal_l"]        = k_long
    v["kal_slope_s"]  = s_sm
    v["kal_slope_l"]  = l_sm
    v["kal_buy"]      = buy.fillna(False).astype(bool)
    v["kal_sell"]     = sell.fillna(False).astype(bool)
    return v

def _ensure_ts_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure a tz-aware DatetimeIndex (UTC). If a 'ts' column exists, parse it and
    set it as the index. Otherwise validate the existing index.
    """
    if "ts" in df.columns:
        df = df.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).set_index("ts")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Need a 'ts' column or a DatetimeIndex")

    if df.index.tz is None:
        df = df.tz_localize("UTC")

    return df


def _attach_trade_stats(view: pd.DataFrame, trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the table columns exist for any engine:
      - pnl_pct, runup_pct, drawdown_pct, cum_pnl_pct
    Works with either {entry_px, exit_px} or {entry_price, exit_price}.
    Assumes trades_df has: entry_ts, exit_ts, side, net_factor.
    """
    # If empty, just add the columns so the table renders
    if trades_df is None or trades_df.empty:
        trades_df = (trades_df if isinstance(trades_df, pd.DataFrame) else pd.DataFrame()).copy()
        for c in ["pnl_pct","runup_pct","drawdown_pct","cum_pnl_pct"]:
            trades_df[c] = []
        return trades_df

    v = view.copy()
    # Ensure UTC DatetimeIndex for slicing
    if "ts" in v.columns:
        v["ts"] = pd.to_datetime(v["ts"], utc=True, errors="coerce")
        v = v.dropna(subset=["ts"]).set_index("ts").sort_index()
    if not isinstance(v.index, pd.DatetimeIndex):
        raise ValueError("view must have 'ts' or a DatetimeIndex")

    # Normalize price column names
    entry_col = "entry_px" if "entry_px" in trades_df.columns else "entry_price"
    exit_col  = "exit_px"  if "exit_px"  in trades_df.columns else "exit_price"
    if entry_col not in trades_df.columns or exit_col not in trades_df.columns:
        raise KeyError("Trades frame must include entry_px/exit_px (or entry_price/exit_price).")

    # Base P&L in percent from net_factor (already fee-adjusted in your builder)
    pnl_frac = trades_df["net_factor"].astype(float) - 1.0
    trades_df = trades_df.copy()
    trades_df["pnl_pct"] = pnl_frac * 100.0

    # Infer bar indices for MFE/MAE if missing
    if "entry_idx" not in trades_df.columns or "exit_idx" not in trades_df.columns:
        idxer = pd.Index(v.index)
        trades_df["entry_idx"] = idxer.get_indexer(pd.to_datetime(trades_df["entry_ts"], utc=True), method="nearest")
        trades_df["exit_idx"]  = idxer.get_indexer(pd.to_datetime(trades_df["exit_ts"],  utc=True), method="nearest")

    highs = v["high"].to_numpy() if "high" in v.columns else v["close"].to_numpy()
    lows  = v["low"].to_numpy()  if "low"  in v.columns else v["close"].to_numpy()

    runups, drawdns = [], []
    for entry_i, exit_i, side, entry_px in zip(
        trades_df["entry_idx"].to_numpy(),
        trades_df["exit_idx"].to_numpy(),
        trades_df["side"].to_numpy(),
        trades_df[entry_col].to_numpy(),
    ):
        i0 = int(min(entry_i, exit_i)); i1 = int(max(entry_i, exit_i))
        h_slice = highs[i0:i1+1]; l_slice = lows[i0:i1+1]
        if side == "long":
            mfe = (np.max(h_slice) / entry_px) - 1.0
            mae = (np.min(l_slice) / entry_px) - 1.0
        else:
            mfe = (entry_px / np.min(l_slice)) - 1.0
            mae = (entry_px / np.max(h_slice)) - 1.0
        runups.append(mfe * 100.0); drawdns.append(mae * 100.0)

    trades_df["runup_pct"]    = pd.Series(runups, index=trades_df.index).astype(float)
    trades_df["drawdown_pct"] = pd.Series(drawdns, index=trades_df.index).astype(float)

    # Compounded cumulative (%)
    trades_df["cum_pnl_pct"] = ((1.0 + pnl_frac).cumprod() - 1.0) * 100.0
    return trades_df

