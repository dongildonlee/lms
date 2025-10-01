# backend/accounts/strategy_lorentzian.py
from __future__ import annotations
import pandas as pd
import numpy as np

# Reuse your existing helpers from strategies.py
from .strategies import _ensure_cols, _apply_fee_on_bars, _cum_from_returns

# Optional: tiny trade row helper so we don't depend on views_analysis internals
def _append_trade(trades, df: pd.DataFrame, side: str, i_entry: int, i_exit: int, fee: float):
    # guard
    if i_entry is None or i_exit is None or i_entry >= len(df) or i_exit >= len(df) or i_exit <= i_entry:
        return
    ts_e = pd.to_datetime(df["ts"].iloc[i_entry])
    ts_x = pd.to_datetime(df["ts"].iloc[i_exit])
    px_e = float(df["close"].iloc[i_entry])
    px_x = float(df["close"].iloc[i_exit])
    # fees at entry and exit
    if side == "long":
        gross = px_x / px_e
    else:  # short
        gross = px_e / px_x
    net_mult = gross * (1.0 - fee) * (1.0 - fee)
    pnl_pct = (net_mult - 1.0) * 100.0
    trades.append({
        "side": side,
        "entry_ts": ts_e,
        "exit_ts": ts_x,
        "entry_px": px_e,
        "exit_px": px_x,
        "pnl_pct": pnl_pct,
    })

def _trades_from_pos(view: pd.DataFrame, pos: pd.Series, fee: float) -> pd.DataFrame:
    trades = []
    side = None
    i_open = None
    for i in range(len(pos)):
        p  = int(pos.iat[i])
        p0 = int(pos.iat[i-1]) if i > 0 else 0
        if p != p0:
            # close existing at bar i (using close)
            if side is not None and i_open is not None:
                _append_trade(trades, view, side, i_open, i, fee)
                side, i_open = None, None
            # open new at *next* bar if it exists (safer for lookahead)
            if p in (1, -1) and i + 1 < len(pos):
                side = "long" if p == 1 else "short"
                i_open = i + 1
    # if still open into the end, close on the last bar
    if side is not None and i_open is not None:
        _append_trade(trades, view, side, i_open, len(pos) - 1, fee)
    return pd.DataFrame(trades)

from advanced_ta import LorentzianClassification as LC


from advanced_ta import LorentzianClassification as LC

def _half_bar_tolerance(ts: pd.Series) -> pd.Timedelta:
    ts = pd.to_datetime(ts, utc=True, errors="coerce").dropna()
    if len(ts) < 3:
        return pd.Timedelta(minutes=45)
    step = pd.Series(ts).diff().median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(minutes=60)
    return step / 2

def lorentzian_positions_advta(df, features=None, settings=None, filterSettings=None):
    # Lowercase OHLCV with a safe volume fallback
    df_in = df.rename(columns=str.lower).copy()
    for c in ("open", "high", "low", "close"):
        if c not in df_in:
            raise KeyError(f"Missing column {c!r} in input df")
    if "volume" not in df_in:
        df_in["volume"] = 0.0
    df_in = df_in[["open", "high", "low", "close", "volume"]]

    # Cover the full window unless caller overrides
    if settings is None:
        settings = LC.Settings(
            source="close",
            neighborsCount=8,
            maxBarsBack=len(df_in),   # classify across the entire slice
            useDynamicExits=False,
        )

    lc = LC(df_in, features=features, settings=settings, filterSettings=filterSettings)

    # Grab LC’s output (in-memory first; csv fallback)
    out = None
    for attr in ("df", "data", "result", "_df"):
        cand = getattr(lc, attr, None)
        if isinstance(cand, pd.DataFrame):
            out = cand
            break
    if out is None:
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv"); tmp.close()
        try:
            lc.dump(tmp.name)
            out = pd.read_csv(tmp.name)
        finally:
            try: os.remove(tmp.name)
            except Exception: pass

    # Select a signal column
    sig_col = next((c for c in ("signal", "prediction", "label", "y_pred", "pred") if c in out.columns), None)
    if sig_col is None:
        raise RuntimeError("advanced-ta output missing signal column (signal/prediction/label/y_pred/pred).")

    # Normalize signal → {-1,0,1}
    raw = out[sig_col]
    s = pd.to_numeric(raw, errors="coerce")
    if s.isna().any():
        sig_str = raw.astype(str).str.strip().str.lower()
        label_map = {
            "buy": 1, "long": 1, "bull": 1, "bullish": 1,
            "sell": -1, "short": -1, "bear": -1, "bearish": -1,
            "hold": 0, "flat": 0, "neutral": 0, "none": 0, "nan": 0, "": 0,
            "1": 1, "-1": -1, "0": 0, "true": 1, "false": 0,
        }
        mapped = sig_str.map(label_map)
        s = s.fillna(pd.to_numeric(mapped, errors="coerce"))
    s = s.fillna(0.0)
    s = (np.sign(s) if (s < 0).any() else s.round()).astype(int).clip(-1, 1)

    # Timestamp alignment (nearest within half a bar)
    df_ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    out_ts = None
    for cand in ("ts", "timestamp", "date", "datetime", "time"):
        if cand in out.columns:
            out_ts = pd.to_datetime(out[cand], utc=True, errors="coerce")
            break
    if out_ts is None and isinstance(out.index, pd.DatetimeIndex):
        out_ts = pd.to_datetime(out.index, utc=True, errors="coerce")

    pos = pd.Series(0, index=df.index, dtype=int)
    if out_ts is not None and out_ts.notna().any():
        left  = pd.DataFrame({"ts": df_ts}).dropna(subset=["ts"]).sort_values("ts")
        right = pd.DataFrame({"ts": out_ts, "sig": s.values}).dropna(subset=["ts"]).sort_values("ts")
        tol = _half_bar_tolerance(df_ts)
        merged = pd.merge_asof(left, right, on="ts", direction="nearest", tolerance=tol)
        pos[:] = merged["sig"].fillna(0).astype(int).clip(-1, 1).values
    else:
        # No timestamps in LC output; align by tail length
        m = min(len(df), len(s))
        pos.iloc[-m:] = s.iloc[-m:].values

    return pos


def lorentzian_strategy_advta(
    view: pd.DataFrame,
    *,
    fee_frac: float = 0.001,
    features=None,
    settings=None,
    filterSettings=None,
) -> pd.DataFrame:
    """
    Full strategy wrapper returning: ts, ret, cum, pos
    (shape matches your strategies.* outputs).
    """
    _ensure_cols(view)
    pos = lorentzian_positions_advta(view, features=features, settings=settings, filterSettings=filterSettings)

    # PnL path with fees on flips
    asset_ret = view["close"].pct_change().fillna(0.0)
    strat_ret = asset_ret * pos.shift(1, fill_value=0)
    flip = pos.ne(pos.shift(1, fill_value=0))
    ret = _apply_fee_on_bars(strat_ret, flip, fee_frac)
    cum = _cum_from_returns(ret)
    return pd.DataFrame({"ts": view["ts"], "ret": ret, "cum": cum, "pos": pos})

def lorentzian_trades_advta(
    view: pd.DataFrame,
    *,
    fee_frac: float = 0.001,
    features=None,
    settings=None,
    filterSettings=None,
) -> pd.DataFrame:
    """
    Convenience: directly build trades_df from LC positions;
    ready for analysis_all table & equity.
    """
    pos = lorentzian_positions_advta(view, features=features, settings=settings, filterSettings=filterSettings)
    return _trades_from_pos(view, pos, fee_frac)
