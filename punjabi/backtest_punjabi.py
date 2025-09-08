# backtest_punjabi.py (Updated with Trend Filter Logic)

import pandas as pd
import yaml
import argparse
from indicators_punjabi import add_order_block_indicators
from strategy import calculate_position_size
from utils import log

def run_backtest(df, cfg):
    """Core backtest logic for the Punjabi's Paid strategy."""
    
    equity = cfg['starting_equity']
    peak_equity = equity
    max_drawdown = 0
    trade_records = []
    position = None

    sl_pct = cfg['trade_rules']['stop_loss_pct']
    tp_pct = cfg['trade_rules']['take_profit_pct']
    fee = cfg['taker_fee']
    risk_per_trade = cfg['risk_per_trade']

    log("Starting backtest simulation...", "info")

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        cur = df.iloc[i]

        # --- POSITION MANAGEMENT ---
        if position:
            pnl = 0
            exit_price = None
            if position['side'] == 'long':
                if cur['high'] >= position['tp']: exit_price = position['tp']
                elif cur['low'] <= position['sl']: exit_price = position['sl']
            elif position['side'] == 'short':
                if cur['low'] <= position['tp']: exit_price = position['tp']
                elif cur['high'] >= position['sl']: exit_price = position['sl']
            
            if exit_price:
                if position['side'] == 'long':
                    pnl = (exit_price - position['entry_price']) * position['qty']
                else:
                    pnl = (position['entry_price'] - exit_price) * position['qty']
                
                trade_value = position['entry_price'] * position['qty']
                exit_value = exit_price * position['qty']
                total_fees = (trade_value * fee) + (exit_value * fee)
                pnl -= total_fees
                
                equity += pnl
                drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                max_drawdown = max(max_drawdown, drawdown)
                if equity > peak_equity: peak_equity = equity
                
                trade_records.append({'pnl': pnl, 'fees': total_fees})
                position = None

        # --- ENTRY LOGIC ---
        if not position:
            ob_high = prev['last_ob_high']
            ob_low = prev['last_ob_low']

            # (NEW) Trend Filter Conditions
            trend_ok_for_long = True
            trend_ok_for_short = True
            if cfg.get('trend_filter', {}).get('enabled', False):
                # Check if the ema_trend column exists and is not NaN
                if 'ema_trend' in prev and pd.notna(prev['ema_trend']):
                    trend_ok_for_long = prev['close'] > prev['ema_trend']
                    trend_ok_for_short = prev['close'] < prev['ema_trend']
                else:
                    # If EMA is not ready (e.g., at the start of data), don't trade
                    trend_ok_for_long = False
                    trend_ok_for_short = False

            # LONG ENTRY: Breakout Occurs AND We are in an Uptrend
            if trend_ok_for_long and cur['open'] < ob_high and cur['high'] > ob_high:
                entry_price = ob_high
                sl = entry_price * (1 - sl_pct)
                tp = entry_price * (1 + tp_pct)
                qty = calculate_position_size(equity, risk_per_trade, entry_price, sl)
                if qty > 0:
                    position = {'side': 'long', 'qty': qty, 'entry_price': entry_price, 'sl': sl, 'tp': tp}
            
            # SHORT ENTRY: Breakout Occurs AND We are in a Downtrend
            elif not cfg['trade_rules']['long_only'] and trend_ok_for_short and cur['open'] > ob_low and cur['low'] < ob_low:
                entry_price = ob_low
                sl = entry_price * (1 + sl_pct)
                tp = entry_price * (1 - tp_pct)
                qty = calculate_position_size(equity, risk_per_trade, entry_price, sl)
                if qty > 0:
                    position = {'side': 'short', 'qty': qty, 'entry_price': entry_price, 'sl': sl, 'tp': tp}

    # --- RESULTS CALCULATION ---
    if not trade_records:
        log("No trades were executed during the backtest period.", "warning")
        return None
    trades_df = pd.DataFrame(trade_records)
    total_trades = len(trades_df)
    wins = trades_df[trades_df['pnl'] > 0]
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] <= 0]['pnl'].sum())
    return {
        "net_pnl": trades_df['pnl'].sum(), "total_trades": total_trades,
        "win_rate": (len(wins) / total_trades) * 100 if total_trades > 0 else 0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        "max_drawdown": max_drawdown, "final_equity": equity,
        "total_fees": trades_df['fees'].sum()
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Backtest the Punjabi's Paid trading strategy.")
    parser.add_argument('--data', type=str, required=True, help='Path to the historical data CSV file.')
    args = parser.parse_args()
    with open('config_punjabi.yaml', 'r') as f:
        CFG = yaml.safe_load(f)
    log("Loading data...", "info")
    df_raw = pd.read_csv(args.data)
    log("Calculating indicators...", "info")
    df_processed = add_order_block_indicators(df_raw, CFG)
    df_processed.dropna(inplace=True)
    results = run_backtest(df_processed, CFG)
    if results:
        print("\n" + "="*50)
        log("STRATEGY BACKTEST RESULTS", "success")
        print("="*50)
        print(f" Period Tested      : {pd.to_datetime(df_raw['ts'].iloc[0], unit='ms')} -> {pd.to_datetime(df_raw['ts'].iloc[-1], unit='ms')}")
        print(f" Initial Equity     : ${CFG['starting_equity']:,.2f}")
        print("-" * 50)
        print(f" Final Equity       : ${results['final_equity']:,.2f}")
        print(f" Net PnL            : ${results['net_pnl']:,.2f}")
        print(f" Total Fees Paid    : ${results['total_fees']:,.2f}")
        print(f" Max Drawdown       : {results['max_drawdown']:.2%}")
        print("-" * 50)
        print(f" Total Trades       : {results['total_trades']}")
        print(f" Win Rate           : {results['win_rate']:.2f}%")
        print(f" Profit Factor      : {results['profit_factor']:.2f}")
        print("="*50 + "\n")