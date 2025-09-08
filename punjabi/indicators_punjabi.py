# indicators_punjabi.py (Updated with Trend Filter)

import pandas as pd
import numpy as np
import ta

def add_order_block_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Identifies Order Block candles and adds the long-term trend filter EMA.
    """
    df = df.copy()
    lookback = cfg['order_block']['lookback_period']
    body_mult = cfg['order_block']['body_size_mult']
    vol_mult = cfg['order_block']['volume_mult']

    # 1. Calculate base metrics for Order Blocks
    df['body_size'] = abs(df['close'] - df['open'])
    df['body_size_ma'] = df['body_size'].rolling(window=lookback).mean()
    df['volume_ma'] = df['volume'].rolling(window=lookback).mean()

    # 2. Identify candles that meet the Order Block criteria
    is_ob_candle = (
        (df['body_size'] > df['body_size_ma'] * body_mult) &
        (df['volume'] > df['volume_ma'] * vol_mult)
    )

    # 3. Create and forward-fill the last valid OB levels
    df['ob_high_on_candle'] = np.where(is_ob_candle, df['high'], np.nan)
    df['ob_low_on_candle'] = np.where(is_ob_candle, df['low'], np.nan)
    df['last_ob_high'] = df['ob_high_on_candle'].ffill()
    df['last_ob_low'] = df['ob_low_on_candle'].ffill()

    # 4. (NEW) Add Trend Filter Indicator if enabled in config
    if cfg.get('trend_filter', {}).get('enabled', False):
        ema_period = cfg['trend_filter']['ema_period']
        df['ema_trend'] = ta.trend.EMAIndicator(df['close'], window=ema_period).ema_indicator()
    
    # 5. Clean up intermediate columns
    df.drop(columns=[
        'body_size', 'body_size_ma', 'volume_ma',
        'ob_high_on_candle', 'ob_low_on_candle'
    ], inplace=True)

    return df