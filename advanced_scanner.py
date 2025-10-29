import pandas as pd
import pandas_ta as ta
from typing import Dict, List, Optional
import logging
from tqdm import tqdm
from datetime import datetime

from analysis import HHHLScanner
from config import SCAN_CONFIG

# Configure logging
log = logging.getLogger(__name__)

class AdvancedScanner:
    """
    Implements the advanced HHHL + ADX, ATR, RS55, RSI, EMA strategy.
    """
    def __init__(self, portfolio_value: float = 1000000, risk_per_trade: float = 0.01):
        self.portfolio_value = portfolio_value
        self.risk_per_trade = risk_per_trade
        self.hhhl_scanner = HHHLScanner(lookback_days=60, min_swing_pct=2.0)
        self.atr_multiplier = 2.0

    def calculate_indicators(self, symbol: str, data: pd.DataFrame, rs_value: Optional[float], scan_date: datetime) -> Optional[Dict]:
        """
        Calculates all required technical indicators for a single stock using pandas_ta,
        as of a specific scan_date.
        """
        historical_data = data[data.index <= scan_date]
        if historical_data.empty or len(historical_data) < 250:
            log.warning(f"Skipping {symbol} due to insufficient historical data for {scan_date.strftime('%Y-%m-%d')}.")
            return None

        # Use pandas_ta for all indicators
        historical_data.ta.ema(length=21, append=True)
        historical_data.ta.ema(length=200, append=True)
        historical_data.ta.atr(length=14, append=True)
        historical_data.ta.rsi(length=14, append=True)
        historical_data.ta.adx(length=14, append=True)
        historical_data.columns = [col.lower() for col in historical_data.columns]

        latest = historical_data.iloc[-1]

        return {
            'symbol': symbol,
            'close': latest['close'],
            'ema_21': latest['ema_21'],
            'ema_200': latest['ema_200'],
            'atr_14': latest['atrr_14'],
            'rsi_14': latest['rsi_14'],
            'adx': latest['adx_14'],
            'plus_di': latest['dmp_14'],
            'minus_di': latest['dmn_14'],
            'rs55': rs_value,
        }

    def calculate_score(self, indicators: Dict) -> float:
        norm_rs = min((indicators.get('rs55') or 0) / 0.3, 1.0)
        norm_adx = min((indicators.get('adx') or 0) / 50, 1.0)
        norm_rsi = max(0, min(1, ((indicators.get('rsi_14') or 0) - 40) / 60))
        score = (0.45 * norm_rs) + (0.30 * norm_adx) + (0.15 * norm_rsi)
        return round(score, 4)

    def apply_filters(self, indicators: Dict) -> bool:
        if not indicators: return False
        if indicators.get('trend') != 'UPTREND': return False
        if (indicators.get('close') or 0) < (indicators.get('ema_200') or float('inf')): return False
        if (indicators.get('adx') or 0) < 20: return False
        if (indicators.get('plus_di') or 0) < (indicators.get('minus_di') or float('inf')): return False
        if (indicators.get('rsi_14') or 0) < 40: return False
        return True

    def check_entry_signals(self, indicators: Dict, data: pd.DataFrame, scan_date: datetime) -> Dict:
        signals = {'entry_type': None}
        if not indicators: return signals

        historical_data = data[data.index <= scan_date]
        high_10d = historical_data['high'].rolling(window=10).max().iloc[-1]
        is_breakout = indicators['close'] > high_10d

        if is_breakout and indicators['close'] > indicators['ema_21'] and indicators['adx'] >= 25 and indicators['rsi_14'] < 80:
            signals['entry_type'] = 'BREAKOUT'
        elif abs(indicators['close'] - indicators['ema_21']) <= indicators['atr_14'] and indicators['adx'] >= 20 and indicators['rsi_14'] >= 45:
            signals['entry_type'] = 'PULLBACK'
        return signals

    def calculate_position_size(self, entry_price: float, atr: float) -> Dict:
        risk_amount = self.portfolio_value * self.risk_per_trade
        stop_distance = atr * self.atr_multiplier
        stop_price = entry_price - stop_distance
        shares = int(risk_amount / stop_distance) if stop_distance > 0 else 0
        position_value = shares * entry_price

        max_position = self.portfolio_value * 0.25
        if position_value > max_position:
            shares = int(max_position / entry_price)
            position_value = shares * entry_price

        return {
            'shares': shares, 'position_value': round(position_value, 2),
            'stop_price': round(stop_price, 2),
            'target_1r': round(entry_price + stop_distance, 2),
            'target_2r': round(entry_price + (stop_distance * 2), 2),
            'position_pct': round((position_value / self.portfolio_value) * 100, 2)
        }

    def run_advanced_scan(self, market_data: Dict[str, pd.DataFrame], rs_lookup: Dict[str, float], scan_date: datetime):
        results = []
        log.info(f"Starting advanced HHHL + ADX analysis for date {scan_date.strftime('%Y-%m-%d')}...")
        for symbol, data in tqdm(market_data.items(), desc="Running Advanced Analysis"):
            hhhl_result = self.hhhl_scanner.scan_single_stock(symbol, df_data=data[data.index <= scan_date])
            if not hhhl_result: continue

            rs_value = rs_lookup.get(symbol.replace(".NS", ""))
            indicators = self.calculate_indicators(symbol, data, rs_value, scan_date)
            if not indicators: continue

            indicators.update(hhhl_result)
            indicators['score'] = self.calculate_score(indicators)
            indicators['tradeable'] = self.apply_filters(indicators)

            if indicators['tradeable']:
                signals = self.check_entry_signals(indicators, data, scan_date)
                indicators.update(signals)
                if indicators.get('entry_type'):
                    position_info = self.calculate_position_size(indicators['close'], indicators['atr_14'])
                    indicators.update(position_info)
            results.append(indicators)

        df_results = pd.DataFrame(results).sort_values('score', ascending=False)
        return df_results
