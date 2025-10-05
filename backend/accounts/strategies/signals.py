# backend/accounts/strategies/signals.py
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional
from .kalman import kalman_cross_masks, attach_kalman_cols
from .lorentzian import lorentzian_positions_advta

def isKalmanUptrend(view: pd.DataFrame) -> pd.Series:
    """
    Return a boolean Series (per-bar CLOSE) where True means Kalman uptrend.

    This is a thin wrapper over your existing Kalman Cross logic:
      - True  when fast Kalman slope > slow Kalman slope
      - False when fast Kalman slope < slow Kalman slope
      - NaNs (e.g., at warmup) are treated as False

    NOTE:
      - No resampling here. Pass in the DataFrame at the timeframe you want
        (e.g., your 4h v2/v4), and this will align 1:1 with your trade logic.
      - No shifting here. Entry timing (next bar OPEN) is handled by trade builder.
    """
    try:
        # Preferred path: use the same masks the trade builder uses
        v2, long_mask, short_mask = kalman_cross_masks(view)
        up = long_mask
    except Exception:
        # Fallback if kalman_cross_masks isn't available: compute slopes then compare
        v2 = attach_kalman_cols(view)
        up = (v2["kal_slope_s"] > v2["kal_slope_l"])

    return up.fillna(False).rename("is_uptrend").astype(bool)


# # ---------- Common engine: run segmentation + swing comparison ----------

# def _run_starts_ends(state: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
#     """
#     Turn a boolean state Series (per-bar CLOSE) into contiguous runs.
#     Returns (starts_idx, ends_idx, is_up_per_run).
#     starts/ends are integer *positions* (iloc).
#     The last run is considered 'ongoing' unless another run follows.
#     """
#     s = state.astype(bool).to_numpy()
#     n = s.size
#     if n == 0:
#         return np.array([], dtype=int), np.array([], dtype=int), np.array([], dtype=bool)

#     # change points where state flips
#     changes = np.flatnonzero(s[1:] != s[:-1]) + 1
#     starts = np.r_[0, changes]
#     ends   = np.r_[changes - 1, n - 1]
#     is_up  = s[starts]
#     return starts, ends, is_up


# def _swing_from_runs(
#     view: pd.DataFrame,
#     state_up: pd.Series,
#     *,
#     close_col: str,
#     kind: str,          # "HH" or "HL"
#     strict: bool,
#     name: str,
# ) -> pd.Series:
#     """
#     Generic swing signal:
#       - For HH: compare max(CLOSE) of last two *completed UP* runs, fire at the bar
#         where the most-recent UP run completes (i.e., the up->down flip bar).
#       - For HL: compare min(CLOSE) of last two *completed DOWN* runs, fire at the bar
#         where the most-recent DOWN run completes (i.e., the down->up flip bar).
#     """
#     state_up = state_up.astype(bool)
#     closes = view[close_col].astype(float).reset_index(drop=True)
#     out = pd.Series(False, index=state_up.index, name=name)

#     starts, ends, is_up_run = _run_starts_ends(state_up)
#     m = len(starts)
#     if m <= 1:
#         return out  # nothing concluded yet

#     # We only consider *completed* runs => all runs except the very last one
#     # because a run completes when the *next* run starts.
#     LAST_COMPLETED = m - 2  # index of last completed run (before the ongoing final run)

#     prev_up_high: Optional[float] = None
#     prev_dn_low:  Optional[float] = None

#     for i in range(0, LAST_COMPLETED + 1):
#         s_i, e_i = starts[i], ends[i]

#         if kind == "HH":
#             # fire when an UP run completes i.e. next run exists and is DOWN
#             if not is_up_run[i] or is_up_run[i + 1]:
#                 continue
#             cur_high = float(closes.iloc[s_i:e_i + 1].max())
#             if prev_up_high is not None:
#                 ok = cur_high > prev_up_high if strict else cur_high >= prev_up_high
#                 if ok:
#                     # Signal at the flip bar (the first bar of the next DOWN run),
#                     # which is the bar *after* e_i; but our state is sampled at CLOSE,
#                     # and the flip is recorded at the next bar's close index (e_i+1).
#                     # However, per our state definition, the *flip bar* (where up->down)
#                     # is exactly index e_i+1, and the UP run *completed* at index e_i.
#                     # We want to flag the flip bar (consistent with your spec),
#                     # which is e_i + 1, but ensure bounds:
#                     flip_pos = min(e_i + 1, len(out) - 1)
#                     out.iloc[flip_pos] = True
#             # update previous after evaluating
#             prev_up_high = cur_high

#         else:  # "HL"
#             # fire when a DOWN run completes i.e. next run exists and is UP
#             if is_up_run[i] or not is_up_run[i + 1]:
#                 continue
#             cur_low = float(closes.iloc[s_i:e_i + 1].min())
#             if prev_dn_low is not None:
#                 ok = cur_low > prev_dn_low if strict else cur_low >= prev_dn_low
#                 if ok:
#                     # flip bar for down->up is the first bar of the next UP run: e_i+1
#                     flip_pos = min(e_i + 1, len(out) - 1)
#                     out.iloc[flip_pos] = True
#             prev_dn_low = cur_low

#     return out



def is_hh_hl(df):
    # your original lines
    is_up = isKalmanUptrend(df)

    a = is_up.to_numpy(dtype=bool)

    # True → False
    tf_down_idx = np.where(a[:-1] & ~a[1:])[0] + 1

    # False → True
    ft_up_idx   = np.where(~a[:-1] &  a[1:])[0] + 1

    dn_idx_shift=0
    up_idx_shift=0

    k = min(len(tf_down_idx), len(ft_up_idx)) 
    if tf_down_idx[-1] < ft_up_idx[-1]:
        dt = [np.arange(d, u) for d, u in zip(tf_down_idx[-k:][::-1], ft_up_idx[-k:][::-1]) if u >= d]
        ut = [np.arange(u, d) for d, u in zip(tf_down_idx[-k:][::-1], ft_up_idx[-k-1:-1][::-1]) if d >= u]
        last_ut = np.arange(ft_up_idx[-1],is_up.index[-1]+1)
        # print(last_ut)
        ut.insert(0,last_ut)
        up_idx_shift+=1

    elif tf_down_idx[-1] > ft_up_idx[-1]:
        ut = [np.arange(u, d) for u, d in zip(ft_up_idx[-k:][::-1], tf_down_idx[-k:][::-1]) if d >= u]
        dt = [np.arange(d, u) for u, d in zip(ft_up_idx[-k:][::-1], tf_down_idx[-k-1:-1][::-1]) if u >= d]
        last_dt = np.arange(tf_down_idx[-1],is_up.index[-1]+1)
        dt.insert(0,last_dt)
        dn_idx_shift+=1

    isHL = np.zeros(len(is_up))
    isHH = np.zeros(len(is_up))

    for i in range(1, np.min([len(dt), len(ut)]) - 1):
        
        if np.min(df.iloc[dt[i]]["close"]) > np.min(df.iloc[dt[i+1]]["close"]):
            isHL[dt[i-1]] = 1
            isHL[ut[i-1+up_idx_shift]] = 1
            
        if np.max(df.iloc[ut[i]]["close"]) > np.max(df.iloc[ut[i+1]]["close"]):
            isHH[ut[i-1]] = 1
            isHH[dt[i-1+dn_idx_shift]] = 1

    return isHH, isHL



def isKalmanBuy(df: pd.DataFrame, return_series: bool = False):
    """
    1 on bars where fast Kalman slope crosses ABOVE slow slope (enter long), else 0.
    """
    v = attach_kalman_cols(df)  # adds kal_slope_s, kal_slope_l
    lm = (v["kal_slope_s"] > v["kal_slope_l"])
    edge = (lm & ~lm.shift(1, fill_value=False)).astype(np.uint8)
    return edge if return_series else edge.to_numpy()


def isKalmanSell(df: pd.DataFrame, return_series: bool = False):
    """
    1 on bars where fast Kalman slope crosses BELOW slow slope (enter short), else 0.
    """
    v = attach_kalman_cols(df)
    sm = (v["kal_slope_s"] < v["kal_slope_l"])
    edge = (sm & ~sm.shift(1, fill_value=False)).astype(np.uint8)
    return edge if return_series else edge.to_numpy()


# optional: for default/validation of settings + source coercion
try:
    from advanced_ta.LorentzianClassification.Classifier import LorentzianClassification as LC
except Exception:
    LC = None

def _ensure_lc_settings(df: pd.DataFrame, settings=None, filterSettings=None):
    if LC is None:
        return settings, filterSettings
    if settings is None:
        src = df["close"] if "close" in df.columns else df.select_dtypes(include=[np.number]).iloc[:, -1]
        settings = LC.Settings(source=src, neighborsCount=8, maxBarsBack=len(df), useDynamicExits=False)
    else:
        src_attr = getattr(settings, "source", None)
        if isinstance(src_attr, str):
            key = src_attr.lower()
            if key == "ohlc4":
                settings.source = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
            else:
                settings.source = df[key]
    if filterSettings is None:
        filterSettings = LC.FilterSettings()
    return settings, filterSettings

def isLorentzianBuy(df: pd.DataFrame, *, features=None, settings=None, filterSettings=None, return_series: bool=False):
    settings, filterSettings = _ensure_lc_settings(df, settings, filterSettings)
    pos = lorentzian_positions_advta(df, features=features, settings=settings, filterSettings=filterSettings)
    mask = ((pos == 1) & (pos.shift(1, fill_value=0) != 1)).astype(np.uint8)  # exact BUY-print bar only
    return mask if return_series else mask.to_numpy()

def isLorentzianSell(df: pd.DataFrame, *, features=None, settings=None, filterSettings=None, return_series: bool=False):
    settings, filterSettings = _ensure_lc_settings(df, settings, filterSettings)
    pos = lorentzian_positions_advta(df, features=features, settings=settings, filterSettings=filterSettings)
    mask = ((pos == -1) & (pos.shift(1, fill_value=0) != -1)).astype(np.uint8)  # exact SELL-print bar only
    return mask if return_series else mask.to_numpy()

import numpy as np
import pandas as pd

def isKalman_regression_down_break(df: pd.DataFrame, scope: str = "any_bar") -> np.ndarray:
    """
    0/1 mask for breaking above the 'regression downtrend' line formed by
    monotonically decreasing peaks (max close) across *concluded* Kalman uptrends.

    scope:
      - "any_bar"      → label every bar after the current peak up to the next peak if close > line
      - "uptrend_only" → label only bars inside the next Kalman uptrend if close > line
    """
    assert "close" in df.columns, "df must have a 'close' column"
    close = pd.to_numeric(df["close"], errors="coerce")
    n = len(df)
    if n == 0:
        return np.zeros(0, dtype=np.uint8)

    # 1) Kalman state
    is_up = isKalmanUptrend(df).astype(bool)
    a = is_up.to_numpy(dtype=bool)

    # 2) Uptrend boundaries
    ft_up_idx   = np.where(~a[:-1] &  a[1:])[0] + 1  # False→True starts
    tf_down_idx = np.where( a[:-1] & ~a[1:])[0] + 1  # True→False ends

    # Pair starts/ends to concluded uptrends [start, end)
    starts, ends = [], []
    s_i = d_i = 0
    while s_i < len(ft_up_idx) and d_i < len(tf_down_idx):
        s = ft_up_idx[s_i]; d = tf_down_idx[d_i]
        if s < d:
            starts.append(s); ends.append(d)
            s_i += 1; d_i += 1
        else:
            d_i += 1
    ut_concluded = [np.arange(s, e) for s, e in zip(starts, ends) if e > s]

    # Active uptrend at the tail (optional)
    ut_active = None
    if len(ft_up_idx) > len(tf_down_idx) and (len(tf_down_idx) == 0 or ft_up_idx[-1] > tf_down_idx[-1]):
        ut_active = np.arange(ft_up_idx[-1], n)

    # 3) Peaks (max close) of each concluded uptrend
    peaks = []
    for seg in ut_concluded:
        if len(seg) == 0: continue
        seg_close = close.iloc[seg].to_numpy()
        peak_offset = int(np.argmax(seg_close))
        peak_idx = int(seg[peak_offset])
        peaks.append((peak_idx, float(close.iat[peak_idx])))

    out = np.zeros(n, dtype=np.uint8)
    if len(peaks) < 2:
        return out

    def mark_segment(seg_indices: np.ndarray, m: float, b: float):
        if seg_indices is None or len(seg_indices) == 0:
            return
        x = seg_indices.astype(float)
        y_pred = m * x + b
        y = close.iloc[seg_indices].to_numpy(dtype=float)
        out[seg_indices[y > y_pred]] = 1  # ← state-like: every bar above line prints 1

    # 4) Track runs of strictly decreasing peaks; update regression with all points in the run
    run_start = None
    for i in range(1, len(peaks)):
        prev_idx, prev_px = peaks[i-1]
        curr_idx, curr_px = peaks[i]
        if curr_px < prev_px:
            if run_start is None:
                run_start = i - 1  # include previous peak to start the run

            # Fit using all peaks in current decreasing run
            xs = np.array([peaks[k][0] for k in range(run_start, i + 1)], dtype=float)
            ys = np.array([peaks[k][1] for k in range(run_start, i + 1)], dtype=float)
            m, b = np.polyfit(xs, ys, 1)

            if scope == "uptrend_only":
                # only the next concluded uptrend (or active tail)
                seg = ut_concluded[i + 1] if (i + 1) < len(ut_concluded) else ut_active
                mark_segment(seg, m, b)
            else:
                # ANY BAR from current peak until the next peak (or end of series)
                end_i = peaks[i + 1][0] if (i + 1) < len(peaks) else (n - 1)
                if end_i > curr_idx:
                    seg = np.arange(curr_idx + 1, end_i + 1)
                    mark_segment(seg, m, b)
        else:
            # decreasing sequence broken → reset run
            run_start = None

    return out