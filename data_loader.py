import pandas as pd
import yfinance as yf
from pathlib import Path
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import io

from config import (
    CACHE_DIR,
    NIFTY_TOTAL_MARKET_URL,
    EXCHANGE_SUFFIX,
    SCAN_CONFIG,
    DATA_PERIOD,
    DATA_INTERVAL,
    USD_TO_INR,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_stock_symbols():
    """
    Fetches the list of stock symbols from the NIFTY Total Market CSV file.
    """
    try:
        response = requests.get(NIFTY_TOTAL_MARKET_URL, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        symbols = df['Symbol'].str.strip() + EXCHANGE_SUFFIX
        return symbols.tolist()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching symbol list: {e}")
        return []

def get_market_cap(ticker):
    """
    Fetches market cap for a single ticker.
    """
    try:
        stock_info = yf.Ticker(ticker).info
        market_cap_usd = stock_info.get("marketCap")
        if market_cap_usd:
            return market_cap_usd / USD_TO_INR / 1e7  # Convert to Crores
        return None
    except Exception as e:
        logging.warning(f"Could not fetch market cap for {ticker}: {e}")
        return None

def download_stock_data(ticker, cache_days):
    """
    Downloads and caches historical data for a single stock.
    """
    cache_file = CACHE_DIR / f"{ticker}.parquet"
    if cache_file.exists():
        file_mod_time = cache_file.stat().st_mtime
        if (time.time() - file_mod_time) / 86400 < cache_days:
            logging.info(f"Loading {ticker} from cache.")
            return pd.read_parquet(cache_file)

    for attempt in range(SCAN_CONFIG["retry_attempts"]):
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period=DATA_PERIOD, interval=DATA_INTERVAL)
            if not data.empty:
                data.to_parquet(cache_file)
                logging.info(f"Successfully downloaded and cached data for {ticker}.")
                return data
            else:
                logging.warning(f"No data for {ticker}. It might be delisted.")
                return None
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed for {ticker}: {e}")
            time.sleep(SCAN_CONFIG["retry_delay"])
    return None

def download_all_data(symbols):
    """
    Downloads data for all symbols in parallel.
    """
    market_caps = {}
    with ThreadPoolExecutor(max_workers=SCAN_CONFIG["max_workers_download"]) as executor:
        # Download OHLCV data
        future_to_ticker = {executor.submit(download_stock_data, ticker, SCAN_CONFIG["cache_days"]): ticker for ticker in symbols}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                future.result()
            except Exception as exc:
                logging.error(f'{ticker} generated an exception: {exc}')

        # Download market cap data
        future_to_market_cap = {executor.submit(get_market_cap, ticker): ticker for ticker in symbols}
        for future in as_completed(future_to_market_cap):
            ticker = future_to_market_cap[future]
            try:
                market_cap = future.result()
                if market_cap is not None:
                    market_caps[ticker] = market_cap
            except Exception as exc:
                logging.error(f'{ticker} generated an exception during market cap fetch: {exc}')

    # Cache market caps
    market_cap_cache_file = CACHE_DIR / "market_caps.json"
    pd.Series(market_caps).to_json(market_cap_cache_file)

def load_data(ticker):
    """
    Loads data for a single ticker from cache.
    """
    cache_file = CACHE_DIR / f"{ticker}.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        # Forward-fill missing values
        df.ffill(inplace=True)
        return df
    return None

def load_all_data(symbols):
    """
    Loads all data from cache.
    """
    data = {}
    for symbol in symbols:
        df = load_data(symbol)
        if df is not None:
            data[symbol] = df

    market_cap_cache_file = CACHE_DIR / "market_caps.json"
    if market_cap_cache_file.exists():
        market_caps = pd.read_json(market_cap_cache_file, typ='series').to_dict()
    else:
        market_caps = {}

    return data, market_caps

def align_benchmark_data(stock_data, benchmark_ticker="^NSEI"):
    """
    Aligns benchmark data to the stock data index.
    """
    benchmark_data = load_data(benchmark_ticker)
    if benchmark_data is not None:
        return benchmark_data.reindex(stock_data.index, method='ffill')
    return None
