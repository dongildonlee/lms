# seed_once.py  (run from anywhere with the venv active)
import pandas as pd, ccxt, time
from datetime import timedelta
from pathlib import Path

ET = "America/New_York"
STEP_MS = 5 * 60 * 1000
DATA_DIR = Path("/Users/dongillee/lms/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def to_utc_ms_from_et(ts_et):
    t = pd.Timestamp(ts_et)
    if t.tzinfo is None:
        t = t.tz_localize(ET, nonexistent="shift_forward")
    return int(t.tz_convert("UTC").timestamp() * 1000)

def seed(symbol_ccxt, out_csv, days=7, exchange_name="coinbase"):
    ex = getattr(ccxt, exchange_name)({"enableRateLimit": True})
    ex.load_markets()
    end_et = pd.Timestamp.now(tz=ET).tz_localize(None) - pd.Timedelta(minutes=5)
    start_et = end_et - pd.Timedelta(days=days)
    since = to_utc_ms_from_et(start_et)
    end_ms = to_utc_ms_from_et(end_et)
    rows = []
    while since <= end_ms:
        batch = ex.fetch_ohlcv(symbol_ccxt, timeframe="5m", since=since, limit=300)
        if not batch:
            break
        rows.extend(batch)
        last_ms = batch[-1][0]
        since = max(last_ms + STEP_MS, since + STEP_MS)
        time.sleep(getattr(ex, "rateLimit", 200)/1000.0)
    if not rows:
        raise RuntimeError("No data returned to seed " + symbol_ccxt)

    raw = pd.DataFrame(rows, columns=["ms","open","high","low","close","volume"])
    ts = (pd.to_datetime(raw["ms"], unit="ms", utc=True)
            .dt.tz_convert(ET)
            .dt.tz_localize(None))
    out = pd.DataFrame({
        "date": ts.dt.strftime("%Y-%m-%d"),
        "time": ts.dt.strftime("%H:%M:%S"),
        "open": raw["open"].astype(float),
        "high": raw["high"].astype(float),
        "low": raw["low"].astype(float),
        "close": raw["close"].astype(float),
        "volume": raw["volume"].astype(float),
    })
    out.to_csv(out_csv, index=False)
    print(f"Seeded {len(out)} rows -> {out_csv}")

# seed BTC and ADA (skip SOL if you already have it)
seed("BTC/USD", DATA_DIR / "btcusd_5m_table_COINBASE_FILLED.csv", days=7)
seed("ADA/USD", DATA_DIR / "adausd_5m_table_COINBASE_FILLED.csv", days=7)
