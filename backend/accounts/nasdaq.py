# backend/accounts/nasdaq.py
from __future__ import annotations
import os, datetime as dt
from pathlib import Path
import pandas as pd
import requests




STANDARD_COLS = ["date", "time", "open", "high", "low", "close", "volume", "ts"]
DEFAULT_TIME_FOR_DAILY = "00:00:00"  # change to "16:00:00" if you prefer EOD close time




# --- optional: keep Data Link key loaded, but we won't use it for now ---
try:
   from dotenv import load_dotenv
except ImportError:
   load_dotenv = None
_THIS_DIR = Path(__file__).resolve().parent
if load_dotenv:
   load_dotenv(_THIS_DIR / ".env")


API_KEY = os.getenv("NASDAQ_API_KEY", "").strip()


# ---------- Paths ----------
def stocks_dir() -> Path:
   return Path(__file__).resolve().parents[2] / "backend" / "data" / "stocks"


def csv_path(sym: str) -> Path:
   sym = (sym or "").upper().strip()
   return stocks_dir() / f"HistoricalData_{sym}.csv"


def _ensure_dir(p: Path) -> None:
   p.mkdir(parents=True, exist_ok=True)


# ---------- CSV helpers ----------
def _best_start(existing_csv: Path | None) -> dt.date:
   today = dt.date.today()
   if existing_csv and existing_csv.exists():
       try:
           cur = pd.read_csv(existing_csv)
           if "Date" in cur.columns:
               s = pd.to_datetime(cur["Date"], errors="coerce").dt.date.dropna()
               if not s.empty:
                   return max(s) + dt.timedelta(days=1)
       except Exception:
           pass
   return today.replace(year=max(2000, today.year - 10))


def _append_and_save(target: Path, new_rows: pd.DataFrame) -> tuple[int, int]:
   if target.exists():
       old = pd.read_csv(target)
   else:
       old = pd.DataFrame(columns=["Date","Open","High","Low","Close","Volume"])
   both = pd.concat([old, new_rows], ignore_index=True)
   both["Date"] = pd.to_datetime(both["Date"], errors="coerce").dt.date
   both = both.dropna(subset=["Date"]).drop_duplicates(subset=["Date"]).sort_values("Date")
   added = len(both) - len(old)
   _ensure_dir(target.parent)
   tmp = target.with_suffix(".tmp.csv")
   both.to_csv(tmp, index=False)
   tmp.replace(target)
   return added, len(both)


# ---------- Parse helper (shared) ----------
def _clean_num(x):
   if isinstance(x, (int, float)): return float(x)
   if x is None: return float("nan")
   return float(str(x).replace(",", "").strip())


def _parse_nasdaq_rows(rows: list[dict]) -> pd.DataFrame:
   if not rows:
       return pd.DataFrame(columns=["Date","Open","High","Low","Close","Volume"])
   df = pd.DataFrame(rows)
   lower = {c.lower(): c for c in df.columns}
   def col(name): return lower.get(name)
   c_date  = col("date")
   c_open  = col("open")
   c_high  = col("high")
   c_low   = col("low")
   c_close = col("close")
   c_vol   = col("volume") or col("sharevolume") or col("shares")


   out = pd.DataFrame({
       "Date":  pd.to_datetime(df[c_date], errors="coerce").dt.date if c_date in df else pd.NaT,
       "Open":  df[c_open ].apply(_clean_num) if c_open  in df else float("nan"),
       "High":  df[c_high ].apply(_clean_num) if c_high  in df else float("nan"),
       "Low":   df[c_low  ].apply(_clean_num) if c_low   in df else float("nan"),
       "Close": df[c_close].apply(_clean_num) if c_close in df else float("nan"),
       "Volume": pd.to_numeric(df[c_vol].map(lambda v: str(v).replace(",", "").strip()), errors="coerce").fillna(0).astype("Int64") if c_vol in df else 0,
   })
   out = out.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
   return out


# ---------- FREE web endpoint (nasdaq.com page JSON) ----------
# backend/accounts/nasdaq.py


def _fetch_nasdaq_web(sym: str, start: dt.date, end: dt.date) -> pd.DataFrame:
   """
   Stable backfill without paging:
     1) Request [start, end] with limit=250 (most-recent 250 rows).
     2) If we got rows, append; set end = earliest_date - 1 day.
     3) Repeat until earliest_date <= start, or no progress, or caps reached.
   """
   base = f"https://api.nasdaq.com/api/quote/{sym.upper().strip()}/historical"
   headers = {
       "User-Agent": "Mozilla/5.0",
       "Accept": "application/json, text/plain, */*",
       "Referer": f"https://www.nasdaq.com/market-activity/stocks/{sym.lower().strip()}/historical",
       "Origin": "https://www.nasdaq.com",
   }


   LIMIT_PER_CALL = 250
   MAX_CALLS      = 40        # safety: ~10k rows; raise if you want deeper
   NO_PROGRESS_CAP = 3        # break if we fail to go earlier 3 times in a row


   all_frames: list[pd.DataFrame] = []
   seen_dates: set[dt.date] = set()
   calls = 0
   no_progress = 0
   prev_earliest: dt.date | None = None
   cur_end = end


   while cur_end >= start and calls < MAX_CALLS:
       params = {
           "assetclass": "stocks",
           "fromdate": start.isoformat(),   # keep start fixed
           "todate":   cur_end.isoformat(), # walk cur_end backward
           "limit":    str(LIMIT_PER_CALL)
       }
       r = requests.get(base, params=params, headers=headers, timeout=20)
       r.raise_for_status()
       js = r.json()
       rows = (((js or {}).get("data") or {}).get("tradesTable") or {}).get("rows", []) or []
       calls += 1


       if not rows:
           # nothing in this window → move back a little and count "no progress"
           no_progress += 1
           cur_end = cur_end - dt.timedelta(days=30)
           if no_progress >= NO_PROGRESS_CAP:
               break
           continue


       df = _parse_nasdaq_rows(rows)
       if df.empty:
           no_progress += 1
           cur_end = cur_end - dt.timedelta(days=30)
           if no_progress >= NO_PROGRESS_CAP:
               break
           continue


       # de-dup on the fly and see if we actually discovered earlier dates
       new_dates = [d for d in df["Date"].tolist() if isinstance(d, dt.date) and d not in seen_dates]
       if new_dates:
           all_frames.append(df)
           seen_dates.update(new_dates)
           no_progress = 0
       else:
           no_progress += 1


       earliest = df["Date"].min()
       if earliest is None or pd.isna(earliest):
           # safety: step back a month
           cur_end = cur_end - dt.timedelta(days=30)
       else:
           # If we didn't move earlier than last time, count no-progress
           if prev_earliest is not None and earliest >= prev_earliest:
               no_progress += 1
           prev_earliest = earliest
           # Move the window to fetch OLDER chunk next
           cur_end = earliest - dt.timedelta(days=1)


       if earliest is not None and not pd.isna(earliest) and earliest <= start:
           break


       if no_progress >= NO_PROGRESS_CAP:
           break


   if not all_frames:
       return pd.DataFrame(columns=["Date","Open","High","Low","Close","Volume"])


   df_all = pd.concat(all_frames, ignore_index=True)
   df_all = (df_all.dropna(subset=["Date"])
                   .drop_duplicates(subset=["Date"])
                   .sort_values("Date"))
   return df_all[(df_all["Date"] >= start) & (df_all["Date"] <= end)].reset_index(drop=True)








# ---------- Public function used by the site ----------
def update_symbol(sym: str) -> dict:
   """
   Default updater: uses free web endpoint so you don't need a paid NDL dataset.
   """
   sym = (sym or "").upper().strip()
   target = csv_path(sym)
   start  = _best_start(target)
   end    = dt.date.today()
   if start > end:
       return {"ok": True, "ticker": sym, "rows_added": 0, "path": str(target)}
   df = _fetch_nasdaq_web(sym, start, end)
   if df.empty:
       return {"ok": False, "error": f"No rows from Nasdaq for {sym}."}
   added, total = _append_and_save_standard(target, df)
   return {"ok": True, "ticker": sym, "rows_added": added, "total_rows": total, "path": str(target)}


# ---------- (keep your Data Link version here if needed later) ----------
def update_symbol_datalink(sym: str) -> dict:
   raise RuntimeError("Data Link version requires a subscribed dataset (e.g., SEP). Use update_symbol() instead for the free nasdaq.com endpoint.")




def _clean_num(x):
   if x is None: return float("nan")
   s = str(x).strip()
   if s in {"", "-", "—", "N/A", "NA", "null"}: return float("nan")
   neg = False
   if s.startswith("(") and s.endswith(")"):
       neg, s = True, s[1:-1].strip()
   s = s.replace("$", "").replace(",", "")
   if s.endswith("%"): s = s[:-1]
   try:
       v = float(s)
       return -v if neg else v
   except Exception:
       return float("nan")




def _normalize_daily_to_standard(df_in: pd.DataFrame) -> pd.DataFrame:
   """
   Accepts a DataFrame with any of:
     Date / date, Open / open, High, Low, Close or Close/Last, Volume
   Returns DataFrame with columns: date,time,open,high,low,close,volume,ts
   """
   df = df_in.copy()


   # Unify column names (case-insensitive)
   lower = {c.lower(): c for c in df.columns}
   def pick(*opts):
       for o in opts:
           if o.lower() in lower: return lower[o.lower()]
       return None


   c_date  = pick("date")
   c_open  = pick("open", "open price", "open/last")
   c_high  = pick("high")
   c_low   = pick("low")
   c_close = pick("close", "adj. close", "close/last")
   c_clast = pick("close/last")
   c_vol   = pick("volume", "sharevolume", "shares")


   # If "Close/Last" exists, prefer it
   if c_clast and (not c_close or c_clast != c_close):
       df["__close_pref__"] = df[c_clast]
       c_close = "__close_pref__"


   # Build normalized frame
   out = pd.DataFrame()
   out["date"] = pd.to_datetime(df[c_date], errors="coerce").dt.date.astype("string") if c_date else pd.Series(dtype="string")
   out["open"] = df[c_open].map(_clean_num)   if c_open  else float("nan")
   out["high"] = df[c_high].map(_clean_num)   if c_high  else float("nan")
   out["low"]  = df[c_low ].map(_clean_num)   if c_low   else float("nan")
   out["close"]= df[c_close].map(_clean_num)  if c_close else float("nan")
   if c_vol:
       out["volume"] = pd.to_numeric(df[c_vol].map(lambda v: str(v).replace(",", "").strip()), errors="coerce").fillna(0)
   else:
       out["volume"] = 0


   out = out.dropna(subset=["date"])
   out["time"] = DEFAULT_TIME_FOR_DAILY
   out["ts"]   = pd.to_datetime(out["date"] + " " + out["time"], utc=True)


   # Order & dtypes
   out = out[STANDARD_COLS].sort_values(["date", "time"]).reset_index(drop=True)
   return out




def _read_existing_standard(path: Path) -> pd.DataFrame:
   if not path.exists():
       return pd.DataFrame(columns=STANDARD_COLS)
   cur = pd.read_csv(path)
   # If already in standard schema, ensure ts exists & dtype is good; else normalize.
   if {"date","time","open","high","low","close","volume"}.issubset(set(cur.columns)):
       if "ts" not in cur.columns:
           cur["ts"] = pd.to_datetime(cur["date"] + " " + cur["time"], utc=True)
       else:
           cur["ts"] = pd.to_datetime(cur["ts"], errors="coerce", utc=True)
       cur["volume"] = pd.to_numeric(cur["volume"], errors="coerce").fillna(0)
       return cur[STANDARD_COLS].dropna(subset=["date"]).reset_index(drop=True)
   else:
       # Old Nasdaq-style columns
       return _normalize_daily_to_standard(cur)




def _append_and_save_standard(target: Path, new_rows_raw: pd.DataFrame) -> tuple[int, int]:
   old = _read_existing_standard(target)
   new_std = _normalize_daily_to_standard(new_rows_raw)
   both = pd.concat([old, new_std], ignore_index=True)
   # Daily candles → dedupe by date (if you later ingest intraday, switch to ["ts"])
   both = (both
           .dropna(subset=["date"])
           .drop_duplicates(subset=["date"], keep="last")
           .sort_values(["date","time"])
           .reset_index(drop=True))
   added = len(both) - len(old)
   _ensure_dir(target.parent)
   tmp = target.with_suffix(".tmp.csv")
   both.to_csv(tmp, index=False)
   tmp.replace(target)
   return added, len(both)
