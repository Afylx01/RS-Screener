
import logging
import pandas as pd
from datetime import datetime, date as datetime_date
from sqlalchemy import create_engine
from config import DELIVERY_SCAN_CONFIG, DELIVERY_DATA_DIR

log = logging.getLogger(__name__)

def get_db_engine():
    """Returns the SQLAlchemy engine for the SQLite database."""
    db_path = DELIVERY_DATA_DIR / DELIVERY_SCAN_CONFIG['sqlite_db_name']
    return create_engine(f"sqlite:///{db_path}")

def calculate_average_delivery_prior_days(target_date: datetime_date) -> pd.DataFrame:
    """
    Calculates the average delivery quantity for the 5 trading days
    immediately preceding the target date for each symbol.
    """
    log.info(f"Calculating 5-day prior average delivery for target date: {target_date}...")
    engine = get_db_engine()

    try:
        # Load all data prior to the target date
        query = f"SELECT symbol, date, delivery_qty FROM daily_bhav WHERE date < '{target_date}'"
        df_prior = pd.read_sql(query, engine, parse_dates=['date'])

        if df_prior.empty:
            log.warning("No historical data found to calculate 5-day average delivery.")
            return pd.DataFrame(columns=["symbol", "avg_delivery_5d_prior"])

        # For each symbol, get the last 5 distinct trading days and average the delivery
        avg_deliveries = (
            df_prior.sort_values('date', ascending=False)
            .groupby('symbol')
            .head(5)
            .groupby('symbol')['delivery_qty']
            .mean()
            .reset_index()
        )
        avg_deliveries.rename(columns={"delivery_qty": "avg_delivery_5d_prior"}, inplace=True)

        log.info(f"Successfully calculated 5-day prior averages for {len(avg_deliveries)} symbols.")
        return avg_deliveries

    except Exception as e:
        if "no such table" in str(e).lower():
            log.error("The 'daily_bhav' table does not exist. Cannot calculate averages.")
        else:
            log.error(f"An error occurred while calculating prior day averages: {e}")
        return pd.DataFrame(columns=["symbol", "avg_delivery_5d_prior"])

def create_scan_snapshot(target_date: datetime_date) -> pd.DataFrame:
    """
    Creates a snapshot of all stocks for the target date, merging it with
    the calculated 5-day prior average delivery quantities.
    """
    log.info(f"Creating data snapshot for target date: {target_date}...")
    engine = get_db_engine()

    try:
        # Get all data for the target date
        query = f"SELECT * FROM daily_bhav WHERE date = '{target_date}'"
        df_snapshot = pd.read_sql(query, engine, parse_dates=['date'])

        if df_snapshot.empty:
            log.warning(f"No data available in the database for the target date: {target_date}")
            return pd.DataFrame()

        # Get the 5-day prior averages
        df_avg_delivery = calculate_average_delivery_prior_days(target_date)

        # Merge the snapshot with the averages
        df_merged = pd.merge(df_snapshot, df_avg_delivery, on="symbol", how="left")

        # --- Calculate Key Scanning Metrics ---
        # 1. Percentage change from previous day's close
        df_merged["pct_change"] = ((df_merged["close"] - df_merged["prev_close"]) / df_merged["prev_close"]) * 100

        # 2. Delivery multiple (how many times today's delivery is compared to the average)
        df_merged["delivery_times"] = df_merged["delivery_qty"] / df_merged["avg_delivery_5d_prior"]

        # 3. Delivery value in Crores for better context
        df_merged["delivery_value_cr"] = (df_merged["delivery_qty"] * df_merged["close"]) / 1_00_00_000

        log.info(f"Snapshot created with {len(df_merged)} symbols for {target_date}.")
        return df_merged

    except Exception as e:
        if "no such table" in str(e).lower():
            log.error("The 'daily_bhav' table does not exist. Cannot create a snapshot.")
        else:
            log.error(f"An error occurred while creating the scan snapshot: {e}")
        return pd.DataFrame()

def apply_initial_filters(df_snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Applies the core delivery-based filters based on the settings in config.py.
    """
    if df_snapshot.empty:
        return df_snapshot

    log.info("Applying initial delivery and price filters...")
    initial_count = len(df_snapshot)

    # --- Filtering Logic ---
    # Filter 1: Minimum delivery quantity
    min_qty = DELIVERY_SCAN_CONFIG['min_delivery_quantity']
    df_filtered = df_snapshot[df_snapshot["delivery_qty"].fillna(0) >= min_qty]
    log.info(f"Filter 'min_delivery_quantity' >= {min_qty}: {initial_count} -> {len(df_filtered)} stocks")

    # Filter 2: Minimum percentage price change
    min_change = DELIVERY_SCAN_CONFIG['min_percent_change']
    df_filtered = df_filtered[df_filtered["pct_change"].fillna(-100) > min_change]
    log.info(f"Filter 'min_percent_change' > {min_change}%: {len(df_filtered)} stocks remaining")

    # Filter 3: Minimum delivery multiple
    min_times = DELIVERY_SCAN_CONFIG['min_delivery_times']
    df_filtered = df_filtered[df_filtered["delivery_times"].fillna(0) >= min_times]
    log.info(f"Filter 'delivery_times' >= {min_times}x: {len(df_filtered)} stocks remaining")

    # Filter 4: Ensure the average delivery calculation was successful
    df_filtered = df_filtered[df_filtered["avg_delivery_5d_prior"].notna()]
    log.info(f"Filter 'valid_avg_delivery': {len(df_filtered)} stocks remaining")

    final_count = len(df_filtered)
    log.info(f"Initial filtering complete. Total stocks passed: {final_count} out of {initial_count}")

    return df_filtered.copy()

def run_delivery_scan_core(target_date: datetime) -> pd.DataFrame:
    """
    Main orchestration function for the core delivery scan logic.
    """
    log.info("--- Starting Core Delivery Scan Analysis ---")

    # Ensure the date is in the correct format
    scan_date = target_date.date()

    # 1. Create the snapshot for the target date
    df_snapshot = create_scan_snapshot(scan_date)

    # 2. Apply the initial filters to get the preliminary list
    df_filtered = apply_initial_filters(df_snapshot)

    log.info("--- Core Delivery Scan Analysis Complete ---")

    return df_filtered
