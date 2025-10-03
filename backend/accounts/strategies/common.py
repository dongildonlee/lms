# backend/accounts/strategies/common.py
from __future__ import annotations
import pandas as pd
import numpy as np

def ensure_ema_cols(view: pd.DataFrame, spans=(20,50,100)):
    req = {"ts","open","high","low","close"}
    missing = req - set(view.columns)
    if missing:
        raise ValueError(f"view is missing columns: {missing}")
    for s in spans:
        col = f"ema{s}"
        if col not in view.columns:
            raise ValueError(f"{col} missing — compute EMAs before calling strategy.")


def cum_from_returns(ret: pd.Series) -> pd.Series:
    return (1.0 + ret.fillna(0.0)).cumprod() - 1.0


def apply_fee_on_bars(ret: pd.Series, fee_mask: pd.Series, fee: float) -> pd.Series:
    if not fee:
        return ret
    out = ret.copy()
    idx = fee_mask[fee_mask].index
    out.loc[idx] = (1.0 + out.loc[idx]) * (1.0 - fee) - 1.0
    return out


def _pnl_long(entry_px: float, exit_px: float, fee: float) -> float:
    return (exit_px / entry_px) * (1 - fee) * (1 - fee) - 1.0


def _pnl_short(entry_px: float, exit_px: float, fee: float) -> float:
    return (entry_px / exit_px) * (1 - fee) * (1 - fee) - 1.0


def mfe_mae(view: pd.DataFrame, side: str, entry_i: int, exit_i: int, entry_px: float) -> tuple[float, float]:
    win = view.iloc[entry_i:exit_i+1]
    if side == "long":
        mfe = (win["high"].max() / entry_px - 1.0) * 100.0
        mae = (win["low"].min()  / entry_px - 1.0) * 100.0
    else:
        mfe = (entry_px / win["low"].min()  - 1.0) * 100.0
        mae = (entry_px / win["high"].max() - 1.0) * 100.0
    return mfe, mae


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