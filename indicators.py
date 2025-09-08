# indicators.py
import pandas as pd
import numpy as np
import ta

# ---------- HYBRID (kept in case you still use it elsewhere) ----------
def add_all_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    adx_indicator = ta.trend.ADXIndicator(
        high=df['high'], low=df['low'], close=df['close'], window=cfg['regime_filter']['adx_period']
    )
    df['adx'] = adx_indicator.adx()
    df['ema_fast'] = ta.trend.EMAIndicator(df['close'], window=cfg['trend_strategy']['ema_fast_period']).ema_indicator()
    df['ema_slow'] = ta.trend.EMAIndicator(df['close'], window=cfg['trend_strategy']['ema_slow_period']).ema_indicator()

    bb_indicator = ta.volatility.BollingerBands(
        close=df['close'],
        window=cfg['mean_reversion_strategy']['bb_period'],
        window_dev=cfg['mean_reversion_strategy']['bb_std_dev']
    )
    df['bb_lower'] = bb_indicator.bollinger_lband()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=cfg['common_parameters']['rsi_period']).rsi()
    df['atr'] = ta.volatility.AverageTrueRange(
        high=df['high'], low=df['low'], close=df['close'], window=cfg['common_parameters']['atr_period']
    ).average_true_range()
    return df

def add_mta_trend_indicator(df: pd.DataFrame, period: int) -> pd.DataFrame:
    df = df.copy()
    df['mta_ema_trend'] = ta.trend.EMAIndicator(df['close'], window=period).ema_indicator()
    return df

def check_trend_entry_signal(prev_row: pd.Series, cur_row: pd.Series, cfg: dict) -> bool:
    in_short_term_uptrend = cur_row['ema_fast'] > cur_row['ema_slow']
    rsi_crossed_up = (prev_row['rsi'] <= cfg['rsi_crossover_value']) and (cur_row['rsi'] > cfg['rsi_crossover_value'])
    in_long_term_uptrend = cur_row['close'] > cur_row['mta_ema_trend']
    return in_short_term_uptrend and rsi_crossed_up and in_long_term_uptrend

def check_reversion_entry_signal(prev_row: pd.Series, cur_row: pd.Series, cfg: dict) -> bool:
    price_crossed_lower_band = cur_row['low'] <= cur_row['bb_lower']
    is_oversold = cur_row['rsi'] < cfg['rsi_max_value']
    return price_crossed_lower_band and is_oversold

# ---------- Core indicators ----------
def add_core_indicators(df: pd.DataFrame, rsi_period=14, atr_period=14) -> pd.DataFrame:
    df = df.copy()
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=rsi_period).rsi()
    df['atr'] = ta.volatility.AverageTrueRange(
        high=df['high'], low=df['low'], close=df['close'], window=atr_period
    ).average_true_range()
    return df

# ---------- Punjabi Order Block labelling ----------
def label_order_blocks(
    df: pd.DataFrame,
    lookahead_n: int = 3,
    impulse_mult: float = 1.5,
    min_body_pct: float = 0.3
) -> pd.DataFrame:
    """
    Objective order-block anchors:
    - bullish OB: last solid red candle preceding an upward impulse >= impulse_mult * ATR
    - bearish OB: last solid green candle preceding a downward impulse >= impulse_mult * ATR
    """
    df = df.copy()
    o, h, l, c, atr = df['open'].values, df['high'].values, df['low'].values, df['close'].values, df['atr'].values
    n = len(df)

    bull_ob_bar = np.full(n, -1, dtype=int)
    bear_ob_bar = np.full(n, -1, dtype=int)
    bull_ob_high = np.full(n, np.nan, dtype=float)
    bull_ob_low  = np.full(n, np.nan, dtype=float)
    bear_ob_high = np.full(n, np.nan, dtype=float)
    bear_ob_low  = np.full(n, np.nan, dtype=float)

    last_red_idx = -1
    last_green_idx = -1

    for i in range(n):
        body = abs(c[i] - o[i])
        rng = max(h[i] - l[i], 1e-12)
        body_ok = (body / rng) >= min_body_pct

        if c[i] < o[i] and body_ok:
            last_red_idx = i
        elif c[i] > o[i] and body_ok:
            last_green_idx = i

        if last_red_idx >= 0:
            k1, k2 = i, min(i + lookahead_n, n - 1)
            up_thrust = max(0.0, (np.max(h[k1:k2+1]) - c[last_red_idx]))
            if up_thrust >= impulse_mult * max(atr[last_red_idx], 1e-12):
                bull_ob_bar[i] = last_red_idx
                bull_ob_high[i] = h[last_red_idx]
                bull_ob_low[i]  = l[last_red_idx]

        if last_green_idx >= 0:
            k1, k2 = i, min(i + lookahead_n, n - 1)
            down_thrust = max(0.0, (c[last_green_idx] - np.min(l[k1:k2+1])))
            if down_thrust >= impulse_mult * max(atr[last_green_idx], 1e-12):
                bear_ob_bar[i] = last_green_idx
                bear_ob_high[i] = h[last_green_idx]
                bear_ob_low[i]  = l[last_green_idx]

    df['bull_ob_bar']  = bull_ob_bar
    df['bull_ob_high'] = bull_ob_high
    df['bull_ob_low']  = bull_ob_low
    df['bear_ob_bar']  = bear_ob_bar
    df['bear_ob_high'] = bear_ob_high
    df['bear_ob_low']  = bear_ob_low
    return df

# ---------- Punjabi indicators entry point ----------
def add_punjabi_indicators(
    df: pd.DataFrame,
    rsi_period=14,
    atr_period=14,
    lookahead_n=3,
    impulse_mult=1.5,
    min_body_pct=0.3,
    vol_sma_len: int = 20
) -> pd.DataFrame:
    """
    Add RSI, ATR, order-block labels, and Volume SMA for Punjabi strategy.
    """
    df2 = add_core_indicators(df, rsi_period=rsi_period, atr_period=atr_period)
    if 'volume' in df2.columns:
        df2['vol_sma'] = df2['volume'].rolling(int(vol_sma_len)).mean()
    else:
        df2['vol_sma'] = float('nan')
    df2 = label_order_blocks(
        df2,
        lookahead_n=lookahead_n,
        impulse_mult=impulse_mult,
        min_body_pct=min_body_pct
    )
    return df2
