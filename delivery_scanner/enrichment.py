
import logging
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from config import DELIVERY_SCAN_CONFIG, EXCHANGE_SUFFIX, DATA_PERIOD, FETCH_MARKET_CAP

log = logging.getLogger(__name__)

def fetch_market_cap_for_symbol(symbol: str) -> tuple[str, float | None]:
    """Fetches the market capitalization for a single symbol using yfinance."""
    try:
        ticker = yf.Ticker(symbol + EXCHANGE_SUFFIX)
        market_cap = ticker.info.get('marketCap')

        if market_cap:
            # Convert to Crores
            return symbol, market_cap / 1_00_00_000
        else:
            log.warning(f"Market cap not available for {symbol}")
            return symbol, None
    except Exception as e:
        log.error(f"Error fetching market cap for {symbol}: {e}")
        return symbol, None

def enrich_with_market_cap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches the DataFrame with market capitalization for each symbol
    using parallel fetching, and then applies the market cap filter.
    """
    if df.empty:
        return df

    symbols = df['symbol'].unique().tolist()
    log.info(f"Fetching market capitalization for {len(symbols)} symbols...")

    market_caps = {}
    with ThreadPoolExecutor(max_workers=DELIVERY_SCAN_CONFIG['market_cap_workers']) as executor:
        # Using tqdm for a progress bar
        futures = {executor.submit(fetch_market_cap_for_symbol, s): s for s in symbols}
        for future in tqdm(futures, total=len(symbols), desc="Fetching Market Caps"):
            symbol, cap = future.result()
            if cap is not None:
                market_caps[symbol] = cap

    df['market_cap_cr'] = df['symbol'].map(market_caps)

    # --- Apply Market Cap Filter ---
    initial_count = len(df)
    min_cap = DELIVERY_SCAN_CONFIG['min_market_cap_cr']
    df_filtered = df[df['market_cap_cr'].fillna(0) >= min_cap]

    log.info(f"Filter 'min_market_cap_cr' >= {min_cap} Cr: {initial_count} -> {len(df_filtered)} stocks")
    return df_filtered.copy()

def enrich_with_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates and adds RS (Relative Strength) and RSI (Relative Strength Index)
    to the DataFrame using yfinance and pandas_ta.
    """
    if df.empty:
        return df

    symbols = df['symbol'].unique().tolist()
    symbols_with_suffix = [s + EXCHANGE_SUFFIX for s in symbols]
    benchmark_symbol = "^NSEI"  # NIFTY 50 as the benchmark for RS

    log.info(f"Downloading historical data for {len(symbols)} symbols to calculate technical indicators...")

    try:
        # Download all data in one go for efficiency
        all_symbols_data = yf.download(
            symbols_with_suffix + [benchmark_symbol],
            period=DATA_PERIOD,
            interval="1d",
            progress=False,
            show_errors=False
        )['Close']

        if all_symbols_data.empty:
            log.error("Failed to download any historical data for technical indicators.")
            return df

        # --- Calculate RSI ---
        rsi_period = DELIVERY_SCAN_CONFIG['rsi_period']
        log.info(f"Calculating RSI({rsi_period})...")
        rsi_df = all_symbols_data.ta.rsi(length=rsi_period).to_frame(name='rsi')

        # Get the latest RSI value for each stock
        latest_rsi = rsi_df.groupby(level=0, axis=1).last().iloc[-1]
        latest_rsi.index = latest_rsi.index.str.replace(EXCHANGE_SUFFIX, '')
        df['rsi'] = df['symbol'].map(latest_rsi)

        # --- Calculate RS ---
        rs_period = DELIVERY_SCAN_CONFIG['rs_period']
        log.info(f"Calculating RS({rs_period}) against benchmark '{benchmark_symbol}'...")

        # Calculate returns
        returns = all_symbols_data.pct_change(rs_period).iloc[-1]

        # Calculate RS
        benchmark_return = returns[benchmark_symbol]
        relative_strength = (returns / benchmark_return) - 1

        rs_values = relative_strength.drop(benchmark_symbol)
        rs_values.index = rs_values.index.str.replace(EXCHANGE_SUFFIX, '')
        df['rs'] = df['symbol'].map(rs_values)

        log.info("Successfully calculated and added technical indicators.")

    except Exception as e:
        log.error(f"An error occurred during technical indicator calculation: {e}")
        df['rsi'] = None
        df['rs'] = None

    return df

def enrich_and_final_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main orchestration function for the enrichment module. It adds market cap
    and technical indicators, then applies the final market cap filter.
    """
    log.info("--- Starting Data Enrichment and Final Filtering ---")

    # 1. Add technical indicators first
    df_with_technicals = enrich_with_technical_indicators(df)

    # 2. Add market cap and apply the final filter if the feature is enabled
    if FETCH_MARKET_CAP:
        df_final = enrich_with_market_cap(df_with_technicals)
    else:
        log.info("Skipping market cap enrichment as per the feature flag.")
        df_final = df_with_technicals
        # Add placeholder columns to maintain a consistent structure
        df_final['market_cap_cr'] = None

    log.info("--- Data Enrichment and Final Filtering Complete ---")

    return df_final
