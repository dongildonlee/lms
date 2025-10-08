# backend/accounts/strategy_lorentzian.py
from __future__ import annotations
import pandas as pd
import numpy as np

# Reuse your existing helpers from strategies.py
from .common import ensure_ema_cols as _ensure_cols, apply_fee_on_bars as _apply_fee_on_bars, cum_from_returns as _cum_from_returns

# wherever you currently have: from advanced_ta import LorentzianClassification as LC
import pandas as pd
import numpy as np
from .common import _append_trade


try:
    from advanced_ta import LorentzianClassification as LC  # real package
# except Exception:
#     # ---- Local shim fallback: returns zeros so the app can run ----
#     class LC:
#         def __init__(self, *args, **kwargs):
#             pass
#         def fit(self, X, y=None):
#             return self
#         def transform(self, X):
#             # Accept DataFrame/Series/ndarray; return a Series/array of zeros
#             if isinstance(X, pd.DataFrame):
#                 idx = X.index
#                 n = len(X)
#                 return pd.Series(np.zeros(n, dtype=float), index=idx)
#             elif isinstance(X, pd.Series):
#                 return pd.Series(np.zeros(len(X), dtype=float), index=X.index)
#             else:
#                 # assume array-like
#                 return np.zeros(len(X), dtype=float)
#         def fit_transform(self, X, y=None):
#             return self.transform(X)


except Exception:
    # ---- Local shim fallback: returns zeros so the app can run ----
    class LC:
        class Settings:
            def __init__(self, source="close", neighborsCount=8, maxBarsBack=None, useDynamicExits=False):
                self.source = source
                self.neighborsCount = neighborsCount
                self.maxBarsBack = maxBarsBack
                self.useDynamicExits = useDynamicExits

        def __init__(self, *args, **kwargs):
            self._last_len = 0  # remember last transform length

        def fit(self, X, y=None):
            return self

        def transform(self, X):

            if isinstance(X, pd.DataFrame):
                n, idx = len(X), X.index
                self._last_len = n
                return pd.Series(np.zeros(n, dtype=float), index=idx, name="pos")
            if isinstance(X, pd.Series):
                n = len(X); self._last_len = n
                return pd.Series(np.zeros(n, dtype=float), index=X.index, name="pos")
            # array-like
            n = len(X); self._last_len = n
    
            return np.zeros(n, dtype=float)

        def fit_transform(self, X, y=None):
            return self.transform(X)

        def dump(self, path):
            # Write a minimal CSV with a 'pos' column of zeros
            try:
                s = pd.Series([0.0] * int(self._last_len or 0), name="pos")
                s.to_csv(path, index=False)
            except Exception:
                # fall back to empty file
                try:
                    with open(path, "wb") as f:
                        f.write(b"")
                except Exception:
                    pass
            return path





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


def _half_bar_tolerance(ts: pd.Series) -> pd.Timedelta:
    ts = pd.to_datetime(ts, utc=True, errors="coerce").dropna()
    if len(ts) < 3:
        return pd.Timedelta(minutes=45)
    step = pd.Series(ts).diff().median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(minutes=60)
    return step / 2

# def lorentzian_positions_advta(df, features=None, settings=None, filterSettings=None):
#     # Lowercase OHLCV with a safe volume fallback
#     df_in = df.rename(columns=str.lower).copy()
#     for c in ("open", "high", "low", "close"):
#         if c not in df_in:
#             raise KeyError(f"Missing column {c!r} in input df")
#     if "volume" not in df_in:
#         df_in["volume"] = 0.0
#     df_in = df_in[["open", "high", "low", "close", "volume"]]

#     # Cover the full window unless caller overrides
#     if settings is None:
#         settings = LC.Settings(
#             source="close",
#             neighborsCount=8,
#             maxBarsBack=len(df_in),   # classify across the entire slice
#             useDynamicExits=False,
#         )

#     lc = LC(df_in, features=features, settings=settings, filterSettings=filterSettings)

#     # Grab LC’s output (in-memory first; csv fallback)
#     out = None
#     for attr in ("df", "data", "result", "_df"):
#         cand = getattr(lc, attr, None)
#         if isinstance(cand, pd.DataFrame):
#             out = cand
#             break
#     if out is None:
#         import tempfile, os
#         tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv"); tmp.close()
#         try:
#             lc.dump(tmp.name)
#             out = pd.read_csv(tmp.name)
#         finally:
#             try: os.remove(tmp.name)
#             except Exception: pass

#     # Select a signal column
#     sig_col = next((c for c in ("signal", "prediction", "label", "y_pred", "pred") if c in out.columns), None)
#     if sig_col is None:
#         raise RuntimeError("advanced-ta output missing signal column (signal/prediction/label/y_pred/pred).")

#     # Normalize signal → {-1,0,1}
#     raw = out[sig_col]
#     s = pd.to_numeric(raw, errors="coerce")
#     if s.isna().any():
#         sig_str = raw.astype(str).str.strip().str.lower()
#         label_map = {
#             "buy": 1, "long": 1, "bull": 1, "bullish": 1,
#             "sell": -1, "short": -1, "bear": -1, "bearish": -1,
#             "hold": 0, "flat": 0, "neutral": 0, "none": 0, "nan": 0, "": 0,
#             "1": 1, "-1": -1, "0": 0, "true": 1, "false": 0,
#         }
#         mapped = sig_str.map(label_map)
#         s = s.fillna(pd.to_numeric(mapped, errors="coerce"))
#     s = s.fillna(0.0)
#     s = (np.sign(s) if (s < 0).any() else s.round()).astype(int).clip(-1, 1)

#     # Timestamp alignment (nearest within half a bar)
#     df_ts = pd.to_datetime(df["ts"], utc=True, errors="coerce")
#     out_ts = None
#     for cand in ("ts", "timestamp", "date", "datetime", "time"):
#         if cand in out.columns:
#             out_ts = pd.to_datetime(out[cand], utc=True, errors="coerce")
#             break
#     if out_ts is None and isinstance(out.index, pd.DatetimeIndex):
#         out_ts = pd.to_datetime(out.index, utc=True, errors="coerce")

#     pos = pd.Series(0, index=df.index, dtype=int)
#     if out_ts is not None and out_ts.notna().any():
#         left  = pd.DataFrame({"ts": df_ts}).dropna(subset=["ts"]).sort_values("ts")
#         right = pd.DataFrame({"ts": out_ts, "sig": s.values}).dropna(subset=["ts"]).sort_values("ts")
#         tol = _half_bar_tolerance(df_ts)
#         merged = pd.merge_asof(left, right, on="ts", direction="nearest", tolerance=tol)
#         pos[:] = merged["sig"].fillna(0).astype(int).clip(-1, 1).values
#     else:
#         # No timestamps in LC output; align by tail length
#         m = min(len(df), len(s))
#         pos.iloc[-m:] = s.iloc[-m:].values
        
    

#     return pos



def lorentzian_positions_advta(df, features=None, settings=None, filterSettings=None):
    """
    Run the Lorentzian classifier (advanced_ta LC or shim) and return a position Series
    aligned to the input df index with values in {-1, 0, 1}. This is resilient to
    missing/empty outputs by returning zeros instead of raising.
    """
    import os
    import tempfile
    import numpy as np
    import pandas as pd
    from pandas.errors import EmptyDataError

    # --------- helpers ----------
    def _half_bar_tolerance(ts_series):
        """Half the median bar width as a Pandas Timedelta; defaults to 30min if unknown."""
        ts = pd.to_datetime(ts_series, utc=True, errors="coerce").dropna()
        if len(ts) < 2:
            return pd.Timedelta(minutes=30)
        diffs = ts.sort_values().diff().dropna()
        med = diffs.median() if not diffs.empty else pd.Timedelta(minutes=60)
        return med / 2

    def _zeros_like_df(in_df, name="pos"):
        return pd.Series(np.zeros(len(in_df), dtype=float), index=in_df.index, name=name)

    # --------- normalize input ----------
    df_in = df.rename(columns=str.lower).copy()
    for c in ("open", "high", "low", "close"):
        if c not in df_in:
            # required OHLC columns
            return _zeros_like_df(df)
    if "volume" not in df_in:
        df_in["volume"] = 0.0
    # keep a predictable column order for downstream libs
    df_in = df_in[["open", "high", "low", "close", "volume"]]

    # --------- settings default ----------
    try:
        _ = LC  # type: ignore  # ensure LC is present
    except Exception:
        # If LC itself is not available for some reason, just return zeros.
        return _zeros_like_df(df)

    if settings is None:
        try:
            settings = LC.Settings(
                source="close",
                neighborsCount=8,
                maxBarsBack=len(df_in),
                useDynamicExits=False,
            )
        except Exception:
            # Some shims may not require/accept Settings; continue with None.
            settings = None

    # --------- run LC ----------
    try:
        lc = LC(df_in, features=features, settings=settings, filterSettings=filterSettings)
    except Exception:
        # If constructor fails, return zeros
        return _zeros_like_df(df)

    # First try to find an in-memory DataFrame on the LC object
    out = None
    for attr in ("df", "data", "result", "_df", "output"):
        cand = getattr(lc, attr, None)
        if isinstance(cand, pd.DataFrame) and len(cand) > 0:
            out = cand
            break

    # If none found, fall back to dump-to-temp and read
    if out is None:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp_path = tmp.name
            # dump if method exists
            if hasattr(lc, "dump"):
                try:
                    lc.dump(tmp_path)
                except Exception:
                    pass

            # Read back only if file has content
            size = 0
            if tmp_path and os.path.exists(tmp_path):
                try:
                    size = os.path.getsize(tmp_path)
                except Exception:
                    size = 0

            if size > 0:
                try:
                    out = pd.read_csv(tmp_path)
                except EmptyDataError:
                    out = None
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    # If still nothing usable, return zeros
    if not isinstance(out, pd.DataFrame) or out.empty:
        return _zeros_like_df(df)

    # --------- choose a signal column ----------
    sig_col = next((c for c in ("signal", "prediction", "label", "y_pred", "pred", "pos") if c in out.columns), None)
    if sig_col is None:
        # No recognizable signal column → zeros
        return _zeros_like_df(df)

    raw = out[sig_col]

    # --------- normalize to {-1,0,1} ----------
    s = pd.to_numeric(raw, errors="coerce")
    if s.isna().any():
        sig_str = raw.astype(str).str.strip().str.lower()
        label_map = {
            "buy": 1, "long": 1, "bull": 1, "bullish": 1, "true": 1, "1": 1,
            "sell": -1, "short": -1, "bear": -1, "bearish": -1, "-1": -1,
            "hold": 0, "flat": 0, "neutral": 0, "none": 0, "nan": 0, "": 0, "false": 0, "0": 0,
        }
        mapped = sig_str.map(label_map)
        s = s.fillna(pd.to_numeric(mapped, errors="coerce"))
    s = s.fillna(0.0)
    # If there are negative values, keep sign; else round to {0,1}
    s = (np.sign(s) if (s < 0).any() else s.round()).astype(int).clip(-1, 1)

    # --------- align to input df by timestamp if possible ----------
    df_ts = pd.to_datetime(df.get("ts", pd.NaT), utc=True, errors="coerce")

    out_ts = None
    for cand in ("ts", "timestamp", "date", "datetime", "time"):
        if cand in out.columns:
            out_ts = pd.to_datetime(out[cand], utc=True, errors="coerce")
            break
    if out_ts is None and isinstance(out.index, pd.DatetimeIndex):
        out_ts = pd.to_datetime(out.index, utc=True, errors="coerce")

    pos = pd.Series(0, index=df.index, dtype=int, name="pos")

    if out_ts is not None and out_ts.notna().any() and df_ts.notna().any():
        left = pd.DataFrame({"ts": df_ts}).dropna(subset=["ts"]).sort_values("ts")
        right = pd.DataFrame({"ts": out_ts, "sig": s.values}).dropna(subset=["ts"]).sort_values("ts")
        tol = _half_bar_tolerance(df_ts)
        merged = pd.merge_asof(left, right, on="ts", direction="nearest", tolerance=tol)
        # Fill back into the original index order
        pos.loc[left.index] = merged["sig"].fillna(0).astype(int).clip(-1, 1).values
    else:
        # No timestamps in LC output; align by tail length
        m = min(len(df), len(s))
        if m > 0:
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
