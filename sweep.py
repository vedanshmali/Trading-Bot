# sweep.py — fast Punjabi sweep with OB caching (fixed imports)
import argparse, yaml, pandas as pd, itertools, time, sys
from indicators import add_core_indicators, label_order_blocks
from strategy import run_punjabi_backtest

DEFAULT_GRID = {
    'impulse_mult':     [1.9, 2.0, 2.1, 2.2],
    'min_body_pct':     [0.40, 0.45, 0.50],
    'sl_pct':           [0.0022, 0.0025, 0.0028],
    'tp_pct':           [0.0044, 0.0050, 0.0056],
    'vol_min_mult':     [1.20, 1.40, 1.60],
    'max_distance_bps': [3.0, 5.0, 8.0],
    'min_atr_pct':      [0.02, 0.03, 0.04],
    'max_atr_pct':      [0.70, 0.80, 0.90],
}

def ensure_cfg(cfg: dict) -> dict:
    cfg = dict(cfg)
    cfg.setdefault('starting_equity', 1000.0)
    cfg.setdefault('risk_per_trade', 0.002)
    cfg.setdefault('long_only', True)
    cfg.setdefault('fees', {'maker': 0.001, 'taker': 0.001})
    cfg.setdefault('slippage_bps', 1.0)
    cfg.setdefault('sl_pct', 0.0025)
    cfg.setdefault('tp_pct', 0.0050)
    cfg.setdefault('indicators', {'rsi_period': 14, 'atr_period': 14})
    cfg.setdefault('order_block', {'lookahead_n': 6, 'impulse_mult': 2.1, 'min_body_pct': 0.45})
    cfg.setdefault('filters', {
        'min_atr_pct': 0.03, 'max_atr_pct': 0.80,
        'vol_sma_len': 20, 'vol_min_mult': 1.40, 'max_distance_bps': 5.0
    })
    cfg.setdefault('exits', {'time_stop_bars': 4, 'hit_priority': 'aggressive'})
    return cfg

def main(data_path: str, cfg_path: str, out_csv: str, coarse: bool):
    try:
        base = yaml.safe_load(open(cfg_path, 'r'))
    except Exception as e:
        print(f"[ERROR] Could not read config: {e}"); sys.exit(1)
    base = ensure_cfg(base)

    try:
        raw = pd.read_csv(data_path)[['ts','open','high','low','close','volume']]
    except Exception as e:
        print(f"[ERROR] CSV must have columns ts,open,high,low,close,volume: {e}"); sys.exit(1)

    grid = DEFAULT_GRID.copy()
    if coarse:
        grid['impulse_mult']     = [1.9, 2.1]
        grid['min_body_pct']     = [0.40, 0.50]
        grid['sl_pct']           = [0.0022, 0.0028]
        grid['tp_pct']           = [0.0044, 0.0056]
        grid['vol_min_mult']     = [1.20, 1.60]
        grid['max_distance_bps'] = [3.0, 8.0]
        grid['min_atr_pct']      = [0.02, 0.04]
        grid['max_atr_pct']      = [0.70, 0.90]

    keys, vals = zip(*grid.items())
    combos = list(itertools.product(*vals))
    print(f"[INFO] Combos: {len(combos)} (coarse={coarse})")

    t0 = time.time()
    # 1) indicators once
    base_ind = add_core_indicators(raw,
                                   rsi_period=base['indicators']['rsi_period'],
                                   atr_period=base['indicators']['atr_period']).copy()
    vol_sma_len = int(base['filters'].get('vol_sma_len', 20))
    base_ind['vol_sma'] = base_ind['volume'].rolling(vol_sma_len).mean()
    base_ind.dropna(inplace=True)
    base_ind.reset_index(drop=True, inplace=True)

    # 2) cache OB labels per (impulse_mult, min_body_pct)
    lookahead_n = int(base['order_block'].get('lookahead_n', 6))
    ib_vals = sorted(set(grid['impulse_mult']))
    mb_vals = sorted(set(grid['min_body_pct']))
    ob_cache = {}
    print(f"[INFO] Precomputing OB labels for {len(ib_vals)*len(mb_vals)} settings…")
    for im in ib_vals:
        for mb in mb_vals:
            df_lbl = label_order_blocks(base_ind.copy(),
                                        lookahead_n=lookahead_n,
                                        impulse_mult=float(im),
                                        min_body_pct=float(mb))
            ob_cache[(im, mb)] = df_lbl

    results = []
    last_save = time.time()
    for idx, combo in enumerate(combos, 1):
        p = dict(zip(keys, combo))
        cfg = ensure_cfg(base)
        cfg['order_block']['impulse_mult'] = float(p['impulse_mult'])
        cfg['order_block']['min_body_pct'] = float(p['min_body_pct'])
        cfg['filters']['vol_min_mult']     = float(p['vol_min_mult'])
        cfg['filters']['max_distance_bps'] = float(p['max_distance_bps'])
        cfg['filters']['min_atr_pct']      = float(p['min_atr_pct'])
        cfg['filters']['max_atr_pct']      = float(p['max_atr_pct'])
        cfg['sl_pct'] = float(p['sl_pct'])
        cfg['tp_pct'] = float(p['tp_pct'])

        df_use = ob_cache[(cfg['order_block']['impulse_mult'], cfg['order_block']['min_body_pct'])]
        res = run_punjabi_backtest(df_use, cfg)
        results.append({
            **p,
            'pf': round(res['profit_factor'], 3),
            'wr%': round(res['win_rate'], 2),
            'trades': res['total_trades'],
            'net_pnl': round(res['net_pnl'], 2),
            'max_dd%': round(res['max_drawdown']*100, 2),
            'final_eq': round(res['final_equity'], 2),
        })

        if idx % 25 == 0 or idx == len(combos):
            print(f"  - {idx}/{len(combos)} … PF={results[-1]['pf']}, trades={results[-1]['trades']}")
        if time.time() - last_save > 10:
            pd.DataFrame(results).to_csv(out_csv, index=False)
            last_save = time.time()

    out = pd.DataFrame(results).sort_values(['pf','net_pnl','wr%'], ascending=[False, False, False])
    print("\nTop 25:")
    print(out.head(25).to_string(index=False))
    out.to_csv(out_csv, index=False)
    print(f"\n[OK] Saved results to {out_csv}. Elapsed {time.time()-t0:.1f}s")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fast sweep for Punjabi strategy")
    ap.add_argument('--data', required=True, help='CSV ts,open,high,low,close,volume')
    ap.add_argument('--config', required=True, help='Base YAML config')
    ap.add_argument('--out', default='sweep_results.csv')
    ap.add_argument('--coarse', action='store_true', help='Use smaller coarse grid first')
    args = ap.parse_args()
    main(args.data, args.config, args.out, args.coarse)
