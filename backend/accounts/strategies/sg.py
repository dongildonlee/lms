import numpy as np
import pandas as pd

# ---------- Savitzky–Golay core (no SciPy required) ----------
def _sg_coeffs(win: int, poly: int) -> np.ndarray:
    """
    Return convolution coefficients for a centered Savitzky–Golay smoother
    that estimates the constant term (y at the center).
    """
    if win % 2 != 1:
        raise ValueError("win must be odd")
    if poly >= win:
        raise ValueError("poly must be < win")

    half = win // 2
    x = np.arange(-half, half + 1, dtype=float)    # [-h, ..., 0, ..., +h]
    # Vandermonde (win x (poly+1)), increasing powers [1, x, x^2, ...]
    X = np.vander(x, N=poly + 1, increasing=True)
    # Pseudoinverse gives mapping from window y-values -> polynomial coeffs
    # We want the constant term (row 0)
    B = np.linalg.pinv(X)                           # (poly+1 x win)
    return B[0, :]                                  # (win,)

def _sg_smooth(src: np.ndarray, win: int, poly: int) -> np.ndarray:
    """Centered Savitzky–Golay smoothing, reflect-padded at the edges."""
    if len(src) == 0:
        return np.array([], dtype=float)
    coeffs = _sg_coeffs(win, poly)
    h = win // 2
    padded = np.pad(src.astype(float), (h, h), mode="reflect")
    out = np.empty_like(src, dtype=float)
    # Sliding dot product (valid part of padded conv)
    for i in range(len(src)):
        out[i] = np.dot(coeffs, padded[i:i+win])
    return out

def _zscore(x: np.ndarray, ema_span: int = 30) -> np.ndarray:
    """z = (x - EMA(x, span)) / rolling_std(x, window=span)."""
    s = pd.Series(x)
    mean = s.ewm(span=ema_span, adjust=False, min_periods=1).mean()
    std  = s.rolling(ema_span, min_periods=max(2, ema_span//3)).std()
    z = (s - mean) / std.replace(0, np.nan)
    return z.to_numpy()

# ---------- Pivot helpers (confirm at pivot + lbR) ----------
def _pivot_low(vals: np.ndarray, lbL: int, lbR: int) -> np.ndarray:
    """
    Boolean at the *pivot index* (not confirmation),
    True when vals[i] is the minimum over [i-lbL, i+lbR].
    """
    n = len(vals)
    out = np.zeros(n, dtype=bool)
    if n == 0: 
        return out
    for i in range(lbL, n - lbR):
        win = vals[i-lbL:i+lbR+1]
        v = vals[i]
        if np.isfinite(v) and np.nanargmin(win) == lbL:
            # optional strictness:
            # if v <= np.nanmin(win):
            out[i] = True
    return out

def _pivot_high(vals: np.ndarray, lbL: int, lbR: int) -> np.ndarray:
    n = len(vals)
    out = np.zeros(n, dtype=bool)
    if n == 0: 
        return out
    for i in range(lbL, n - lbR):
        win = vals[i-lbL:i+lbR+1]
        v = vals[i]
        if np.isfinite(v) and np.nanargmax(win) == lbL:
            out[i] = True
    return out

# ---------- Public API ----------
def sg_indicators_bool(
    df: pd.DataFrame,
    win: int = 5,
    poly: int = 2,
    z_span: int = 30,
    lbL: int = 10,
    lbR: int = 10,
    source: str = "hlc3",   # "close", "hlc3", etc.
) -> pd.DataFrame:
    """
    Replicates the Pine SG Z-score bar-highlights (no look-ahead) and
    the divergence H/R tags (confirmed only), returning boolean columns:

      - SG_Long        (z > 0)
      - SG_Short       (z < 0)
      - SG_ROC_Up      (Δz > 0)
      - SG_ROC_Down    (Δz < 0)
      - SG_Div_RegBull (confirmed regular bullish divergence)
      - SG_Div_HidBull (confirmed hidden   bullish divergence)
      - SG_Div_RegBear (confirmed regular  bearish divergence)
      - SG_Div_HidBear (confirmed hidden   bearish divergence)

    Notes:
      * SG_* bar booleans are computed on the bar close → no look-ahead.
      * Divergences are marked True at the **confirmation bar** (pivot + lbR).
    """
    need = {"high","low","close"}
    missing = need - set(map(str.lower, df.columns))
    # try to map common names
    cols = {c.lower(): c for c in df.columns}
    if missing:
        raise KeyError(f"sg_indicators_bool: missing columns {sorted(missing)}; have {list(df.columns)}")

    hi = pd.to_numeric(df[cols["high"]], errors="coerce").to_numpy()
    lo = pd.to_numeric(df[cols["low"]],  errors="coerce").to_numpy()
    cl = pd.to_numeric(df[cols["close"]],errors="coerce").to_numpy()

    if source.lower() == "hlc3":
        src = (hi + lo + cl) / 3.0
    elif source.lower() == "close":
        src = cl
    else:
        # fallback to close if unrecognized
        src = cl

    n = len(cl)

    # --- SG z-score stream (no look-ahead) ---
    sg = _sg_smooth(src, win=win, poly=poly)
    z  = _zscore(sg, ema_span=z_span)

    # bar highlights (bools)
    sg_long     = np.isfinite(z) & (z > 0)
    sg_short    = np.isfinite(z) & (z < 0)
    dz          = np.diff(z, prepend=np.nan)
    sg_roc_up   = np.isfinite(dz) & (dz > 0)
    sg_roc_down = np.isfinite(dz) & (dz < 0)

    # --- Divergences (confirmed only) ---
    # pivot detection on z-score series
    pl = _pivot_low(z,  lbL=lbL, lbR=lbR)   # True at pivot index i (swing low)
    ph = _pivot_high(z, lbL=lbL, lbR=lbR)   # True at pivot index i (swing high)

    reg_bull = np.zeros(n, dtype=bool)
    hid_bull = np.zeros(n, dtype=bool)
    reg_bear = np.zeros(n, dtype=bool)
    hid_bear = np.zeros(n, dtype=bool)

    # process lows (bullish divergences)
    pl_idx = np.flatnonzero(pl)
    for k in range(1, len(pl_idx)):
        i_prev = int(pl_idx[k-1])
        i_cur  = int(pl_idx[k])
        confirm = i_cur + lbR
        if confirm >= n:
            break

        # Oscillator & price comparisons at *pivot indices*
        oscHL = z[i_cur] > z[i_prev]                 # higher low in z
        oscLL = z[i_cur] < z[i_prev]                 # lower  low in z
        priceLL = lo[i_cur] < lo[i_prev]            # lower  low in price
        priceHL = lo[i_cur] > lo[i_prev]            # higher low in price

        # Regular Bullish: price LL & osc HL
        if priceLL and oscHL:
            reg_bull[confirm] = True
        # Hidden Bullish: price HL & osc LL
        if priceHL and oscLL:
            hid_bull[confirm] = True

    # process highs (bearish divergences)
    ph_idx = np.flatnonzero(ph)
    for k in range(1, len(ph_idx)):
        i_prev = int(ph_idx[k-1])
        i_cur  = int(ph_idx[k])
        confirm = i_cur + lbR
        if confirm >= n:
            break

        oscLH = z[i_cur] < z[i_prev]                 # lower high in z
        oscHH = z[i_cur] > z[i_prev]                 # higher high in z
        priceHH = hi[i_cur] > hi[i_prev]            # higher high in price
        priceLH = hi[i_cur] < hi[i_prev]            # lower  high in price

        # Regular Bearish: price HH & osc LH
        if priceHH and oscLH:
            reg_bear[confirm] = True
        # Hidden Bearish: price LH & osc HH
        if priceLH and oscHH:
            hid_bear[confirm] = True

    # assemble output (booleans)
    out = pd.DataFrame(index=df.index)
    out["SG_Long"]         = sg_long
    out["SG_Short"]        = sg_short
    out["SG_ROC_Up"]       = sg_roc_up
    out["SG_ROC_Down"]     = sg_roc_down
    out["SG_Div_RegBull"]  = reg_bull
    out["SG_Div_HidBull"]  = hid_bull
    out["SG_Div_RegBear"]  = reg_bear
    out["SG_Div_HidBear"]  = hid_bear
    return out
