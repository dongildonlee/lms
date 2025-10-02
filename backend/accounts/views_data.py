# backend/accounts/views_data.py
from __future__ import annotations
from pathlib import Path
from django.http import JsonResponse
import pandas as pd

# Reuse the same data directory convention as the rest of the app
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _map_tf_to_yf(tf: str) -> tuple[str, str]:
    """Map our timeframe to yfinance (interval, period)."""
    tf = (tf or "1h").lower()
    if tf in ("1h", "60m"): return ("60m", "60d")
    if tf in ("5m", "5min"): return ("5m", "30d")
    if tf in ("1d", "day", "d"): return ("1d", "max")
    return ("60m", "60d")

def _standardize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return columns: ts, open, high, low, close, volume (UTC)."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("YF dataframe missing DatetimeIndex")
    idx = df.index
    if idx.tz is None: idx = idx.tz_localize("UTC")
    else: idx = idx.tz_convert("UTC")
    out = pd.DataFrame({
        "ts": idx,
        "open":  df["Open"].rename("open"),
        "high":  df["High"].rename("high"),
        "low":   df["Low"].rename("low"),
        "close": df["Close"].rename("close"),
        "volume":df["Volume"].rename("volume"),
    }).dropna().reset_index(drop=True)
    return out

def _stock_csv_name(symbol: str, tf: str, source: str = "yahoo") -> Path:
    return DATA_DIR / f"{symbol.lower()}_{tf.lower()}_{source}.csv"

def analysis_fill_csv(request, symbol: str):
    """
    GET /api/data/fill_csv/<symbol>/?tf=1h
    Downloads bars via yfinance and writes a standardized CSV:
      data/<symbol>_<tf>_yahoo.csv  (e.g., aapl_1h_yahoo.csv)
    Returns: { ok, path, rows } on success; { ok: False, reason } on error.
    """
    try:
        import yfinance as yf
    except Exception as e:
        return JsonResponse({"ok": False, "reason": f"yfinance not installed: {e}"}, status=500)

    tf = request.GET.get("tf", "1h")
    interval, period = _map_tf_to_yf(tf)
    ticker = symbol.upper()

    try:
        hist = yf.Ticker(ticker).history(interval=interval, period=period, auto_adjust=False)
        if hist is None or hist.empty:
            return JsonResponse({"ok": False, "reason": f"No data for {ticker} ({interval},{period})."}, status=404)

        df = _standardize_ohlcv(hist)
        if df.empty:
            return JsonResponse({"ok": False, "reason": f"No standardized rows for {ticker}."}, status=404)

        out_path = _stock_csv_name(symbol, tf, "yahoo")
        df.to_csv(out_path, index=False)
        return JsonResponse({"ok": True, "path": str(out_path), "rows": int(len(df))})
    except Exception as e:
        return JsonResponse({"ok": False, "reason": f"Fetch failed: {e}"}, status=500)
