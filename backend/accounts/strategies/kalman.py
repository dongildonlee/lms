# backend/accounts/strategies/kalman.py
from __future__ import annotations
import numpy as np
import pandas as pd
from .common import cum_from_returns, _ensure_ts_index

# paste _kalman_filter_series(...)  here
# paste attach_kalman_cols(...)     here
# paste build_trades_from_masks(...) here

def kalman_long(view: pd.DataFrame, fee: float):
    v = attach_kalman_cols(view)
    long_mask  = v["kal_slope_s"] > v["kal_slope_l"]
    short_mask = v["kal_slope_s"] < v["kal_slope_l"]
    return build_trades_from_masks(v, long_mask, short_mask, mode="long",  fee=fee)

def kalman_short(view: pd.DataFrame, fee: float):
    v = attach_kalman_cols(view)
    long_mask  = v["kal_slope_s"] > v["kal_slope_l"]
    short_mask = v["kal_slope_s"] < v["kal_slope_l"]
    return build_trades_from_masks(v, long_mask, short_mask, mode="short", fee=fee)

def kalman_cross(view: pd.DataFrame, fee: float):
    v = attach_kalman_cols(view)
    long_mask  = v["kal_slope_s"] > v["kal_slope_l"]
    short_mask = v["kal_slope_s"] < v["kal_slope_l"]
    return build_trades_from_masks(v, long_mask, short_mask, mode="both",  fee=fee)

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

# def attach_kalman_cols(view: pd.DataFrame, *, short_len: int = 50, long_len: int = 150,
#                        slope_ema: int = 5, extra_smooth: int = 12) -> pd.DataFrame:
#     """Append Kalman levels, smoothed slopes, and buy/sell cross flags to `view`."""
#     v = view.copy()
#     # ensure numeric, sorted
#     v = v.sort_values("ts") if "ts" in v.columns else v.sort_index()
#     for c in ("open","high","low","close"):
#         if c in v.columns:
#             v[c] = pd.to_numeric(v[c], errors="coerce")

#     k_short = _kalman_filter_series(v["close"], short_len)
#     k_long  = _kalman_filter_series(v["close"], long_len)

#     s_raw = k_short - k_short.shift(1)
#     l_raw = k_long  - k_long.shift(1)

#     def _ema(s, n):
#         return pd.to_numeric(s, errors="coerce").ewm(span=max(1, int(n)), adjust=False).mean()

#     s_ema = _ema(s_raw, slope_ema)
#     l_ema = _ema(l_raw,  slope_ema)
#     s_sm  = _ema(s_ema,  extra_smooth)
#     l_sm  = _ema(l_ema,  extra_smooth)

#     buy  = (s_sm.shift(1) <= l_sm.shift(1)) & (s_sm > l_sm)   # fast crosses up
#     sell = (s_sm.shift(1) >= l_sm.shift(1)) & (s_sm < l_sm)   # fast crosses down

#     v["kal_s"]        = k_short
#     v["kal_l"]        = k_long
#     v["kal_slope_s"]  = s_sm
#     v["kal_slope_l"]  = l_sm
#     v["kal_buy"]      = buy.fillna(False).astype(bool)
#     v["kal_sell"]     = sell.fillna(False).astype(bool)
#     return v


# ---- TradingView-style EMA (ta.ema) -----------------------------------------
def _ema_tv(x: pd.Series | np.ndarray, length: int) -> pd.Series:
    """
    TradingView ta.ema with alpha = 2/(length+1), causal.
    If NaNs exist, we treat them as gaps (skip-update); seed with first non-nan.
    """
    s = pd.Series(x, copy=False).astype(float)
    alpha = 2.0 / (length + 1.0)
    out = np.empty(len(s), dtype=float)
    out[:] = np.nan

    # seed
    idx = int(np.where(~np.isnan(s.to_numpy()))[0][0]) if s.notna().any() else None
    if idx is None:
        return pd.Series(out, index=s.index)
    out[idx] = s.iloc[idx]

    # iterate
    for i in range(idx + 1, len(s)):
        xi = s.iloc[i]
        prev = out[i - 1]
        if np.isnan(xi):
            out[i] = prev
        else:
            out[i] = prev + alpha * (xi - prev)

    return pd.Series(out, index=s.index)

# ---- Pine-style scalar Kalman filter ----------------------------------------
def _kalman_filter_tv(src: pd.Series, length: int, R: float = 0.01, Q: float = 0.1) -> pd.Series:
    """
    Pine-like kalman_filter(close, length, R, Q):
      var float e=na, var float pe=1.0, var float em=R*length, var float kg=0.0, var float pred=na
      e := na(e) ? src[1] : e
      pred := e
      kg := pe/(pe+em)
      e := pred + kg*(src - pred)
      pe := (1-kg)*pe + Q/length
      e

    Vectorized with a loop; we seed e with the first value of src (closest to src[1] on bar 0).
    """
    s = pd.Series(src, copy=False).astype(float)
    n = len(s)
    if n == 0:
        return s

    e = np.empty(n, dtype=float)
    e[:] = np.nan
    pe = 1.0
    em = R * float(length)

    # seed e with first available value (Pine bar0 uses src[1] which is NaN; this is the practical seed)
    first_idx = int(np.where(~np.isnan(s.to_numpy()))[0][0]) if s.notna().any() else None
    if first_idx is None:
        return pd.Series(e, index=s.index)
    e_val = s.iloc[first_idx]

    for i in range(first_idx, n):
        pred = e_val
        kg = pe / (pe + em)
        xi = s.iloc[i]
        if np.isnan(xi):
            # keep previous estimate if price is NaN
            e_val = pred
        else:
            e_val = pred + kg * (xi - pred)
        pe = (1.0 - kg) * pe + Q / float(length)
        e[i] = e_val

    return pd.Series(e, index=s.index)


# ---- Public: attach Kalman cols exactly like the Pine snippet ----------------
def attach_kalman_cols(
    view: pd.DataFrame,
    *,
    close_col: str = "close",
    kf_short_len: int = 50,
    kf_long_len: int = 150,
    ema_slope_len: int = 5,
    slope_smooth_len: int = 12,
    R: float = 0.01,
    Q: float = 0.1,
    scale: float = 10000.0,
) -> pd.DataFrame:
    """
    Adds the following columns to a copy of `view`, matching your Pine defaults:

      short_kf      = kalman_filter(close,  kf_short_len, R, Q)
      long_kf       = kalman_filter(close,  kf_long_len,  R, Q)
      short_slope   = ema( short_kf.diff(), ema_slope_len) * scale
      long_slope    = ema(  long_kf.diff(), ema_slope_len) * scale
      kal_slope_s   = ema( short_slope,     slope_smooth_len)
      kal_slope_l   = ema(  long_slope,     slope_smooth_len)

    These two columns are what downstream code (signals/trades) should compare:
      - is_downtrend = kal_slope_s < kal_slope_l
      - is_uptrend   = kal_slope_s >= kal_slope_l
    """
    v = view.copy()
    if close_col not in v.columns:
        raise ValueError(f"attach_kalman_cols: missing '{close_col}' in view")

    close = pd.Series(v[close_col], copy=False).astype(float)

    # Pine-like Kalman filters
    v["short_kf"] = _kalman_filter_tv(close, kf_short_len, R=R, Q=Q)
    v["long_kf"]  = _kalman_filter_tv(close, kf_long_len,  R=R, Q=Q)

    # Raw slopes (1st difference), then EMA smoothing and scale
    short_kf_slope_raw = v["short_kf"].diff()
    long_kf_slope_raw  = v["long_kf"].diff()

    short_kf_slope = _ema_tv(short_kf_slope_raw, ema_slope_len) * scale
    long_kf_slope  = _ema_tv(long_kf_slope_raw,  ema_slope_len) * scale

    # Extra slope smoothing (EMA)
    v["kal_slope_s"] = _ema_tv(short_kf_slope, slope_smooth_len)
    v["kal_slope_l"] = _ema_tv(long_kf_slope,  slope_smooth_len)

    return v


def kalman_cross_masks(view: pd.DataFrame):
    """
    Return (v2, long_mask, short_mask) exactly as used by Kalman Cross.
    long when fast slope > slow slope; short when fast < slow.
    """
    v2 = attach_kalman_cols(view)
    long_mask  = (v2["kal_slope_s"] > v2["kal_slope_l"]).fillna(False)
    short_mask = (v2["kal_slope_s"] < v2["kal_slope_l"]).fillna(False)
    return v2, long_mask, short_mask


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