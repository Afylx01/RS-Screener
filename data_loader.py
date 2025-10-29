import pandas as pd
import yfinance as yf
from pathlib import Path
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import io
from tqdm import tqdm

from config import (
    CACHE_DIR,
    NIFTY_TOTAL_MARKET_URL,
    EXCHANGE_SUFFIX,
    SCAN_CONFIG,
    DATA_PERIOD,
    DATA_INTERVAL,
    USD_TO_INR,
    FETCH_MARKET_CAP
)

# Configure logging
log = logging.getLogger(__name__)

def get_stock_symbols():
    """
    Fetches the list of stock symbols from the NIFTY Total Market CSV file
    and filters out dummy symbols.
    """
    try:
        log.info("Fetching stock symbol list from Nifty Indices...")
        response = requests.get(NIFTY_TOTAL_MARKET_URL, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))

        symbols = df['Symbol'].str.strip()
        # Filter out dummy symbols before appending the suffix
        symbols = symbols[~symbols.str.contains("DUMMY", na=False)]

        log.info(f"Found {len(symbols)} valid symbols.")
        return (symbols + EXCHANGE_SUFFIX).tolist()
    except requests.exceptions.RequestException as e:
        log.error(f"Error fetching symbol list: {e}")
        return []

def get_market_cap(ticker):
    """
    Fetches market cap for a single ticker. Returns value in Crores.
    """
    try:
        stock_info = yf.Ticker(ticker).info
        market_cap_usd = stock_info.get("marketCap")
        if market_cap_usd:
            return market_cap_usd / USD_TO_INR / 1e7  # Convert to Crores
        log.debug(f"Market cap not available for {ticker}")
        return None
    except Exception:
        log.warning(f"Could not fetch market cap for {ticker}. It may be delisted or there was a network issue.")
        return None

def download_stock_data(ticker, cache_days):
    """
    Downloads and caches historical OHLCV data for a single stock.
    """
    cache_file = CACHE_DIR / f"{ticker}.parquet"
    if cache_file.exists():
        file_mod_time = cache_file.stat().st_mtime
        if (time.time() - file_mod_time) / 86400 < cache_days:
            log.debug(f"Loading {ticker} from cache.")
            return pd.read_parquet(cache_file)

    for attempt in range(SCAN_CONFIG["retry_attempts"]):
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period=DATA_PERIOD, interval=DATA_INTERVAL, auto_adjust=False, back_adjust=True)
            if not data.empty:
                data.columns = [col.lower() for col in data.columns]
                data.to_parquet(cache_file)
                log.debug(f"Successfully downloaded and cached data for {ticker}.")
                return data
        except Exception as e:
            log.error(f"Attempt {attempt + 1} failed for {ticker}: {e}")
            time.sleep(SCAN_CONFIG["retry_delay"])

    log.warning(f"No data for {ticker} after all attempts. It might be delisted.")
    return None

def download_all_data(symbols):
    """
    Downloads OHLCV data and market caps for all symbols in parallel,
    using separate, managed thread pools to avoid rate-limiting issues.
    """
    log.info("Starting parallel download for OHLCV data...")
    with ThreadPoolExecutor(max_workers=SCAN_CONFIG["max_workers_download"]) as executor:
        future_to_ticker = {executor.submit(download_stock_data, ticker, SCAN_CONFIG["cache_days"]): ticker for ticker in symbols}
        for future in tqdm(as_completed(future_to_ticker), total=len(symbols), desc="[1/2] Downloading OHLCV Data"):
            try:
                future.result()
            except Exception as exc:
                ticker = future_to_ticker[future]
                log.error(f'{ticker} generated an exception during OHLCV download: {exc}')

    if FETCH_MARKET_CAP:
        log.info("Starting parallel download for market cap data...")
        market_caps = {}
        # Use a more constrained number of workers for market cap to avoid API rate limiting
        market_cap_workers = max(1, SCAN_CONFIG["max_workers_download"] // 2)
        with ThreadPoolExecutor(max_workers=market_cap_workers) as executor:
            future_to_market_cap = {executor.submit(get_market_cap, ticker): ticker for ticker in symbols}
            for future in tqdm(as_completed(future_to_market_cap), total=len(symbols), desc="[2/2] Fetching Market Caps"):
                try:
                    market_cap = future.result()
                    if market_cap is not None:
                        ticker = future_to_market_cap[future]
                        market_caps[ticker] = market_cap
                except Exception as exc:
                    ticker = future_to_market_cap[future]
                    log.error(f'{ticker} generated an exception during market cap fetch: {exc}')

        # Cache the successfully fetched market caps
        if market_caps:
            market_cap_cache_file = CACHE_DIR / "market_caps.json"
            pd.Series(market_caps).to_json(market_cap_cache_file)
            log.info(f"Successfully cached market caps for {len(market_caps)} symbols.")

def load_data(ticker):
    """
    Loads historical data for a single ticker from its cached Parquet file.
    """
    cache_file = CACHE_DIR / f"{ticker}.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        df.columns = [col.lower() for col in df.columns]  # Ensure lowercase columns
        df.ffill(inplace=True)  # Forward-fill any missing values
        return df
    return None

def load_all_data(symbols):
    """
    Loads all cached data for the given symbols.
    """
    data = {}
    log.info("Loading all stock data from cache...")
    for symbol in tqdm(symbols, desc="Loading data from cache"):
        df = load_data(symbol)
        if df is not None:
            data[symbol] = df

    market_caps = {}
    if FETCH_MARKET_CAP:
        market_cap_cache_file = CACHE_DIR / "market_caps.json"
        if market_cap_cache_file.exists():
            log.info("Loading market caps from cache.")
            market_caps = pd.read_json(market_cap_cache_file, typ='series').to_dict()
        else:
            log.warning("Market cap cache file not found.")

    return data, market_caps

def align_benchmark_data(stock_data, benchmark_ticker="^NSEI"):
    """
    Aligns the benchmark data (e.g., NIFTY) to a stock's data index.
    """
    benchmark_data = load_data(benchmark_ticker)
    if benchmark_data is not None:
        # Reindex and forward-fill to match the trading days of the stock
        return benchmark_data.reindex(stock_data.index, method='ffill')
    return None
