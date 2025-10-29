from scipy.signal import find_peaks
from scipy.stats import linregress
import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional
import warnings

warnings.filterwarnings('ignore')

class HHHLScanner:
    """
    Analyzes price structure for Higher Highs and Higher Lows (HHHL).
    """
    def __init__(self, lookback_days=60, min_swing_pct=2.0):
        self.lookback_days = lookback_days
        self.min_swing_pct = min_swing_pct

    def download_data(self, symbol, period='3mo'):
        """Download historical data for a symbol (used as fallback)"""
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(period=period)
            if len(df) > 0:
                return df
            else:
                return None
        except Exception as e:
            print(f"Error downloading {symbol}: {e}")
            return None

    def identify_swing_points(self, prices, dates):
        if len(prices) == 0:
            return {'highs': {'indices': [], 'values': [], 'dates': []},
                    'lows': {'indices': [], 'values': [], 'dates': []}}

        price_mean = np.mean(prices)
        prominence = (self.min_swing_pct / 100) * price_mean

        peaks, _ = find_peaks(prices, prominence=prominence, distance=3)
        troughs, _ = find_peaks(-prices, prominence=prominence, distance=3)

        swing_points = {
            'highs': {
                'indices': peaks,
                'values': prices[peaks] if len(peaks) > 0 else np.array([]),
                'dates': dates[peaks] if len(peaks) > 0 else [],
            },
            'lows': {
                'indices': troughs,
                'values': prices[troughs] if len(troughs) > 0 else np.array([]),
                'dates': dates[troughs] if len(troughs) > 0 else [],
            }
        }
        return swing_points

    def analyze_trend_structure(self, swing_points):
        highs = swing_points['highs']['values']
        lows = swing_points['lows']['values']

        result = {
            'trend': 'UNDEFINED', 'strength': 0, 'higher_highs': 0,
            'lower_highs': 0, 'higher_lows': 0, 'lower_lows': 0,
            'total_highs': len(highs), 'total_lows': len(lows),
        }

        if len(highs) < 2 or len(lows) < 2:
            return result

        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        lower_highs = len(highs) - 1 - higher_highs
        higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        lower_lows = len(lows) - 1 - higher_lows

        total_comparisons = (len(highs) - 1) + (len(lows) - 1)
        uptrend_score = (higher_highs + higher_lows) / total_comparisons if total_comparisons > 0 else 0
        downtrend_score = (lower_highs + lower_lows) / total_comparisons if total_comparisons > 0 else 0

        if uptrend_score > 0.6:
            trend = 'UPTREND'
            strength = uptrend_score
        elif downtrend_score > 0.6:
            trend = 'DOWNTREND'
            strength = downtrend_score
        else:
            trend = 'SIDEWAYS'
            strength = 1 - abs(uptrend_score - downtrend_score)

        result.update({
            'trend': trend, 'strength': strength * 100,
            'higher_highs': higher_highs, 'lower_highs': lower_highs,
            'higher_lows': higher_lows, 'lower_lows': lower_lows
        })
        return result

    def scan_single_stock(self, symbol: str, df_data: Optional[pd.DataFrame] = None):
        try:
            df = df_data.copy() if df_data is not None else self.download_data(symbol)
            if df is None or len(df) < self.lookback_days:
                return None

            df_analysis = df.tail(self.lookback_days).copy()
            prices = df_analysis['Close'].values
            dates = df_analysis.index.values

            if len(prices) == 0 or np.isnan(prices).any():
                return None

            swing_points = self.identify_swing_points(prices, dates)
            trend_analysis = self.analyze_trend_structure(swing_points)

            current_price = prices[-1]
            min_price, max_price = np.min(prices), np.max(prices)
            price_position = ((current_price - min_price) / (max_price - min_price)) * 100 if max_price > min_price else 50

            return {
                'symbol': symbol, 'trend': trend_analysis['trend'],
                'trend_strength': trend_analysis['strength'],
                'price_position': price_position,
            }
        except Exception as e:
            print(f"Error scanning {symbol} in HHHL: {e}")
            return None
