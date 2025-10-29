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
from reporter import (
    format_results, save_results, print_top_results,
    save_advanced_scan_results, display_advanced_summary,
    save_delivery_scan_results, send_telegram_report
)
from advanced_scanner import AdvancedScanner
# --- Delivery Scanner Imports ---
from delivery_scanner.data_handler import prepare_database_for_date
from delivery_scanner.scanner import run_delivery_scan_core
from delivery_scanner.enrichment import enrich_and_final_filter

# --- Logging Configuration ---
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, stream=sys.stdout)
log = logging.getLogger(__name__)

# --- UI and Display Functions ---
def display_banner():
    """Prints the application's welcome banner."""
    print("\n" + "="*60)
    print(" Ultra-Fast RS55 Scanner & Advanced Analyzer (v3.1)")
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
            latest_date = benchmark_data.index.max().tz_convert('Asia/Kolkata')
            def make_tz_aware(dt):
                return pd.to_datetime(dt).tz_localize('Asia/Kolkata')

            if choice == '1':
                date_str = input("Enter date (ddmmyy): ")
                return [make_tz_aware(datetime.strptime(date_str, '%d%m%y'))]
            elif choice == '2':
                start_str, end_str = input("Enter start and end dates (ddmmyy ddmmyy): ").split()
                start_date = datetime.strptime(start_str, '%d%m%y')
                end_date = datetime.strptime(end_str, '%d%m%y')
                return [make_tz_aware(d) for d in pd.date_range(start_date, end_date)]
            elif choice == '3':
                n_days = int(input("Enter number of days: "))
                return benchmark_data.index[-n_days:].tz_convert('Asia/Kolkata').to_pydatetime().tolist()
            elif choice == '4':
                return [latest_date]
            elif choice == '5':
                return [benchmark_data.index[-2].tz_convert('Asia/Kolkata')]
            elif choice == '6':
                today = datetime.now()
                if today.hour < 16:
                    log.warning("Market may still be open. Using yesterday's data for consistency.")
                    return [benchmark_data.index[-2].tz_convert('Asia/Kolkata')]
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

def run_delivery_scan():
    """Orchestrates the complete High-Delivery scan workflow."""
    # Since this scan depends on bhavcopy, it needs a single target date.
    # We can use the existing menu but will only use the LATEST selected date.
    log.info("Preparing for High-Delivery Scan. Please select a target date.")

    # We need a benchmark to use the date selection menu, even if it's not used for RS calculations here.
    try:
        _, benchmark_data = load_all_data([SCAN_CONFIG['benchmark_symbol']])
        scan_dates = get_date_input(benchmark_data[SCAN_CONFIG['benchmark_symbol']])
        if not scan_dates:
            return
        target_date = scan_dates[-1] # Use the latest date from the selection
        log.info(f"High-Delivery Scan will run for the target date: {target_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        log.error(f"Could not prepare dates for the scan. Please run the initial RS55 scan first to cache data. Error: {e}")
        return

    # 1. Prepare the database (downloads, cleans, persists bhavcopy data)
    prepare_database_for_date(target_date)

    # 2. Run the core scanner to get the initially filtered list
    df_filtered = run_delivery_scan_core(target_date)

    # 3. Run the enrichment process (technicals, market cap) and final filter
    df_final = enrich_and_final_filter(df_filtered)

    # 4. Save results and send notifications
    if not df_final.empty:
        # Sort by delivery times for the final report
        df_final = df_final.sort_values('delivery_times', ascending=False)

        output_file_path = save_delivery_scan_results(df_final, target_date)

        if output_file_path:
            caption = f"High-Delivery Stock Scan Results for {target_date.strftime('%d-%b-%Y')}. Found {len(df_final)} stocks."
            send_telegram_report(output_file_path, caption)

            # 5. Prompt for advanced scan chaining
            run_advanced = input("\nDo you want to run the Advanced HHHL Analysis on these results? (y/n): ").strip().lower()
            if run_advanced == 'y':
                # Manually trigger the advanced scan with the new file
                run_advanced_scan_on_file(output_file_path)
    else:
        log.info("No stocks were found that matched the high-delivery scanning criteria.")

def run_advanced_scan_on_file(input_file: str):
    """A modified version of run_advanced_scan that takes a file path directly."""
    try:
        portfolio_value = float(input("Enter portfolio value (e.g., 1000000): ") or "1000000")
        risk_per_trade = float(input("Enter risk per trade %% (e.g., 1 for 1%%): ") or "1") / 100
    except ValueError:
        log.error("Invalid input. Using default portfolio values.")
        portfolio_value = 1000000
        risk_per_trade = 0.01

    log.info(f"Loading symbols from '{os.path.basename(input_file)}'...")
    # The delivery scanner uses 'symbol', not 'Symbol'
    df_input = pd.read_excel(input_file, engine='openpyxl')
    if 'symbol' not in df_input.columns:
        log.error("The input file is missing the required 'symbol' column.")
        return

    symbols_to_scan = (df_input['symbol'] + ".NS").tolist()
    # The delivery scanner has 'rs', not 'RS55_Today'
    rs_lookup = dict(zip(df_input['symbol'], df_input['rs']))
    scan_date = pd.to_datetime(df_input['date'].iloc[0]).tz_localize('Asia/Kolkata')

    log.info(f"Found {len(symbols_to_scan)} symbols. Fetching full historical data up to {scan_date.strftime('%Y-%m-%d')}...")
    download_all_data(symbols_to_scan)
    market_data, _ = load_all_data(symbols_to_scan)

    scanner = AdvancedScanner(portfolio_value=portfolio_value, risk_per_trade=risk_per_trade)
    df_advanced_results = scanner.run_advanced_scan(market_data, rs_lookup, scan_date)

    if not df_advanced_results.empty:
        # Clean the symbol format before saving and displaying
        df_advanced_results['symbol'] = df_advanced_results['symbol'].str.replace(".NS", "")
        df_signals = df_advanced_results[df_advanced_results['tradeable'] == True].head(5)
        df_signals['rank'] = range(1, len(df_signals) + 1)

        save_advanced_scan_results(df_advanced_results, df_signals, input_file)
        display_advanced_summary(df_advanced_results, df_signals, scanner.portfolio_value)
    else:
        log.info("No stocks passed the advanced scanning criteria.")

def run_advanced_scan():
    """Orchestrates the advanced HHHL + ADX scan on an existing output file."""
    log.info("Searching for scan result files in 'results/' and 'delivery_scanner_results/'...")

    # Look in both directories for potential input files
    rs55_files = sorted(glob.glob('results/RS55_Scan_*.xlsx'), reverse=True)
    delivery_files = sorted(glob.glob('delivery_scanner_results/High_Delivery_Scan_*.xlsx'), reverse=True)

    all_files = rs55_files + delivery_files
    if not all_files:
        log.error("No scan result files found. Please run a scan first.")
        return

    print("\n--- Please select an input file for the advanced scan ---")
    for i, f_path in enumerate(all_files[:15]): # Show latest 15 files
        print(f"{i+1}. {os.path.basename(f_path)}")

    try:
        choice = int(input(f"Enter file number (1-{len(all_files[:15])}): ")) - 1
        if not (0 <= choice < len(all_files[:15])):
            raise IndexError
        input_file = all_files[choice]
        run_advanced_scan_on_file(input_file)
    except (ValueError, IndexError):
        log.error("Invalid selection.")
        return

# --- Main Application Workflow ---
def main():
    """Main menu and application entry point."""
    while True:
        display_banner()
        print("\n--- MAIN MENU ---")
        print("1. Run Initial RS55 Scan")
        print("2. Run High-Delivery Scan")
        print("3. Run Advanced HHHL Analysis on Scan Output")
        print("4. Exit")

        choice = input("Enter your choice (1-4): ").strip()

        if choice == '1':
            run_initial_scan()
        elif choice == '2':
            run_delivery_scan()
        elif choice == '3':
            run_advanced_scan()
        elif choice == '4':
            log.info("Exiting scanner. Goodbye!")
            break
        else:
            log.error("Invalid choice. Please enter a number between 1 and 4.")

        input("\nPress Enter to return to the main menu...")

if __name__ == "__main__":
    main()
