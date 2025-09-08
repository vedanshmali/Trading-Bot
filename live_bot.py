# live.py
import os
import time
import yaml
import pandas as pd
from math import floor
from dotenv import load_dotenv

from coindcx_client import CoinDCXClient
from indicators import add_indicators, add_trend_indicator, check_long_entry_signal
from strategy import calculate_position_size, calculate_initial_stop_loss, manage_trailing_stop
from utils import read_state, write_state, ts_to_str, log

# --- CONFIG & INITIALIZATION ---
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

with open('config.yaml', 'r') as f:
    CFG = yaml.safe_load(f)

# Asset precision (e.g., BTC has 8 decimal places)
# This is crucial for order placement. Change if you trade another asset.
ASSET_PRECISION_STEP = 1e-8

def get_dataframes(client: CoinDCXClient) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetches and prepares data for both main and trend timeframes."""
    try:
        # Main timeframe data
        raw_main = client.fetch_candles(CFG['symbol'], timeframe=CFG['timeframe'], limit=500)
        df_main = pd.DataFrame(raw_main, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df_main = add_indicators(df_main, CFG['indicators'])

        # Trend timeframe data (if enabled)
        df_trend = None
        if CFG.get('multi_timeframe', {}).get('enabled'):
            tf_trend = CFG['multi_timeframe']['timeframe']
            raw_trend = client.fetch_candles(CFG['symbol'], timeframe=tf_trend, limit=500)
            df_trend = pd.DataFrame(raw_trend, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df_trend = add_trend_indicator(df_trend, CFG['multi_timeframe']['ema_trend_period'])

        return df_main.dropna(), df_trend.dropna() if df_trend is not None else None
    except Exception as e:
        log(f"ERROR: Could not fetch or process data: {e}", level="error")
        return None, None

def main_loop():
    client = CoinDCXClient(API_KEY, API_SECRET)
    state = read_state()
    order_market = CFG['symbol'].replace("/", "").upper()
    log(f"Bot started for {order_market} on {CFG['timeframe']} timeframe.")

    last_bar_ts = 0
    while True:
        try:
            df, df_trend = get_dataframes(client)
            if df is None:
                time.sleep(20)
                continue

            # Use the second to last row as the last fully closed bar
            idx = len(df) - 2
            cur, prev = df.iloc[idx], df.iloc[idx-1]

            if cur['ts'] == last_bar_ts:
                time.sleep(10)
                continue
            last_bar_ts = cur['ts']
            log(f"New Bar: {ts_to_str(cur['ts'])} | Close: {cur['close']:.2f} | ATR: {cur['atr']:.2f} | RSI: {cur['rsi']:.1f}")

            # --- POSITION MANAGEMENT ---
            pos = state.get('position')
            if pos and pos['side'] == 'long':
                # Check for Stop Loss or Trailing Stop hit
                if cur['low'] <= pos['stop_loss']:
                    log(f"EXIT: Stop-loss triggered at {pos['stop_loss']:.2f}", "warning")
                    # ... (Place Sell Order Logic) ...
                    state['position'] = None
                    write_state(state) # Persist exit immediately
                    continue

                # Update Trailing Stop
                if CFG['stops_targets']['trailing_stop']['enabled']:
                    new_stop = manage_trailing_stop(
                        pos,
                        cur['high'],
                        cur['atr'],
                        CFG['stops_targets']['trailing_stop']['atr_mult']
                    )
                    if new_stop > pos['stop_loss']:
                        log(f"Trailing stop moved up to {new_stop:.2f}", "info")
                        pos['stop_loss'] = new_stop
                        write_state(state) # Persist new stop

            # --- ENTRY LOGIC ---
            if not state.get('position'):
                # 1. Trend Filter (Multi-Timeframe)
                is_uptrend = True # Default to true if MTA is disabled
                if df_trend is not None:
                    last_trend_bar = df_trend.iloc[-2]
                    is_uptrend = last_trend_bar['close'] > last_trend_bar['ema_trend']
                    if not is_uptrend:
                        log(f"Entry blocked: Price is below trend EMA on {CFG['multi_timeframe']['timeframe']}.", "debug")
                        continue
                
                # 2. Volatility Filter
                if CFG['volatility_filter']['enabled']:
                    atr_pct = (cur['atr'] / cur['close']) * 100
                    min_atr, max_atr = CFG['volatility_filter']['min_atr_pct'], CFG['volatility_filter']['max_atr_pct']
                    if not (min_atr < atr_pct < max_atr):
                        log(f"Entry blocked: ATR% ({atr_pct:.2f}%) is outside of range ({min_atr}% - {max_atr}%).", "debug")
                        continue

                # 3. Entry Signal
                if is_uptrend and check_long_entry_signal(prev, cur, CFG['entry']):
                    entry_price = cur['close']
                    sl = calculate_initial_stop_loss(entry_price, cur['atr'], CFG['stops_targets']['initial_stop_atr_mult'])
                    
                    # Get latest equity
                    try:
                        # You would implement a proper balance fetch here
                        equity = state.get('equity', CFG['starting_equity'])
                    except Exception:
                        equity = state.get('equity', CFG['starting_equity'])
                    
                    qty = calculate_position_size(equity, CFG['risk_per_trade'], entry_price, sl)
                    
                    # Apply precision rounding
                    qty_rounded = floor(qty / ASSET_PRECISION_STEP) * ASSET_PRECISION_STEP

                    if qty_rounded <= 0:
                        log("Entry skipped: Calculated quantity is too small.", "warning")
                        continue

                    log(f"ENTRY SIGNAL: Buying {qty_rounded} of {order_market} at ~{entry_price:.2f}", "success")
                    log(f" -> Initial Stop: {sl:.2f}")

                    # --- PLACE LIVE ORDER ---
                    # resp = client.create_spot_order_market(market=order_market, side='buy', total_quantity=qty_rounded)
                    # actual_fill_price = float(resp...) # Parse response to get actual fill price
                    # ...
                    
                    # For simulation, we assume fill at close
                    actual_fill_price = entry_price

                    state['position'] = {
                        'side': 'long',
                        'qty': qty_rounded,
                        'entry_price': actual_fill_price,
                        'stop_loss': sl,
                        'entry_time': cur['ts'],
                        'high_since_entry': cur['high'] # For trailing stop
                    }
                    write_state(state)
            
            # Persist state at the end of each loop
            write_state(state)
            time.sleep(5)

        except KeyboardInterrupt:
            log("Bot stopping manually.", "warning")
            return
        except Exception as e:
            log(f"FATAL ERROR in main loop: {e}", "error")
            time.sleep(20)

if __name__ == '__main__':
    main_loop()