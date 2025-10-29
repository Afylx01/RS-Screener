
import logging
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from pathlib import Path

# Assuming config.py is in the parent directory
from config import DELIVERY_SCAN_CONFIG, DELIVERY_DATA_DIR

log = logging.getLogger(__name__)

def ensure_dir(path: Path):
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def download_bhavcopy_for_date(date: datetime) -> tuple[Path | None, bool]:
    """
    Downloads the bhavcopy for a specific date from NSE archives.
    Caches the file locally to avoid re-downloads.
    """
    date_str = date.strftime('%d%m%Y')
    filename = f"sec_bhavdata_full_{date_str}.csv"
    local_path = DELIVERY_DATA_DIR / filename

    # Check cache first
    if local_path.exists():
        log.info(f"Found cached bhavcopy for {date.date()} at '{local_path}'")
        return local_path, True

    # Download if not in cache
    url = DELIVERY_SCAN_CONFIG['bhavcopy_base_url'].format(date=date_str)
    headers = {"User-Agent": DELIVERY_SCAN_CONFIG['user_agent']}
    timeout = DELIVERY_SCAN_CONFIG['timeout']

    try:
        log.info(f"Downloading bhavcopy for {date.date()} from {url}...")
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and resp.content:
            ensure_dir(DELIVERY_DATA_DIR)
            with open(local_path, "wb") as f:
                f.write(resp.content)
            log.info(f"Successfully downloaded and cached '{filename}'")
            return local_path, True
        else:
            log.warning(f"No data file available for {date.date()} (HTTP Status: {resp.status_code})")
            return None, False
    except requests.RequestException as e:
        log.error(f"Failed to fetch data from {url}: {e}")
        return None, False

def collect_last_n_trading_days(n: int, target_date: datetime) -> list[Path]:
    """
    Collects the file paths for the last N available trading days,
    starting from the target date and going backwards.
    """
    collected_paths = []
    days_checked = 0
    current_date = target_date

    while len(collected_paths) < n and days_checked < (n * 2 + 10): # Safety break
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date -= timedelta(days=1)
            days_checked += 1
            continue

        local_path, success = download_bhavcopy_for_date(current_date)
        if success and local_path:
            collected_paths.append(local_path)

        current_date -= timedelta(days=1)
        days_checked += 1

    if len(collected_paths) < n:
        log.warning(f"Could only collect {len(collected_paths)} of the required {n} trading day files.")

    log.info(f"Collected {len(collected_paths)} bhavcopy files for analysis.")
    return collected_paths

def read_and_clean_bhavcopy(csv_path: Path) -> pd.DataFrame | None:
    """
    Reads and cleans a single NSE bhavcopy CSV file into a DataFrame.
    Handles multiple potential encodings and separators for robustness.
    """
    log.info(f"Processing and cleaning '{csv_path.name}'...")
    # List of attempts to read the CSV with different settings
    read_attempts = [
        {"encoding": "utf-8", "sep": ","},
        {"encoding": "latin1", "sep": ","},
    ]
    df = None
    for opt in read_attempts:
        try:
            df = pd.read_csv(csv_path, **opt, engine="python")
            break
        except Exception:
            continue

    if df is None:
        log.error(f"Failed to read and parse the CSV file: {csv_path}")
        return None

    # Normalize column names (all uppercase, stripped of whitespace)
    df.columns = [c.strip().upper() for c in df.columns]

    # --- Data Validation and Cleaning ---
    # Ensure required columns are present
    required_cols = ["SYMBOL", "SERIES", "CLOSE_PRICE", "PREV_CLOSE", "DELIV_QTY"]
    if not all(col in df.columns for col in required_cols):
        log.error(f"File {csv_path.name} is missing one or more required columns.")
        return None

    # Standardize the date column
    date_col_options = ["DATE1", "DATE", "TIMESTAMP"]
    date_col = next((col for col in date_col_options if col in df.columns), None)
    if date_col:
        df["DATE"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    else:
        log.error(f"No recognizable date column found in {csv_path.name}.")
        return None

    # Filter for the 'EQ' series, which represents regular equity
    df = df[df["SERIES"].str.strip().str.upper() == "EQ"].copy()

    # Convert key numeric columns to numeric types
    numeric_cols = [
        "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
        "LAST_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY", "DELIV_QTY"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors='coerce')

    # Select and rename columns for consistency
    final_cols = {
        "SYMBOL": "symbol",
        "DATE": "date",
        "CLOSE_PRICE": "close",
        "PREV_CLOSE": "prev_close",
        "DELIV_QTY": "delivery_qty",
        "DELIV_PER": "delivery_perc",
    }
    df = df[final_cols.keys()].rename(columns=final_cols)

    # Drop rows with critical missing data
    df.dropna(subset=['symbol', 'date', 'close', 'delivery_qty'], inplace=True)

    log.info(f"Successfully cleaned '{csv_path.name}', found {len(df)} valid 'EQ' rows.")
    return df

def get_db_engine():
    """Returns the SQLAlchemy engine for the SQLite database."""
    db_path = DELIVERY_DATA_DIR / DELIVERY_SCAN_CONFIG['sqlite_db_name']
    return create_engine(f"sqlite:///{db_path}")

def persist_to_sqlite(df: pd.DataFrame):
    """Saves a DataFrame of cleaned bhavcopy data to the SQLite database."""
    if df.empty:
        return
    engine = get_db_engine()
    try:
        with engine.begin() as conn:
            # Append data and create an index for faster queries
            df.to_sql("daily_bhav", conn, if_exists="append", index=False)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_date ON daily_bhav (symbol, date)")
        log.info(f"Persisted {len(df)} rows to the 'daily_bhav' table.")
    except Exception as e:
        log.error(f"Failed to persist data to SQLite database: {e}")

def deduplicate_database():
    """
    Removes duplicate entries from the database, keeping the one with the highest
    delivery quantity for any given symbol on a specific date.
    """
    log.info("Deduplicating the 'daily_bhav' table to ensure data integrity...")
    engine = get_db_engine()
    try:
        # Read the entire table
        df = pd.read_sql_table("daily_bhav", engine)
        if df.empty:
            return

        # Sort by delivery_qty descending and drop duplicates
        df_sorted = df.sort_values(["symbol", "date", "delivery_qty"], ascending=[True, True, False])
        df_dedup = df_sorted.drop_duplicates(subset=["symbol", "date"], keep="first")

        # Overwrite the table with the deduplicated data
        with engine.begin() as conn:
            df_dedup.to_sql("daily_bhav", conn, if_exists="replace", index=False)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_date ON daily_bhav (symbol, date)")

        log.info(f"Deduplication complete. Original rows: {len(df)}, Final rows: {len(df_dedup)}")
    except Exception as e:
        # This can happen if the table doesn't exist yet, which is fine
        if "no such table" in str(e).lower():
            log.info("'daily_bhav' table not found for deduplication, skipping.")
        else:
            log.error(f"Error during database deduplication: {e}")

def prepare_database_for_date(target_date: datetime):
    """
    Main orchestration function for the data handler.
    It downloads, cleans, and persists all necessary data up to the target date.
    """
    log.info("--- Starting Bhavcopy Data Preparation ---")
    days_to_fetch = DELIVERY_SCAN_CONFIG['days_back']

    # 1. Collect file paths of recent bhavcopies
    bhavcopy_paths = collect_last_n_trading_days(days_to_fetch, target_date)

    # 2. Clean and persist each file
    for path in bhavcopy_paths:
        cleaned_df = read_and_clean_bhavcopy(path)
        if cleaned_df is not None and not cleaned_df.empty:
            persist_to_sqlite(cleaned_df)

    # 3. Deduplicate the entire database to ensure it's clean
    deduplicate_database()

    log.info("--- Bhavcopy Data Preparation Complete ---")
