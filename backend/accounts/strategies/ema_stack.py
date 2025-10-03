# backend/accounts/strategies.py
from __future__ import annotations
import pandas as pd
import numpy as np
from .common import _append_trade, _finalize_trades


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


def _stack_masks(view):
    long_stack  = ((view["ema20"] > view["ema50"]) & (view["ema50"] > view["ema100"])).fillna(False)
    short_stack = ((view["ema20"] < view["ema50"]) & (view["ema50"] < view["ema100"])).fillna(False)
    return long_stack, short_stack


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




