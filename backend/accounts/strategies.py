# backend/accounts/strategies.py
from __future__ import annotations
import pandas as pd
import numpy as np


def _ensure_cols(view: pd.DataFrame):
    req = {"ts", "open", "high", "low", "close"}
    missing = req - set(view.columns)
    if missing:
        raise ValueError(f"view is missing columns: {missing}")
    for span in (20, 50, 100):
        col = f"ema{span}"
        if col not in view.columns:
            raise ValueError(f"{col} missing — compute EMAs before calling strategy.")


def _cum_from_returns(ret: pd.Series) -> pd.Series:
    """Utility: turn bar returns into cumulative equity (fraction, not %)."""
    return (1.0 + ret.fillna(0.0)).cumprod() - 1.0




def _apply_fee_on_bars(ret: pd.Series, fee_mask: pd.Series, fee: float) -> pd.Series:
    if not fee or fee == 0.0:
        return ret
    out = ret.copy()
    # On fee bars: (1 + r) * (1 - fee) - 1
    idx = fee_mask[fee_mask].index
    out.loc[idx] = (1.0 + out.loc[idx]) * (1.0 - fee) - 1.0
    return out

def ema_stack_long(view: pd.DataFrame, *, fee_frac: float = 0.001) -> pd.DataFrame:
    _ensure_cols(view)
    df = view[["ts","close","ema20","ema50","ema100"]].copy()

    long_stack = (df.ema20 > df.ema50) & (df.ema50 > df.ema100)
    long_on  =  long_stack & ~long_stack.shift(1, fill_value=False)
    long_off = ~long_stack &  long_stack.shift(1, fill_value=False)

    asset_ret = df["close"].pct_change().fillna(0.0)
    strat_ret = asset_ret.where(long_stack, 0.0)

    # Apply fees multiplicatively on entry & exit bars only
    fee_bars = (long_on | long_off)
    ret = _apply_fee_on_bars(strat_ret, fee_bars, fee_frac)

    cum = _cum_from_returns(ret)
    return pd.DataFrame({"ts": df["ts"], "ret": ret, "cum": cum})

def ema_stack_short(view: pd.DataFrame, *, fee_frac: float = 0.001) -> pd.DataFrame:
    _ensure_cols(view)
    df = view[["ts","close","ema20","ema50","ema100"]].copy()

    short_stack = (df.ema20 < df.ema50) & (df.ema50 < df.ema100)
    short_on  =  short_stack & ~short_stack.shift(1, fill_value=False)
    short_off = ~short_stack &  short_stack.shift(1, fill_value=False)

    asset_ret = df["close"].pct_change().fillna(0.0)
    strat_ret = (-asset_ret).where(short_stack, 0.0)

    fee_bars = (short_on | short_off)
    ret = _apply_fee_on_bars(strat_ret, fee_bars, fee_frac)

    cum = _cum_from_returns(ret)
    return pd.DataFrame({"ts": df["ts"], "ret": ret, "cum": cum})


def ema_stack_long_short(view: pd.DataFrame) -> pd.DataFrame:
    """
    Long & Short (flip between them, flat otherwise; no overlap, no pyramiding):
      • Long when EMA20 > EMA50 > EMA100
      • Short when EMA20 < EMA50 < EMA100
      • Flat otherwise
    Returns: ts, ret, cum (fractions)
    """
    _ensure_cols(view)

    df = view[["ts", "close", "ema20", "ema50", "ema100"]].copy()
    long_stack  = (df["ema20"] > df["ema50"]) & (df["ema50"] > df["ema100"])
    short_stack = (df["ema20"] < df["ema50"]) & (df["ema50"] < df["ema100"])

    # position: +1 long, -1 short, 0 flat
    pos = pd.Series(0, index=df.index, dtype=int)
    pos = pos.mask(long_stack, 1).mask(short_stack, -1)

    asset_ret = df["close"].pct_change().fillna(0.0)
    strat_ret = asset_ret * pos
    cum = _cum_from_returns(strat_ret)

    return pd.DataFrame({"ts": df["ts"], "ret": strat_ret, "cum": cum})

# # --- Lorentzian Classification via advanced-ta ---
# def lorentzian_classification_lib(
#     view: pd.DataFrame,
#     *,
#     fee_frac: float = 0.001,
#     features=None,
#     settings=None,
#     filterSettings=None,
# ) -> pd.DataFrame:
#     """
#     Wrapper around advanced_ta.LorentzianClassification.

#     Inputs:
#       view: DataFrame with at least ['ts','open','high','low','close'] (+ optional 'volume')
#       fee_frac: per-entry/exit fee fraction (e.g., 0.001 = 0.1% per fill)
#       features/settings/filterSettings: passed directly to LC(...) if provided.

#     Output:
#       DataFrame: ['ts','ret','cum','pos']
#         - pos ∈ {-1, 0, 1} derived from LC's predicted signal
#         - ret, cum computed using your existing helpers and flip-fee model
#     """
#     try:
#         from advanced_ta import LorentzianClassification as LC
#     except Exception as e:
#         raise ImportError(
#             "advanced-ta not installed. Run: pip install advanced-ta"
#         ) from e

#     _ensure_cols(view)
#     df = view.copy()

#     # advanced-ta expects lowercase OHLCV column names
#     if "volume" not in df.columns:
#         df["volume"] = 0.0
#     df_in = df[["open", "high", "low", "close", "volume"]].rename(columns=str.lower).copy()

#     # Build the LC object (see PyPI usage) and try to access a result frame
#     # Docs show: lc = LorentzianClassification(df); lc.dump('out.csv'); lc.plot('out.jpg')
#     # We first try an in-memory attribute, else fall back to dump() to a temp CSV.
#     lc = LC(df_in, features=features, settings=settings, filterSettings=filterSettings)

#     out = None
#     for attr in ("df", "data", "result", "_df"):
#         cand = getattr(lc, attr, None)
#         if cand is not None:
#             out = cand
#             break
#     if out is None:
#         import tempfile, pandas as _pd
#         with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
#             tmp_path = tmp.name
#         try:
#             lc.dump(tmp_path)
#             out = _pd.read_csv(tmp_path)
#         finally:
#             try:
#                 import os as _os; _os.remove(tmp_path)
#             except Exception:
#                 pass

#     if not isinstance(out, pd.DataFrame):
#         raise RuntimeError("advanced-ta did not expose a DataFrame result; please update the package.")

#     # Try common signal columns -> position: {-1,0,1}
#     sig_col = None
#     for cand in ("signal", "prediction", "label", "y_pred", "pred"):
#         if cand in out.columns:
#             sig_col = cand
#             break
#     if sig_col is None:
#         raise RuntimeError("advanced-ta output missing signal column (expected one of: signal/prediction/label/y_pred/pred).")

#     pos = pd.Series(out[sig_col], index=df.index, dtype="float64").round().astype(int).clip(-1, 1)

#     # Compute trade returns with your existing helpers
#     asset_ret = df["close"].pct_change().fillna(0.0)
#     # Use previous bar's position for close-to-close PnL
#     strat_ret = asset_ret * pos.shift(1, fill_value=0)
#     fee_bars = pos.ne(pos.shift(1, fill_value=0))
#     ret = _apply_fee_on_bars(strat_ret, fee_bars, fee_frac)
#     cum = _cum_from_returns(ret)

#     return pd.DataFrame({"ts": df["ts"], "ret": ret, "cum": cum, "pos": pos})


# # --- Lorentzian Classification via advanced-ta (long/short positions from library) ---
# def lorentzian_classification_advta(
#     view: pd.DataFrame,
#     *,
#     fee_frac: float = 0.001,
#     features=None,
#     settings=None,
#     filterSettings=None,
# ) -> pd.DataFrame:
#     """
#     Wrapper around advanced_ta.LorentzianClassification that produces:
#       columns: ts, ret, cum, pos
#         • pos ∈ {-1,0,1} derived from LC's signal/prediction column
#         • ret uses close-to-close returns with fees applied on position flips
#         • cum is cumulative equity fraction using your existing compounding convention

#     Parameters
#     ----------
#     view : DataFrame with columns ['ts','open','high','low','close'] (and optionally 'volume')
#     fee_frac : float, per-entry/exit fee fraction (e.g., 0.001 = 0.1% each trade)
#     features, settings, filterSettings : passed through to LC(...)
#     """
#     try:
#         from advanced_ta import LorentzianClassification as LC
#     except Exception as e:
#         raise ImportError("advanced-ta not installed; pip install advanced-ta") from e

#     # Reuse your existing column checks
#     _ensure_cols(view)

#     # Prepare input as OHLCV (advanced-ta expects lower-case names)
#     df = view.copy()
#     if "volume" not in df.columns:
#         df["volume"] = 0.0
#     df_in = df[["open", "high", "low", "close", "volume"]].rename(columns=str.lower).copy()

#     # Run LC
#     lc = LC(df_in, features=features, settings=settings, filterSettings=filterSettings)

#     # Try to grab an in-memory DataFrame first; else, fall back to dump() -> read CSV
#     out = None
#     for attr in ("df", "data", "result", "_df"):
#         cand = getattr(lc, attr, None)
#         if isinstance(cand, pd.DataFrame):
#             out = cand
#             break

#     if out is None:
#         import tempfile, os
#         tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
#         tmp_path = tmp.name
#         tmp.close()
#         try:
#             lc.dump(tmp_path)
#             out = pd.read_csv(tmp_path)
#         finally:
#             try:
#                 os.remove(tmp_path)
#             except Exception:
#                 pass

#     if not isinstance(out, pd.DataFrame):
#         raise RuntimeError("advanced-ta did not expose tabular results; please update the package.")

#     # Map LC's signal to {-1,0,1}
#     sig_col = None
#     for name in ("signal", "prediction", "label", "y_pred", "pred"):
#         if name in out.columns:
#             sig_col = name
#             break
#     if sig_col is None:
#         raise RuntimeError("No signal column found in advanced-ta output (looked for: signal/prediction/label/y_pred/pred).")

#     # Align index/length with input df; be defensive about size
#     pos = pd.Series(0, index=df.index, dtype=int)
#     n = min(len(pos), len(out))
#     pos.iloc[:n] = pd.Series(out[sig_col].iloc[:n]).round().astype(int).clip(-1, 1).values

#     # Strategy returns: use previous bar's position; apply fees when position changes
#     asset_ret = df["close"].pct_change().fillna(0.0)
#     strat_ret = asset_ret * pos.shift(1, fill_value=0)
#     flip = pos.ne(pos.shift(1, fill_value=0))
#     ret = _apply_fee_on_bars(strat_ret, flip, fee_frac)
#     cum = _cum_from_returns(ret)

#     return pd.DataFrame({"ts": df["ts"], "ret": ret, "cum": cum, "pos": pos})


# # ---------- helpers ----------
# def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
#     df = df.copy()
#     if "ts" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
#         df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
#         df = df.dropna(subset=["ts"]).set_index("ts")
#     df = df.rename(columns=str.lower)
#     need = ["open", "high", "low", "close"]
#     missing = [c for c in need if c not in df.columns]
#     if missing:
#         raise ValueError(f"DataFrame missing columns: {missing}")
#     for c in need + (["volume"] if "volume" in df.columns else []):
#         df[c] = pd.to_numeric(df[c], errors="coerce")
#     df = df.dropna(subset=need).sort_index()
#     return df

# def _ema(s: pd.Series, length: int) -> pd.Series:
#     length = int(max(1, length))
#     return s.ewm(span=length, adjust=False, min_periods=1).mean()

# def _kalman_scalar(close: pd.Series, length: int, R: float = 0.01, Q: float = 0.1) -> pd.Series:
#     length = int(max(2, length))
#     est = np.empty(len(close), dtype="float64"); est[:] = np.nan
#     err = 1.0
#     err_meas = R * length
#     prev = np.nan
#     cvals = close.to_numpy(dtype="float64", copy=False)
#     for i, c in enumerate(cvals):
#         if np.isnan(prev):
#             prev = cvals[i-1] if i > 0 else c
#         prediction = prev
#         gain = err / (err + err_meas)
#         cur = prediction + gain * (c - prediction)
#         err = (1.0 - gain) * err + Q / length
#         est[i] = cur
#         prev = cur
#     return pd.Series(est, index=close.index)

# def _crossover(a: pd.Series, b: pd.Series) -> pd.Series:
#     return (a > b) & (a.shift(1) <= b.shift(1))

# def _crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
#     return (a < b) & (a.shift(1) >= b.shift(1))

# # ---------- indicator (signals) ----------
# def kalman_cross_signals(df: pd.DataFrame, short_len: int = 50, long_len: int = 150, slope_ema: int = 5, extra_smooth: int = 10) -> pd.DataFrame:
#     df = _ensure_ohlcv(df)
#     c = df["close"]
#     k_short = _kalman_scalar(c, short_len)
#     k_long  = _kalman_scalar(c, long_len)
#     s_slope = _ema(k_short - k_short.shift(1), slope_ema)
#     l_slope = _ema(k_long  - k_long.shift(1),  slope_ema)
#     s_slope_sm = _ema(s_slope, extra_smooth)
#     l_slope_sm = _ema(l_slope, extra_smooth)
#     buy  = _crossover(s_slope_sm, l_slope_sm)
#     sell = _crossunder(s_slope_sm, l_slope_sm)
#     out = df.copy()
#     out["kalman_short"] = k_short
#     out["kalman_long"]  = k_long
#     out["shortSlopeSm"] = s_slope_sm
#     out["longSlopeSm"]  = l_slope_sm
#     out["buy_sig"]      = buy.astype(bool)
#     out["sell_sig"]     = sell.astype(bool)
#     return out

# # ---------- backtest primitives ----------
# def _exit_long_by_stops(o, h, l, entry_price, sl_pct, tp_pct):
#     stop_price  = entry_price * (1.0 - sl_pct)
#     limit_price = entry_price * (1.0 + tp_pct) if tp_pct > 0 else np.nan
#     if l <= stop_price:
#         return True, stop_price, "stop"
#     if tp_pct > 0 and h >= limit_price:
#         return True, limit_price, "tp"
#     return False, np.nan, ""

# def _exit_short_by_stops(o, h, l, entry_price, sl_pct, tp_pct):
#     stop_price  = entry_price * (1.0 + sl_pct)
#     limit_price = entry_price * (1.0 - tp_pct) if tp_pct > 0 else np.nan
#     if h >= stop_price:
#         return True, stop_price, "stop"
#     if tp_pct > 0 and l <= limit_price:
#         return True, limit_price, "tp"
#     return False, np.nan, ""

# def _apply_fees_factor(fee_side: float) -> float:
#     return (1.0 - fee_side)

# def _append_trade(trades, side, ent_t, ent_p, ex_t, ex_p, bars, fee_side):
#     if side == "long":
#         gross = (ex_p / ent_p) - 1.0
#     else:
#         gross = (ent_p / ex_p) - 1.0
#     net_factor = _apply_fees_factor(fee_side) * (1.0 + gross) * _apply_fees_factor(fee_side)
#     pnl = net_factor - 1.0
#     trades.append({
#         "side": side,
#         "entry_time": ent_t,
#         "entry_price": float(ent_p),
#         "exit_time": ex_t,
#         "exit_price": float(ex_p),
#         "bars": int(bars),
#         "gross_return": float(gross),
#         "net_factor": float(net_factor),
#         "pnl": float(pnl),
#         "reason": "",
#     })


