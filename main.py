import logging
import sys
import os
import glob
from datetime import datetime
import pandas as pd
from config import SCAN_CONFIG, LOG_LEVEL, LOG_FORMAT
from data_loader import get_stock_symbols, download_all_data, load_all_data
from indicator_engine import run_indicator_calculation
from scanner import run_scan
from reporter import format_results, save_results, print_top_results, save_advanced_scan_results, display_advanced_summary
from advanced_scanner import AdvancedScanner

# --- Logging Configuration ---
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, stream=sys.stdout)
log = logging.getLogger(__name__)

# --- UI and Display Functions ---
def display_banner():
    """Prints the application's welcome banner."""
    print("\n" + "="*60)
    print(" Ultra-Fast RS55 Scanner & Advanced Analyzer (v3.0)")
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

def run_initial_scan():
    """Orchestrates the initial RS55 scan."""
    symbols = get_stock_symbols()
    if not symbols:
        log.error("Could not retrieve stock symbols. Exiting.")
        return

    download_all_data(symbols + [SCAN_CONFIG['benchmark_symbol']])
    all_stock_data, market_caps = load_all_data(symbols)
    benchmark_data, _ = load_all_data([SCAN_CONFIG['benchmark_symbol']])
    if SCAN_CONFIG['benchmark_symbol'] not in benchmark_data:
        log.error("Critical: Failed to load NIFTY benchmark data. Cannot proceed.")
        return

    scan_dates = get_date_input(benchmark_data[SCAN_CONFIG['benchmark_symbol']])
    if not scan_dates:
        return

    processed_data = run_indicator_calculation(all_stock_data, benchmark_data[SCAN_CONFIG['benchmark_symbol']])

    all_results = []
    for scan_date in scan_dates:
        log.info(f"Running scan for date: {scan_date.strftime('%Y-%m-%d')}...")
        results_df = run_scan(processed_data, market_caps, scan_date)
        if not results_df.empty:
            all_results.append(results_df)

    if all_results:
        final_results = pd.concat(all_results, ignore_index=True)
        formatted_results = format_results(final_results)
        print_top_results(formatted_results)
        save_results(formatted_results, scan_dates[-1])
    else:
        log.info("No stocks were found that matched the scanning criteria for the selected date(s).")

def run_advanced_scan():
    """Orchestrates the advanced HHHL + ADX scan on an existing output file."""
    log.info("Searching for initial scan results in the 'results/' directory...")
    result_files = glob.glob('results/RS55_Scan_*.xlsx')
    if not result_files:
        log.error("No initial scan result files found. Please run the 'RS55 Scan' first.")
        return

    print("\n--- Please select an input file for the advanced scan ---")
    for i, f in enumerate(result_files):
        print(f"{i+1}. {os.path.basename(f)}")

    try:
        choice = int(input("Enter file number: ")) - 1
        input_file = result_files[choice]
    except (ValueError, IndexError):
        log.error("Invalid selection.")
        return

    log.info(f"Loading symbols from '{os.path.basename(input_file)}'...")
    df_input = pd.read_excel(input_file, engine='openpyxl')
    symbols_to_scan = (df_input['Symbol'] + ".NS").tolist()
    rs_lookup = dict(zip(df_input['Symbol'], df_input['RS55_Today']))
    scan_date = pd.to_datetime(df_input['Date'].iloc[0]).tz_localize('Asia/Kolkata')

    log.info(f"Found {len(symbols_to_scan)} symbols. Fetching full historical data up to {scan_date.strftime('%Y-%m-%d')}...")
    # We need to download data up to the scan date, not today's date.
    # The download_all_data function uses a fixed period, which is fine,
    # as we will filter the data later.
    download_all_data(symbols_to_scan)
    market_data, _ = load_all_data(symbols_to_scan)

    scanner = AdvancedScanner(portfolio_value=1000000, risk_per_trade=0.01) # Example values
    df_advanced_results = scanner.run_advanced_scan(market_data, rs_lookup, scan_date)

    if not df_advanced_results.empty:
        df_signals = df_advanced_results[df_advanced_results['tradeable'] == True].head(5)
        df_signals['rank'] = range(1, len(df_signals) + 1)

        save_advanced_scan_results(df_advanced_results, df_signals, input_file)
        display_advanced_summary(df_advanced_results, df_signals, scanner.portfolio_value)
    else:
        log.info("No stocks passed the advanced scanning criteria.")


# --- Main Application Workflow ---
def main():
    """Main menu and application entry point."""
    while True:
        display_banner()
        print("\n--- MAIN MENU ---")
        print("1. Run Initial RS55 Scan")
        print("2. Run Advanced HHHL Analysis on Scan Output")
        print("3. Exit")

        choice = input("Enter your choice (1-3): ").strip()

        if choice == '1':
            run_initial_scan()
        elif choice == '2':
            run_advanced_scan()
        elif choice == '3':
            log.info("Exiting scanner. Goodbye!")
            break
        else:
            log.error("Invalid choice. Please enter a number between 1 and 3.")

        input("\nPress Enter to return to the main menu...")

if __name__ == "__main__":
    main()
