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

    processed_data = run_indicator_calculation(all_stock_data, benchmark_data[SCAN_CONFIG['benchmark_symbol']])

    scan_date = benchmark_data[SCAN_CONFIG['benchmark_symbol']].index.max()
    log.info(f"Running initial scan for the latest available date: {scan_date.strftime('%Y-%m-%d')}")
    results_df = run_scan(processed_data, market_caps, scan_date)

    if not results_df.empty:
        formatted_results = format_results(results_df)
        print_top_results(formatted_results)
        save_results(formatted_results, scan_date)
    else:
        log.info("No stocks found matching the initial scan criteria.")

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

    log.info(f"Found {len(symbols_to_scan)} symbols. Fetching full historical data...")
    download_all_data(symbols_to_scan)
    market_data, _ = load_all_data(symbols_to_scan)

    scanner = AdvancedScanner(portfolio_value=1000000, risk_per_trade=0.01) # Example values
    df_advanced_results = scanner.run_advanced_scan(market_data, rs_lookup)

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
