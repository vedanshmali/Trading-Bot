# backtest.py  (Punjabi runner with analytics + CSV export)
import argparse
import yaml
import pandas as pd
from indicators import add_punjabi_indicators
from strategy import run_punjabi_backtest
from utils import log

def _summarize_trades(trades):
    if not trades:
        return {}

    df = pd.DataFrame(trades)
    df['side'] = df['side'].astype(str)
    df['win'] = df['pnl'] > 0
    df['R'] = df['pnl'] / (df['size'] * df['entry'])  # rough normalized pnl

    # per side
    side_grp = df.groupby('side')
    side_stats = side_grp.agg(
        trades=('pnl','count'),
        wr=('win','mean'),
        avg_pnl=('pnl','mean'),
        med_pnl=('pnl','median'),
        pf=('pnl', lambda x: (x[x>0].sum() / abs(x[x<=0].sum())) if x[x<=0].sum()!=0 else float('inf')),
    ).reset_index()

    # calendar stats
    df['month'] = pd.to_datetime(df['entry_ts'], unit='ms').dt.to_period('M').astype(str)
    month_grp = df.groupby('month').agg(
        trades=('pnl','count'),
        net_pnl=('pnl','sum'),
        wr=('win','mean'),
        pf=('pnl', lambda x: (x[x>0].sum() / abs(x[x<=0].sum())) if x[x<=0].sum()!=0 else float('inf')),
    ).reset_index()

    # expectancy
    avg_win = df.loc[df['win'],'pnl'].mean() if (df['win']).any() else 0.0
    avg_loss = df.loc[~df['win'],'pnl'].mean() if (~df['win']).any() else 0.0
    wr = df['win'].mean()
    expectancy = wr*avg_win + (1-wr)*avg_loss

    return {
        'df_trades': df,
        'side_stats': side_stats,
        'month_stats': month_grp,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'wr': wr,
        'expectancy': expectancy
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest Punjabi's Paid Scalping Strategy")
    ap.add_argument('--data', required=True, help='CSV with ts,open,high,low,close,volume')
    ap.add_argument('--config', required=True, help='YAML config for Punjabi strategy')
    ap.add_argument('--out', default='trades_punjabi.csv', help='CSV path to save trades')
    args = ap.parse_args()

    with open(args.config, 'r') as f:
        CFG = yaml.safe_load(f)

    df_raw = pd.read_csv(args.data)
    df = df_raw[['ts','open','high','low','close','volume']].copy()

    df = add_punjabi_indicators(
        df,
        rsi_period=CFG['indicators']['rsi_period'],
        atr_period=CFG['indicators']['atr_period'],
        lookahead_n=CFG['order_block']['lookahead_n'],
        impulse_mult=CFG['order_block']['impulse_mult'],
        min_body_pct=CFG['order_block']['min_body_pct'],
        vol_sma_len=CFG['filters'].get('vol_sma_len', 20)
    ).dropna().reset_index(drop=True)

    log("info", "Running Punjabi backtest...")
    res = run_punjabi_backtest(df, CFG)

    print("\n" + "="*60)
    log("success", "PUNJABI SCALP - RESULTS")
    print("="*60)
    print(f" Initial Equity     : ${CFG['starting_equity']:,.2f}")
    print(f" Final Equity       : ${res['final_equity']:,.2f}")
    print(f" Net PnL            : ${res['net_pnl']:,.2f}")
    print("-"*60)
    print(f" Total Trades       : {res['total_trades']}")
    print(f" Win Rate           : {res['win_rate']:.2f}%")
    print(f" Profit Factor      : {res['profit_factor']:.2f}")
    print(f" Max Drawdown       : {res['max_drawdown']:.2%}")
    print("="*60 + "\n")

    # ---------- Extra analytics ----------
    rpt = _summarize_trades(res.get('trades', []))
    if rpt:
        print("Per-side stats:")
        print(rpt['side_stats'].to_string(index=False))
        print("\nPer-month stats:")
        print(rpt['month_stats'].to_string(index=False))
        print("\nExpectancy per trade:")
        print(f"  Win%: {rpt['wr']*100:.2f}% | AvgWin: {rpt['avg_win']:.2f} | AvgLoss: {rpt['avg_loss']:.2f} | Expectancy: {rpt['expectancy']:.2f}")

        # Save trades to CSV
        rpt['df_trades'].to_csv(args.out, index=False)
        print(f"\nSaved trades to: {args.out}")
