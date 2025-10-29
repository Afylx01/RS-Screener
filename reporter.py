import pandas as pd
from datetime import datetime

from config import RESULTS_DIR, OUTPUT_SETTINGS

def generate_tradingview_link(symbol):
    """
    Generates a TradingView link for a given symbol.
    """
    base_url = "https://www.tradingview.com/chart/?symbol=NSE:"
    # Remove .NS suffix for the link
    cleaned_symbol = symbol.replace(".NS", "")
    return f'{base_url}{cleaned_symbol}'

def format_results(results_df):
    """
    Formats the results dataframe for output.
    """
    if results_df.empty:
        return results_df

    # Round numeric columns
    for col in ['Close', 'EMA_50', 'EMA_200', 'RS55_Today', 'RS55_Yesterday', '52W_High_Ratio']:
        if col in results_df.columns:
            results_df[col] = results_df[col].round(2)

    # Add TradingView link
    if OUTPUT_SETTINGS['generate_tradingview_links']:
        results_df['TradingView_Link'] = results_df['Symbol'].apply(generate_tradingview_link)

    # Clean up the Symbol column by removing the .NS suffix
    results_df['Symbol'] = results_df['Symbol'].str.replace(".NS", "", regex=False)

    return results_df

def save_results(results_df, scan_date):
    """
    Saves the results to Excel and CSV files.
    """
    if results_df.empty:
        print(f"No stocks met the criteria for {scan_date.strftime('%Y-%m-%d')}.")
        return

    # Format filename
    filename_date = scan_date.strftime('%Y%m%d')
    excel_path = RESULTS_DIR / f"RS55_Scan_{filename_date}.xlsx"
    csv_path = RESULTS_DIR / f"RS55_Scan_{filename_date}.csv"

    # Save to CSV
    results_df.to_csv(csv_path, index=False)
    print(f"Results saved to {csv_path}")

    # Save to Excel with hyperlink
    try:
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            results_df.to_excel(writer, index=False, sheet_name='Scan Results')
            workbook = writer.book
            worksheet = writer.sheets['Scan Results']

            # Find the TradingView_Link column
            link_col_idx = -1
            for idx, col in enumerate(results_df.columns):
                if col == 'TradingView_Link':
                    link_col_idx = idx + 1
                    break

            if link_col_idx != -1:
                for row_idx, row in results_df.iterrows():
                    cell = worksheet.cell(row=row_idx + 2, column=link_col_idx)
                    cell.hyperlink = cell.value
                    cell.style = "Hyperlink"
        print(f"Results saved to {excel_path}")
    except Exception as e:
        print(f"Failed to save to Excel with hyperlinks: {e}. The CSV is still available.")

def print_top_results(results_df):
    """
    Prints the top N results to the console.
    """
    if not results_df.empty:
        print("\n--- Top 10 Results ---")
        print(results_df.head(OUTPUT_SETTINGS['top_results_console']).to_string())
