from datetime import datetime, timedelta
import pandas as pd

from config import SCAN_CONFIG
from data_loader import get_stock_symbols, download_all_data, load_all_data, align_benchmark_data, download_stock_data
from indicator_engine import run_indicator_calculation
from scanner import run_scan
from reporter import format_results, save_results, print_top_results

def display_banner():
    """Prints the application banner."""
    print("================================================")
    print(" Ultra-Fast RS55 Scanner – TradingView-Accurate Edition (v2.2.0)")
    print("================================================")

def get_date_input(benchmark_data):
    """Handles user input for date selection."""
    while True:
        print("\n" + "="*50)
        print("📅 DATE SELECTION MENU")
        print("="*50)
        print("1. Single Date (e.g., 150124 for 15-Jan-2024)")
        print("2. Date Range (e.g., 010124 150124 for Jan 1-15, 2024)")
        print("3. Last N Days (e.g., 5 for last 5 trading days)")
        print("4. Latest Available (most recent trading day)")
        print("5. Yesterday (previous trading day)")
        print("6. Today (current day - if market closed)")
        print("="*50)

        choice = input("Enter your choice (1-6): ").strip()

        try:
            latest_date = benchmark_data.index.max().to_pydatetime()
            if choice == '1':
                date_str = input("Enter date (ddmmyy): ")
                scan_dates = [datetime.strptime(date_str, '%d%m%y')]
                return scan_dates
            elif choice == '2':
                start_str, end_str = input("Enter start and end dates (ddmmyy ddmmyy): ").split()
                start_date = datetime.strptime(start_str, '%d%m%y')
                end_date = datetime.strptime(end_str, '%d%m%y')
                scan_dates = pd.date_range(start_date, end_date).to_pydatetime().tolist()
                return scan_dates
            elif choice == '3':
                n_days = int(input("Enter number of days: "))
                scan_dates = benchmark_data.index[-n_days:].to_pydatetime().tolist()
                return scan_dates
            elif choice == '4':
                return [latest_date]
            elif choice == '5':
                return [benchmark_data.index[-2].to_pydatetime()]
            elif choice == '6':
                today = datetime.now()
                if today.hour < 16: # Market might still be open
                    print("Warning: Market may still be open. Using yesterday's data.")
                    return [benchmark_data.index[-2].to_pydatetime()]
                return [latest_date]
            else:
                print("Invalid choice. Please enter a number between 1 and 6.")
        except (ValueError, IndexError) as e:
            print(f"Invalid input: {e}. Please try again.")

def main():
    display_banner()

    # 1. Initial data download
    print("Fetching symbol list...")
    symbols = get_stock_symbols()
    print(f"Found {len(symbols)} symbols. Downloading data...")
    download_stock_data(SCAN_CONFIG['benchmark_symbol'], SCAN_CONFIG['cache_days']) # Ensure benchmark is downloaded
    download_all_data(symbols)

    while True:
        # 2. Load data from cache
        print("\nLoading data from cache...")
        all_stock_data, market_caps = load_all_data(symbols)
        benchmark_stock_data, _ = load_all_data([SCAN_CONFIG['benchmark_symbol']])
        if SCAN_CONFIG['benchmark_symbol'] not in benchmark_stock_data:
            print("Failed to load benchmark data. Exiting.")
            return
        benchmark_data = benchmark_stock_data[SCAN_CONFIG['benchmark_symbol']]

        if not all_stock_data:
            print("No data loaded. Exiting.")
            return

        # 3. Get user input for dates
        scan_dates = get_date_input(benchmark_data)

        # 4. Calculate indicators
        print("\nCalculating indicators...")
        processed_data = run_indicator_calculation(all_stock_data, benchmark_data)

        # 5. Run scanner for each date
        all_results = []
        for scan_date in scan_dates:
            results_df = run_scan(processed_data, market_caps, scan_date)
            if not results_df.empty:
                all_results.append(results_df)

        if all_results:
            final_results = pd.concat(all_results, ignore_index=True)

            # 6. Format and report results
            formatted_results = format_results(final_results)
            print_top_results(formatted_results)
            save_results(formatted_results, scan_dates[-1]) # Save with the last date in the name
        else:
            print("No stocks found matching the criteria in the selected date range.")

        # 7. Ask to run another scan
        another_scan = input("\nDo you want to run another scan? (y/n): ").strip().lower()
        if another_scan != 'y':
            print("Exiting scanner. Goodbye!")
            break

if __name__ == "__main__":
    main()
