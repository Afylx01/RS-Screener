import pandas as pd
from tqdm import tqdm

from config import SCAN_CONFIG, DATA_REQUIREMENTS

def run_scan(all_stock_data, market_caps, scan_date):
    """
    Runs the scanner to find stocks that meet all 12 conditions on a given date.
    """
    results = []
    for symbol, data in tqdm(all_stock_data.items(), desc=f"Scanning for {scan_date.strftime('%Y-%m-%d')}"):
        if scan_date not in data.index:
            continue

        day_data = data.loc[scan_date]

        # Condition 1: Market Cap
        market_cap = market_caps.get(symbol, 0)
        if market_cap < SCAN_CONFIG['min_market_cap']:
            continue

        # Condition 2: 14-day RSI > 50
        if day_data['rsi_14'] <= 50:
            continue

        # Condition 3: 12-week RSI > 50
        if day_data['rsi_12_weekly'] <= 50:
            continue

        # Condition 4: Bullish Daily Candle
        if day_data['close'] <= day_data['open']:
            continue

        # Conditions 5, 6, 7: Close > Yesterday's, 2-day-ago, and 3-day-ago High
        prev_days_data = data.loc[:scan_date].tail(4)
        if len(prev_days_data) < 4:
            continue
        if not (day_data['close'] > prev_days_data.iloc[-2]['high'] and
                day_data['close'] > prev_days_data.iloc[-3]['high'] and
                day_data['close'] > prev_days_data.iloc[-4]['high']):
            continue

        # Condition 8: Price > 50-day EMA
        if day_data['close'] <= day_data['ema_50']:
            continue

        # Condition 9: Price > 200-day EMA
        if day_data['close'] <= day_data['ema_200']:
            continue

        # Condition 10: Golden Cross
        if day_data['ema_50'] <= day_data['ema_200']:
            continue

        # Condition 11: Near 52-week High
        if day_data['close'] < SCAN_CONFIG['min_52_week_ratio'] * day_data['52w_high']:
            continue

        # Condition 12: RS55 Condition
        rs_mode = SCAN_CONFIG['rs_scan_mode']
        if rs_mode == 'positive' and day_data['RS55_Today'] <= 0:
            continue
        elif rs_mode == 'crossover' and not (day_data['RS55_Today'] > 0 and day_data['RS55_Yesterday'] <= 0):
            continue

        results.append({
            'Date': scan_date.strftime('%Y-%m-%d'),
            'Symbol': symbol,
            'Close': day_data['close'],
            'Volume': day_data['volume'],
            'MarketCap_CR': market_cap,
            'RSI_14': day_data['rsi_14'],
            'RSI_12_Weekly': day_data['rsi_12_weekly'],
            'EMA_50': day_data['ema_50'],
            'EMA_200': day_data['ema_200'],
            'RS55_Today': day_data['RS55_Today'],
            'RS55_Yesterday': day_data['RS55_Yesterday'],
            '52W_High_Ratio': day_data['close'] / day_data['52w_high'],
            'Golden_Cross': True,
        })

    return pd.DataFrame(results)
