# lms/backend/invest/update_utils.py
import pandas as pd
import numpy as np
import ccxt, time
from datetime import timedelta

# --- CONFIG (reuse your constants) ---
CSV = "solusd_5m_table_COINBASE_FILLED.csv"
ET  = "America/New_York"
STEP_MS = 5 * 60 * 1000  # 5m

# ---------- helpers ----------
def _to_utc_ms_from_et(ts_et):
    t = pd.Timestamp(ts_et)
    if t.tzinfo is None:
        t = t.tz_localize(ET, nonexistent="shift_forward")
    return int(t.tz_convert("UTC").timestamp() * 1000)

def _ensure_numeric(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

def _recompute_emas_if_present(df):
    # If EMA columns exist in the CSV, recompute them on the *combined* series
    # so appended rows are consistent.
    for span in (20, 50, 100):
        col = f"ema{span}"
        if col in df.columns:
            df[col] = df["close"].ewm(span=span, adjust=False, min_periods=span).mean()
    return df

# ---------- main updater ----------
def update_csv(csv_path=CSV,
               symbol="SOL/USD",
               timeframe="5m",
               exchange_name="coinbase",
               max_batches=1000,
               quiet=False):
    """
    Reads csv_path, detects the last bar's timestamp, fetches CCXT OHLCV from last+5m -> now,
    appends new rows, recomputes EMA20/50/100 if those columns exist, and writes back.
    - csv schema expected to have 'date','time','open','high','low','close' (and optionally ema20/50/100).
    - Timestamps are stored as naive ET in a 'ts' helper column (created if missing), then dropped on save.

    Returns: dict(summary)
    """
    # ---- Load existing CSV
    df = pd.read_csv(csv_path, dtype={"asset":"string","source":"string"}, low_memory=False)
    # build/refresh ts
    if "ts" not in df.columns:
        df["ts"] = pd.to_datetime(df["date"] + " " + df["time"], errors="coerce")
    else:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")  # tolerate if present

    _ensure_numeric(df, ["open","high","low","close","volume","ema20","ema50","ema100"])
    df = df.dropna(subset=["ts","open","high","low","close"]).sort_values("ts")
    df = df[~df["ts"].duplicated(keep="last")].reset_index(drop=True)

    if df.empty:
        raise ValueError("CSV appears empty after cleaning; seed it first (no bars to anchor an update).")

    last_ts = df["ts"].iloc[-1]
    # next desired bar start = last + 5 minutes
    start_ts = last_ts + timedelta(minutes=5)

    # clamp end to (now_ET - 5m) to avoid partial/in-progress bar
    now_et = pd.Timestamp.now(tz=ET).tz_localize(None)
    end_ts = now_et - timedelta(minutes=5)
    if start_ts > end_ts:
        if not quiet:
            print("No new data to fetch (CSV already up to date).")
        return {
            "added_rows": 0,
            "csv_rows_after": len(df),
            "last_ts_before": last_ts,
            "last_ts_after": df["ts"].iloc[-1],
            "from": None,
            "to": None
        }

    # ---- CCXT fetch loop
    ex = getattr(ccxt, exchange_name)({"enableRateLimit": True})
    ex.load_markets()
    since = _to_utc_ms_from_et(start_ts)
    end_ms = _to_utc_ms_from_et(end_ts)

    rows = []
    batches = 0
    while since <= end_ms and batches < max_batches:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=300)
        if not batch:
            break
        rows.extend(batch)
        last_ms = batch[-1][0]
        # advance at least one step to avoid duplicates; Coinbase returns inclusive bars
        since = max(last_ms + STEP_MS, since + STEP_MS)
        # respect rate limit
        time.sleep(getattr(ex, "rateLimit", 200) / 1000.0)
        batches += 1

    if not rows:
        if not quiet:
            print("Exchange returned no new candles.")
        return {
            "added_rows": 0,
            "csv_rows_after": len(df),
            "last_ts_before": last_ts,
            "last_ts_after": df["ts"].iloc[-1],
            "from": None,
            "to": None
        }

    raw = pd.DataFrame(rows, columns=["ms","open","high","low","close","volume"])
    # Convert to ET (naive) like the rest of your pipeline
    raw["ts"] = (
        pd.to_datetime(raw["ms"], unit="ms", utc=True)
          .dt.tz_convert(ET)          # convert UTC -> ET
          .dt.tz_localize(None)       # drop tz, keep naive ET timestamps
    )
    new = raw.set_index("ts")[["open","high","low","close","volume"]].astype(float)
    # slice to the exact requested window (defensive)
    new = new.loc[(new.index >= start_ts) & (new.index <= end_ts)]
    if new.empty:
        if not quiet:
            print("No new rows after window filtering.")
        return {
            "added_rows": 0,
            "csv_rows_after": len(df),
            "last_ts_before": last_ts,
            "last_ts_after": df["ts"].iloc[-1],
            "from": None,
            "to": None
        }

    # ---- Build appendable frame with date/time columns
    add = new.reset_index().rename(columns={"ts":"ts"})
    add["date"] = add["ts"].dt.strftime("%Y-%m-%d")
    add["time"] = add["ts"].dt.strftime("%H:%M:%S")
    # Preserve any existing columns (ema20/50/100 etc.) with NaN placeholders; we’ll recompute next
    for extra_col in df.columns:
        if extra_col not in add.columns and extra_col not in ["asset","source"]:
            add[extra_col] = np.nan

    # ---- Append & dedupe
    cols_order = df.columns  # keep the same column order when saving
    combined = pd.concat([df, add[cols_order.intersection(add.columns)]], ignore_index=True, sort=False)
    combined = combined.drop_duplicates(subset=["ts"], keep="last").sort_values("ts").reset_index(drop=True)

    # ---- Recompute EMAs if present
    if {"ema20","ema50","ema100"}.intersection(set(combined.columns)):
        combined = _recompute_emas_if_present(combined)

    # ---- Save back
    had_ts_col = "ts" in df.columns and "ts" not in ({"date","time"} - set())
    combined_out = combined.copy()
    if "ts" in combined_out.columns and not had_ts_col:
        combined_out = combined_out.drop(columns=["ts"])

    combined_out.to_csv(csv_path, index=False)

    added = combined["ts"].isin(add["ts"]).sum()
    if not quiet:
        print(f"Added {added} new rows | {csv_path}")
        print(f"Range: {add['ts'].min()}  →  {add['ts'].max()}")

    return {
        "added_rows": int(added),
        "csv_rows_after": int(len(combined_out)),
        "last_ts_before": pd.Timestamp(last_ts),
        "last_ts_after": pd.Timestamp(combined['ts'].iloc[-1]),
        "from": pd.Timestamp(add['ts'].min()),
        "to": pd.Timestamp(add['ts'].max())
    }
