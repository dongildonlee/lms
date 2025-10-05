import numpy as np
import pandas as pd

# your edge-only signals (already defined in your codebase)
# from .signals import isLorentzianBuy, isLorentzianSell, isKalmanBuy, isKalmanSell

# --- import helpers to standardize + enrich the trade table ---
try:
    # absolute import (works from notebooks/scripts)
    from backend.accounts.analysis_helpers import _normalize_trade_cols, _attach_trade_stats
except Exception:
    # sibling or package-relative fallbacks if needed
    from ..analysis_helpers import _normalize_trade_cols, _attach_trade_stats

def long_tester(
    df: pd.DataFrame,
    *,
    use_lorentzian_buy: bool = False,
    use_kalman_buy: bool = False,
    require_HH: bool = False,
    require_HL: bool = False,
    tolerance: int = 2,
    # exit rules
    exit_on_lorentzian_sell: bool | None = None,
    exit_on_kalman_sell: bool | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    max_hold_bars: int | None = None,
    # plumbing / overrides
    lb_func=None, ls_func=None, kb_func=None, ks_func=None,
    hh_col: str = "isHH", hl_col: str = "isHL",
    price_col: str = "close",
    return_masks: bool = True,
    hhhl_func=None,      # pass your is_hh_hl(df) if columns absent
    fee: float = 0.002,  # round-trip fee fraction (matches helpers’ convention)
):
    assert price_col in df.columns, f"'{price_col}' column required"
    px = pd.to_numeric(df[price_col], errors="coerce").to_numpy()
    n  = len(df)

    # lazy-load signals to avoid circular imports
    if lb_func is None or ls_func is None or kb_func is None or ks_func is None:
        from .signals import isLorentzianBuy as _lb, isLorentzianSell as _ls, isKalmanBuy as _kb, isKalmanSell as _ks
        lb_func = lb_func or _lb
        ls_func = ls_func or _ls
        kb_func = kb_func or _kb
        ks_func = ks_func or _ks

    # default exits follow entries
    if exit_on_lorentzian_sell is None:
        exit_on_lorentzian_sell = bool(use_lorentzian_buy)
    if exit_on_kalman_sell is None:
        exit_on_kalman_sell = bool(use_kalman_buy)

    # edge-only signals (Series aligned to df)
    lb_edge = lb_func(df, return_series=True).astype(np.uint8) if use_lorentzian_buy else pd.Series(0, index=df.index, dtype=np.uint8)
    kb_edge = kb_func(df, return_series=True).astype(np.uint8) if use_kalman_buy     else pd.Series(0, index=df.index, dtype=np.uint8)
    ls_edge = ls_func(df, return_series=True).astype(np.uint8) if exit_on_lorentzian_sell else pd.Series(0, index=df.index, dtype=np.uint8)
    ks_edge = ks_func(df, return_series=True).astype(np.uint8) if exit_on_kalman_sell     else pd.Series(0, index=df.index, dtype=np.uint8)

    # ---- resolve HH/HL (compute on-the-fly if needed) ----
    def _as_bool_series(x: pd.Series) -> pd.Series:
        s = pd.to_numeric(x, errors="coerce").fillna(0).astype(int)
        return (s != 0)

    hh_mask = pd.Series(True, index=df.index)
    hl_mask = pd.Series(True, index=df.index)

    need_hh = require_HH and hh_col not in df.columns
    need_hl = require_HL and hl_col not in df.columns
    if (need_hh or need_hl) and hhhl_func is None:
        # try a few common import paths
        try:
            from .signals import is_hh_hl as hhhl_func  # same package
        except Exception:
            try:
                from backend.accounts.strategies.signals import is_hh_hl as hhhl_func  # absolute
            except Exception:
                from signals import is_hh_hl as hhhl_func  # sibling

    if require_HH:
        if hh_col in df.columns:
            hh_mask = _as_bool_series(df[hh_col])
        else:
            isHH_arr, _ = hhhl_func(df)
            hh_mask = pd.Series(np.asarray(isHH_arr).astype(int) != 0, index=df.index)

    if require_HL:
        if hl_col in df.columns:
            hl_mask = _as_bool_series(df[hl_col])
        else:
            _, isHL_arr = hhhl_func(df)
            hl_mask = pd.Series(np.asarray(isHL_arr).astype(int) != 0, index=df.index)

    # ---- build entry indices per your rules ----
    entry_idx = []
    if use_lorentzian_buy and use_kalman_buy:
        li = np.where(lb_edge.values == 1)[0]
        ki = np.where(kb_edge.values == 1)[0]
        pL, pK = 0, 0
        while pL < len(li) and pK < len(ki):
            iL, iK = li[pL], ki[pK]
            d = iL - iK
            if abs(d) <= tolerance:
                ei = max(iL, iK)
                if hh_mask.iat[ei] and hl_mask.iat[ei]:
                    entry_idx.append(ei)
                pL += 1; pK += 1
            elif d < -tolerance:
                pL += 1
            else:
                pK += 1
    elif use_lorentzian_buy:
        for i in np.where(lb_edge.values == 1)[0]:
            if hh_mask.iat[i] and hl_mask.iat[i]:
                entry_idx.append(i)
    elif use_kalman_buy:
        for i in np.where(kb_edge.values == 1)[0]:
            if hh_mask.iat[i] and hl_mask.iat[i]:
                entry_idx.append(i)

    entry_idx = sorted(set(entry_idx))
    entry_set = set(entry_idx)

    # ---- simulate single-position long trades ----
    trades = []
    entry_mask = np.zeros(n, dtype=np.uint8)
    exit_mask  = np.zeros(n, dtype=np.uint8)

    in_pos = False
    ent_i = None
    ent_px = np.nan
    bars = 0

    for i in range(n):
        if not in_pos:
            if i in entry_set:
                in_pos = True
                ent_i = i
                ent_px = float(px[i])
                bars = 0
                entry_mask[i] = 1
        else:
            bars += 1
            reason = None
            # signal exits
            if exit_on_lorentzian_sell and ls_edge.iat[i] == 1:
                reason = "signal:lc"
            if reason is None and exit_on_kalman_sell and ks_edge.iat[i] == 1:
                reason = "signal:kalman"
            # risk exits
            if reason is None and take_profit_pct is not None and (px[i] / ent_px - 1.0) >= take_profit_pct:
                reason = "tp"
            if reason is None and stop_loss_pct is not None and (px[i] / ent_px - 1.0) <= -abs(stop_loss_pct):
                reason = "sl"
            if reason is None and max_hold_bars is not None and bars >= max_hold_bars:
                reason = "max_hold"

            # finalize exit (or force on last bar)
            if reason is not None or i == n - 1:
                exit_px = float(px[i])
                exit_mask[i] = 1
                gross = exit_px / ent_px
                net_factor = float(gross * (1.0 - float(fee)))  # round-trip fee
                trades.append({
                    "side": "long",
                    "entry_ts": df["ts"].iat[ent_i] if "ts" in df.columns else (df.index[ent_i] if isinstance(df.index, pd.DatetimeIndex) else ent_i),
                    "entry_px": ent_px,
                    "exit_ts":  df["ts"].iat[i]     if "ts" in df.columns else (df.index[i]     if isinstance(df.index, pd.DatetimeIndex) else i),
                    "exit_px":  exit_px,
                    "bars_held": bars,
                    "net_factor": net_factor,
                    "reason": (reason or "eod"),
                    # helpful indices for later enrichment
                    "entry_idx": ent_i,
                    "exit_idx":  i,
                })
                in_pos = False
                ent_i = None
                ent_px = np.nan
                bars = 0

    # ---- standardize to the UI table + attach stats ----
    trades_df = pd.DataFrame(trades)
    trades_df = _normalize_trade_cols(trades_df)    # enforce canonical columns & dtypes
    trades_df = _attach_trade_stats(df, trades_df)  # adds pnl_pct/runup_pct/drawdown_pct/cum_pnl_pct

    if return_masks:
        return trades_df, entry_mask, exit_mask
    return trades_df
