# backend/accounts/views_update.py
import time
from pathlib import Path
from datetime import timedelta

import ccxt
import numpy as np
import pandas as pd
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt

# -------------------- CONFIG --------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

ET = "America/New_York"
TIMEFRAME = "5m"  # we target 5-minute candles
STEP_MS = 5 * 60 * 1000  # one candle width at 5m

# Supported short symbols -> ccxt symbols (slash pairs)
SYMBOL_MAP = {
    "BTC": "BTC/USD",
    "SOL": "SOL/USD",
    "ADA": "ADA/USD",
    "DOGE": "DOGE/USD",
    "DOT": "DOT/USD",
    "LINK": "LINK/USD",
    "ETH": "ETH/USD",
    "XRP": "XRP/USD"
}


# -------------------- HELPERS --------------------
def _ensure_numeric(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")


def _to_utc_ms_from_et(ts):
    """
    Accepts string or Timestamp, naive or tz-aware.
    If naive, assume ET; if tz-aware, convert to UTC.
    Returns UNIX ms.
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(ET, nonexistent="shift_forward")
    return int(t.tz_convert("UTC").timestamp() * 1000)


def _rows_to_df(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "time", "open", "high", "low", "close", "volume", "ts"])
    df = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"])
    df["ts"] = (
        pd.to_datetime(df["ms"], unit="ms", utc=True)
          .dt.tz_convert(ET).dt.tz_localize(None)
    )
    df["date"] = df["ts"].dt.strftime("%Y-%m-%d")
    df["time"] = df["ts"].dt.strftime("%H:%M:%S")
    df = df[["date", "time", "open", "high", "low", "close", "volume", "ts"]]
    _ensure_numeric(df, ["open", "high", "low", "close", "volume"])
    return df


def _fmt_ms(ms: int) -> str:
    """Pretty-print an ms epoch as ET-naive string (for debug)."""
    return (pd.to_datetime(ms, unit="ms", utc=True)
              .tz_convert(ET).tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"))


def _page_forward(ex, ccxt_symbol: str, since_ms: int, end_ms: int, limit: int) -> list:
    """
    Robust forward pagination with DEBUG prints:
    - fetch_ohlcv(..., since, limit)
    - if empty: jump forward by 'limit * candle_ms' to find first non-empty window
    - else: extend, advance since_ms past last_ms
    """
    out, batches = [], 0
    tf_ms = ex.parse_timeframe(TIMEFRAME) * 1000
    print(f"DEBUG: page_forward START  since={_fmt_ms(since_ms)}  →  end={_fmt_ms(end_ms)}  limit={limit}")

    while since_ms <= end_ms:
        batch = ex.fetch_ohlcv(ccxt_symbol, timeframe=TIMEFRAME, since=since_ms, limit=limit)
        batches += 1

        if not batch:
            # Jump forward one page-span to find first non-empty window near listing
            jump = limit * tf_ms
            probe = since_ms + jump
            print(f"DEBUG:  batch#{batches:>4}: EMPTY  window_start={_fmt_ms(since_ms)}  → jump +{jump//1000//60}m")
            if probe <= end_ms:
                since_ms = probe
                continue
            print("DEBUG:  no room to jump further; breaking")
            break

        first_ms, last_ms = batch[0][0], batch[-1][0]
        out.extend(batch)
        since_ms = max(last_ms + tf_ms, since_ms + tf_ms)  # advance at least one candle

        # Show a concise progress line every batch
        print(
            f"DEBUG:  batch#{batches:>4}: rows={len(batch):>4}  "
            f"range=[{_fmt_ms(first_ms)} → {_fmt_ms(last_ms)}]  next_since={_fmt_ms(since_ms)}"
        )

        # be polite to rate limits
        time.sleep(getattr(ex, "rateLimit", 200) / 1000.0)

    print(f"DEBUG: page_forward END    total_rows={len(out)}  batches={batches}")
    return out


# -------------------- VIEW --------------------
@csrf_exempt
def api_get_csv(request):
    """
    POST form fields:
      - symbol: one of {"BTC","SOL","ADA", ...} as per SYMBOL_MAP
      - mode: optional, "full" to backfill from a very early anchor ignoring existing CSV;
              default is forward-update from last_ts+5m
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    print("DEBUG: api_get_csv called; method =", request.method)
    print("DEBUG: request.POST =", request.POST)

    symbol_key = (request.POST.get("symbol") or "").upper()
    mode = (request.POST.get("mode") or "").lower()  # "", "full"
    if symbol_key not in SYMBOL_MAP:
        print("DEBUG: unsupported symbol:", symbol_key)
        return JsonResponse({"ok": False, "error": "Unsupported symbol"}, status=400)

    ccxt_symbol = SYMBOL_MAP[symbol_key]
    csv_path = DATA_DIR / f"{symbol_key.lower()}usd_5m_coinbase.csv"
    print(f"DEBUG: symbol={symbol_key}  ccxt_symbol={ccxt_symbol}  csv_path={csv_path}  mode={mode or '(update)'}")

    try:
        # Build exchange client
        ex = ccxt.coinbase({"enableRateLimit": True})
        ex.load_markets()
        print("DEBUG: exchange loaded; markets =", len(ex.symbols))

        limit = 2016  # ~7 days of 5m candles per call

        now_et = pd.Timestamp.now(tz=ET)
        end_et = (now_et.floor("5min") - pd.Timedelta(minutes=5))
        end_et_naive = end_et.tz_localize(None)              # <- drop tz
        end_ms = _to_utc_ms_from_et(end_et_naive)            # use the naive ET value
        print("DEBUG: end_et (naive) =", end_et_naive)

        # Load existing CSV if present
        if csv_path.exists():
            df_old = pd.read_csv(csv_path, low_memory=False)
            if "ts" not in df_old.columns:
                df_old["ts"] = pd.to_datetime(df_old["date"] + " " + df_old["time"], errors="coerce")
            else:
                df_old["ts"] = pd.to_datetime(df_old["ts"], errors="coerce")
            df_old = df_old.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
            print(f"DEBUG: loaded CSV rows={len(df_old)}  range=[{df_old['ts'].iloc[0] if len(df_old) else None} → {df_old['ts'].iloc[-1] if len(df_old) else None}]")
        else:
            df_old = pd.DataFrame()
            print("DEBUG: no CSV found; starting fresh")

        orig_rows = int(len(df_old))

        # Branch 1: FULL backfill (discover earliest via jumping pagination)
        if df_old.empty or mode == "full":
            start_et = pd.Timestamp("2019-01-01 00:00:00")
            since_ms = _to_utc_ms_from_et(start_et)
            print("DEBUG: FULL/BACKFILL  start_et =", start_et)

            rows = _page_forward(ex, ccxt_symbol, since_ms, end_ms, limit=limit)
            df_new = _rows_to_df(rows)
            print(f"DEBUG: backfill rows={len(df_new)}  df_old={len(df_old)}")

            if df_old.empty:
                combined = df_new
            else:
                combined = (
                    pd.concat([df_new, df_old], ignore_index=True)
                      .sort_values("ts").drop_duplicates(subset=["ts"]).reset_index(drop=True)
                )

        # Branch 2: Forward update only
        else:
            last_ts = df_old["ts"].iloc[-1]
            since_et = last_ts + pd.Timedelta(minutes=5)
            if since_et > end_et_naive:
                print("DEBUG: already up to date  last_ts=", last_ts)
                return JsonResponse({
                    "ok": True,
                    "added_rows": 0,
                    "rows": int(len(df_old)),
                    "from": str(df_old["ts"].iloc[0]),
                    "to": str(df_old["ts"].iloc[-1]),
                    "message": "CSV already up to date"
                })

            since_ms = _to_utc_ms_from_et(since_et)
            print("DEBUG: FORWARD update  since_et=", since_et, " end_et=", end_et_naive)

            rows = _page_forward(ex, ccxt_symbol, since_ms, end_ms, limit=limit)
            df_new = _rows_to_df(rows)
            print(f"DEBUG: forward rows fetched={len(df_new)}")

            combined = (
                pd.concat([df_old, df_new], ignore_index=True)
                  .sort_values("ts").drop_duplicates(subset=["ts"]).reset_index(drop=True)
            )

        added = int(len(combined) - orig_rows)
        combined.to_csv(csv_path, index=False)
        print(f"DEBUG: WRITE CSV  path={csv_path}  total_rows={len(combined)}  added={added}")

        return JsonResponse({
            "ok": True,
            "added_rows": added,
            "rows": int(len(combined)),
            "from": (str(combined["ts"].iloc[0]) if not combined.empty else None),
            "to":   (str(combined["ts"].iloc[-1]) if not combined.empty else None),
            "path": str(csv_path),
        })

    except Exception as e:
        print("DEBUG: EXCEPTION:", type(e).__name__, e)
        return JsonResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)



