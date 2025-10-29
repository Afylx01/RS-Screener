import logging
from datetime import datetime
import pandas as pd
import sys

# Import project modules
from config import SCAN_CONFIG, LOG_LEVEL, LOG_FORMAT
from data_loader import get_stock_symbols, download_all_data, load_all_data, download_stock_data
from indicator_engine import run_indicator_calculation
from scanner import run_scan
from reporter import format_results, save_results, print_top_results

# --- Logging Configuration ---
# Configure logging to provide informative and clean terminal output
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, stream=sys.stdout)
log = logging.getLogger(__name__)

# --- UI and Display Functions ---
def display_banner():
    """Prints the application's welcome banner."""
    print("\n" + "="*60)
    print(" Ultra-Fast RS55 Scanner – TradingView-Accurate Edition (v2.2.0)")
    print("="*60)

def get_date_input(benchmark_data):
    """
    Manages the interactive user menu for selecting the scan date(s).
    """
    while True:
        print("\n" + "="*50)
        print("📅 DATE SELECTION MENU")
        print("="*50)
        print("1. Single Date (e.g., 150124 for 15-Jan-2024)")
        print("2. Date Range (e.g., 010124 150124 for Jan 1-15, 2024)")
        print("3. Last N Days (e.g., 5 for last 5 trading days)")
        print("4. Latest Available (most recent trading day)")
        print("5. Yesterday (previous trading day)")
        print("6. Today (current day - if market has closed)")
        print("="*50)

        choice = input("Enter your choice (1-6): ").strip()

        try:
            latest_date = benchmark_data.index.max().to_pydatetime()
            if choice == '1':
                date_str = input("Enter date (ddmmyy): ")
                return [datetime.strptime(date_str, '%d%m%y')]
            elif choice == '2':
                start_str, end_str = input("Enter start and end dates (ddmmyy ddmmyy): ").split()
                start_date = datetime.strptime(start_str, '%d%m%y')
                end_date = datetime.strptime(end_str, '%d%m%y')
                return pd.date_range(start_date, end_date).to_pydatetime().tolist()
            elif choice == '3':
                n_days = int(input("Enter number of days: "))
                return benchmark_data.index[-n_days:].to_pydatetime().tolist()
            elif choice == '4':
                return [latest_date]
            elif choice == '5':
                return [benchmark_data.index[-2].to_pydatetime()]
            elif choice == '6':
                today = datetime.now()
                if today.hour < 16: # Check if market might still be open
                    log.warning("Market may still be open. Using yesterday's data for consistency.")
                    return [benchmark_data.index[-2].to_pydatetime()]
                return [latest_date]
            else:
                log.error("Invalid choice. Please enter a number between 1 and 6.")
        except (ValueError, IndexError) as e:
            log.error(f"Invalid input: {e}. Please ensure the format is correct.")

# --- Main Application Workflow ---
def main():
    """
    Orchestrates the entire scanning process from data download to reporting.
    """
    display_banner()

    # Step 1: Initial data download and caching
    symbols = get_stock_symbols()
    if not symbols:
        log.error("Could not retrieve stock symbols. Exiting.")
        return

    log.info("Ensuring the NIFTY benchmark is cached...")
    download_stock_data(SCAN_CONFIG['benchmark_symbol'], SCAN_CONFIG['cache_days'])
    download_all_data(symbols)

    # Main application loop
    while True:
        # Step 2: Load all required data from the cache
        all_stock_data, market_caps = load_all_data(symbols)
        benchmark_stock_data, _ = load_all_data([SCAN_CONFIG['benchmark_symbol']])

        if SCAN_CONFIG['benchmark_symbol'] not in benchmark_stock_data:
            log.error("Critical: Failed to load NIFTY benchmark data. Cannot proceed.")
            return

        if not all_stock_data:
            log.error("No stock data could be loaded from the cache. Exiting.")
            return

        benchmark_data = benchmark_stock_data[SCAN_CONFIG['benchmark_symbol']]

        # Step 3: Get user input for the desired scan dates
        scan_dates = get_date_input(benchmark_data)
        if not scan_dates:
            continue

        # Step 4: Run the computationally intensive indicator calculations
        log.info("Starting indicator calculation for all stocks...")
        processed_data = run_indicator_calculation(all_stock_data, benchmark_data)

        # Step 5: Execute the scan for each selected date
        all_results = []
        for scan_date in scan_dates:
            log.info(f"Running scan for date: {scan_date.strftime('%Y-%m-%d')}...")
            results_df = run_scan(processed_data, market_caps, scan_date)
            if not results_df.empty:
                all_results.append(results_df)

        # Step 6: Consolidate, format, and report the results
        if all_results:
            final_results = pd.concat(all_results, ignore_index=True)
            formatted_results = format_results(final_results)
            print_top_results(formatted_results)
            save_results(formatted_results, scan_dates[-1])
        else:
            log.info("No stocks were found that matched the scanning criteria for the selected date(s).")

        # Step 7: Prompt user to run another scan or exit
        another_scan = input("\nDo you want to run another scan? (y/n): ").strip().lower()
        if another_scan != 'y':
            log.info("Exiting scanner. Goodbye!")
            break

if __name__ == "__main__":
    main()
