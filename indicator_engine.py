import pandas as pd
import pandas_ta as ta
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
from tqdm import tqdm

from config import SCAN_CONFIG, DATA_REQUIREMENTS, REQUIRED_TRADING_DAYS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_indicators_for_stock(data, benchmark_data):
    """
    Calculates all required technical indicators for a single stock's data.
    """
    if data is None or len(data) < REQUIRED_TRADING_DAYS:
        return None

    # Standardize column names to lowercase for consistency
    data.columns = [col.lower() for col in data.columns]
    if benchmark_data is not None and not benchmark_data.empty:
        benchmark_data.columns = [col.lower() for col in benchmark_data.columns]

    # 1. Daily RSI
    data['rsi_14'] = ta.rsi(data['close'], length=SCAN_CONFIG['rsi_short_period'])

    # 2. Weekly RSI
    weekly_data = data.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    weekly_rsi = ta.rsi(weekly_data['close'], length=SCAN_CONFIG['rsi_weekly_period'])
    data['rsi_12_weekly'] = weekly_rsi.reindex(data.index, method='ffill')

    # 3. EMAs
    data['ema_50'] = ta.ema(data['close'], length=SCAN_CONFIG['ema_short'])
    data['ema_200'] = ta.ema(data['close'], length=SCAN_CONFIG['ema_long'])

    # 4. 252-day High
    data['52w_high'] = data['close'].rolling(window=SCAN_CONFIG['high_lookback']).max()

    # 5. Relative Strength (RS55)
    if benchmark_data is not None and not benchmark_data.empty:
        stock_return = data['close'] / data['close'].shift(SCAN_CONFIG['rs_period'])
        nifty_return = benchmark_data['close'] / benchmark_data['close'].shift(SCAN_CONFIG['rs_period'])
        rs55 = (stock_return / nifty_return) - 1
        data['RS55_Today'] = rs55
        data['RS55_Yesterday'] = rs55.shift(1)

    # Drop rows with NaN values created by indicators
    data.dropna(inplace=True)

    return data

def run_indicator_calculation(all_stock_data, benchmark_data):
    """
    Runs indicator calculations for all stocks in parallel.
    """
    results = {}
    with ProcessPoolExecutor(max_workers=SCAN_CONFIG["max_workers_calculation"]) as executor:
        future_to_symbol = {
            executor.submit(calculate_indicators_for_stock, data, benchmark_data.reindex(data.index, method='ffill')): symbol
            for symbol, data in all_stock_data.items()
        }

        for future in tqdm(as_completed(future_to_symbol), total=len(all_stock_data), desc="Calculating Indicators"):
            symbol = future_to_symbol[future]
            try:
                result_df = future.result()
                if result_df is not None and not result_df.empty:
                    results[symbol] = result_df
            except Exception as exc:
                logging.error(f'{symbol} generated an exception during indicator calculation: {exc}')

    return results
