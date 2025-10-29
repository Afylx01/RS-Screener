"""
Configuration settings with REALISTIC data requirements for all indicators
"""
import os
from pathlib import Path

# Directory paths
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
RESULTS_DIR = BASE_DIR / "results"
ADVANCED_RESULTS_DIR = BASE_DIR / "advanced_results"
DELIVERY_SCANNER_DIR = BASE_DIR / "delivery_scanner_results"
DELIVERY_DATA_DIR = BASE_DIR / "delivery_data"


# Create directories if they don't exist
CACHE_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)
ADVANCED_RESULTS_DIR.mkdir(exist_ok=True)
DELIVERY_SCANNER_DIR.mkdir(exist_ok=True)
DELIVERY_DATA_DIR.mkdir(exist_ok=True)


# --- Feature Flags ---
FETCH_MARKET_CAP = True # Set to False to skip market cap download and filtering

# Scanning configuration with RS55
SCAN_CONFIG = {
"min_market_cap": 1000, # in CR (Crores)

# RSI Settings
"rsi_short_period": 14,
"rsi_weekly_period": 12,

# EMA Settings
"ema_short": 50,
"ema_long": 200,

# 52-week high settings
"high_lookback": 252,
"min_52_week_ratio": 0.75,

# RS55 Configuration
"rs_period": 55,
"rs_scan_mode": "positive", # Options: "positive", "crossover", "disabled"
"benchmark_symbol": "^NSEI",

# Performance
"cache_days": 1,
"max_workers_download": 5,
"max_workers_calculation": os.cpu_count() or 4,
"retry_attempts": 3,
"retry_delay": 1,
}

# --- Delivery Scanner Configuration ---
DELIVERY_SCAN_CONFIG = {
    # Delivery Filters
    "min_delivery_quantity": 10000,
    "min_percent_change": 0.0,
    "min_delivery_times": 3.0,
    # Market Cap Filter
    "min_market_cap_cr": 100.0,
    # Number of workers for market cap fetching
    "market_cap_workers": 10,
    # Technical Indicators
    "rs_period": 55,
    "rsi_period": 14,
    # System Defaults
    "days_back": 8,
    "bhavcopy_base_url": "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "timeout": 15,
    "sqlite_db_name": "bhavcopy.sqlite",
}


# Realistic data requirements
DATA_REQUIREMENTS = {
"min_days_rsi14": 25,
"min_days_ema50": 75,
"min_days_ema200": 250,
"min_days_rs55": 80,
"min_days_52w_high": 280,
}

REQUIRED_TRADING_DAYS = max(DATA_REQUIREMENTS.values())
REQUIRED_CALENDAR_DAYS = int(REQUIRED_TRADING_DAYS * 1.5)

# Data source
NIFTY_TOTAL_MARKET_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"

# yfinance settings
DATA_PERIOD = "2y"
DATA_INTERVAL = "1d"
WEEKLY_INTERVAL = "1wk"
EXCHANGE_SUFFIX = ".NS"
USD_TO_INR = 83.0

# Output
OUTPUT_SETTINGS = {
"top_results_console": 10,
"generate_tradingview_links": True,
"show_rs55_details": True,
}

# Telegram Configuration
TELEGRAM_CONFIG = {
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",  # Replace with your bot token
    "chat_id": "YOUR_TELEGRAM_CHAT_ID",      # Replace with your chat ID
}


LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
