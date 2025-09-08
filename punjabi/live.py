import pandas as pd
import yaml
import time
import os
from datetime import datetime
from dotenv import load_dotenv

from indicators_punjabi import add_order_block_indicators
from strategy import calculate_position_size
from utils import log, read_state, write_state, get_sleep_time
from exchange import create_exchange, fetch_candles, create_market_order

def run_bot():
    """The main execution loop for the live trading bot."""
    load_dotenv()
    with open('config_live.yaml', 'r') as f:
        CFG = yaml.safe_load(f)

    exchange = create_exchange(CFG)
    symbol = CFG['symbol']
    timeframe = CFG['timeframe']

    while True:
        try:
            state = read_state()
            position = state.get('position')
            
            # 1. Fetch latest data
            ohlcv = fetch_candles(exchange, symbol, timeframe, CFG['candle_limit'])
            if not ohlcv:
                time.sleep(20)
                continue

            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df = add_order_block_indicators(df, CFG)
            
            # Use the last fully closed candle for signals
            prev = df.iloc[-2]
            cur = df.iloc[-1] # Current, potentially incomplete candle

            log(f"Checking candle {datetime.fromtimestamp(prev['ts']/1000)} | Close: {prev['close']:.2f}")

            # --- 2. POSITION MANAGEMENT ---
            if position:
                exit_reason = None
                if position['side'] == 'long':
                    if cur['low'] <= position['sl']: exit_reason = 'Stop-Loss'
                    elif cur['high'] >= position['tp']: exit_reason = 'Take-Profit'
                elif position['side'] == 'short':
                    if cur['high'] >= position['sl']: exit_reason = 'Stop-Loss'
                    elif cur['low'] <= position['tp']: exit_reason = 'Take-Profit'
                
                if exit_reason:
                    log(f"EXIT SIGNAL: {exit_reason} triggered for {position['side']} position.", "warning")
                    side_to_close = 'sell' if position['side'] == 'long' else 'buy'
                    order = create_market_order(exchange, symbol, side_to_close, position['qty'])
                    if order:
                        write_state({"position": None}) # Reset state after successful exit
                    else:
                        log("CRITICAL: Failed to place exit order. Bot will retry.", "error")

            # --- 3. ENTRY LOGIC ---
            if not state.get('position'): # Re-read state in case it was just cleared
                ob_high = prev['last_ob_high']
                ob_low = prev['last_ob_low']
                entry_side = None

                # Check for long entry
                if prev['close'] < ob_high and cur['open'] < ob_high and cur['high'] > ob_high:
                    entry_side = 'long'
                    entry_price = ob_high
                    sl = entry_price * (1 - CFG['trade_rules']['stop_loss_pct'])
                    tp = entry_price * (1 + CFG['trade_rules']['take_profit_pct'])
                
                # Check for short entry
                elif not CFG['trade_rules']['long_only'] and prev['close'] > ob_low and cur['open'] > ob_low and cur['low'] < ob_low:
                    entry_side = 'short'
                    entry_price = ob_low
                    sl = entry_price * (1 + CFG['trade_rules']['stop_loss_pct'])
                    tp = entry_price * (1 - CFG['trade_rules']['take_profit_pct'])
                
                if entry_side:
                    log(f"ENTRY SIGNAL: New {entry_side} signal found at breakout level {entry_price:.2f}", "success")
                    # Use a placeholder for equity; a real bot would fetch this
                    # For safety, we use the hard-coded max position size to calculate qty
                    qty = CFG['max_position_usdt'] / entry_price
                    
                    order = create_market_order(exchange, symbol, entry_side, qty)
                    if order:
                        # You would parse the actual fill price and quantity from the `order` object here
                        # For simplicity, we assume it fills at the intended price
                        new_position = {
                            'side': entry_side, 'qty': qty, 'entry_price': entry_price, 'sl': sl, 'tp': tp
                        }
                        write_state({"position": new_position})

        except Exception as e:
            log(f"An error occurred in the main loop: {e}", "error")
        
        # 4. Sleep until the next candle
        sleep_duration = get_sleep_time(timeframe)
        log(f"Sleeping for {sleep_duration:.2f} seconds until next candle...", "debug")
        time.sleep(sleep_duration)


if __name__ == '__main__':
    run_bot()