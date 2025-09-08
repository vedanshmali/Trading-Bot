# strategy_punjabi.py
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import pandas as pd
import math

@dataclass
class Trade:
    side: str             # 'long' or 'short'
    entry_ts: int
    entry: float
    size: float
    sl: float
    tp: float
    reason: str
    exit_ts: Optional[int] = None
    exit: Optional[float] = None
    pnl: Optional[float] = None
    bars_held: int = 0
    high_since_entry: float = 0.0
    low_since_entry: float = 0.0
    moved_to_be: bool = False  # breakeven applied?

def _apply_slippage(price: float, bps: float, side: str, is_entry: bool) -> float:
    """Apply slippage (basis points). Buyers pay up on entry and down on exit; sellers vice-versa."""
    mult = 1.0 + (bps/10000.0)
    if is_entry:
        return price * (mult if side == 'long' else 1.0/mult)
    else:
        return price * (1.0/mult if side == 'long' else mult)

def _fee_cost(notional: float, fee: float) -> float:
    return abs(notional) * fee

def _position_size_fixed_risk(equity: float, risk_pct: float, entry: float, stop: float, long_only=True, side='long') -> float:
    """Risk = equity * risk_pct; qty sized by per-unit risk to SL."""
    per_unit_risk = (entry - stop) if side == 'long' else (stop - entry)
    if per_unit_risk <= 0 or equity <= 0 or risk_pct <= 0:
        return 0.0
    qty = (equity * risk_pct) / per_unit_risk
    return max(qty, 0.0)

def _bps(a: float, b: float) -> float:
    """Distance in basis points between a and b."""
    return abs((a - b) / max(b, 1e-12)) * 10000.0

def run_punjabi_backtest(
    df: pd.DataFrame,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Punjabi's Paid: Break of objective OB levels with fixed % SL/TP.
    Risk controls: ATR% filter, cooldown, daily loss cap, time stop.
    Quality: volume spike + max distance to OB at entry.
    NEW: Breakeven and ATR trailing stops.
    """
    df = df.copy().reset_index(drop=True)
    if len(df) < 50:
        return {"error": "not_enough_data"}

    needed = {'ts','open','high','low','close','volume','atr','bull_ob_high','bull_ob_bar','bear_ob_low','bear_ob_bar'}
    missing = [c for c in needed if c not in df.columns]
    if missing:
        return {"error": f"missing_columns: {missing}"}

    # Ensure vol_sma exists
    vol_sma_len = int(cfg.get('filters', {}).get('vol_sma_len', 20))
    if 'vol_sma' not in df.columns:
        df['vol_sma'] = df['volume'].rolling(vol_sma_len).mean()

    equity = float(cfg['starting_equity'])
    peak_equity = equity
    max_dd = 0.0
    trades: List[Trade] = []
    pos: Optional[Trade] = None

    long_only = bool(cfg.get('long_only', True))
    allow_short = not long_only

    risk_pct = float(cfg.get('risk_per_trade', 0.01))
    fee = float(cfg.get('fees', {}).get('taker', 0.001))
    slip_bps = float(cfg.get('slippage_bps', 2.0))

    # Filters and risk controls
    min_atr_pct = float(cfg.get('filters', {}).get('min_atr_pct', 0.0))
    max_atr_pct = float(cfg.get('filters', {}).get('max_atr_pct', 5.0))
    vol_min_mult = float(cfg.get('filters', {}).get('vol_min_mult', 0.0))
    max_distance_bps = float(cfg.get('filters', {}).get('max_distance_bps', 1e9))

    cooldown_bars = int(cfg.get('risk', {}).get('cooldown_bars', 0))
    daily_max_loss = float(cfg.get('risk', {}).get('daily_max_loss', 1e9))
    time_stop_bars = int(cfg.get('exits', {}).get('time_stop_bars', 0))
    hit_priority = cfg.get('exits', {}).get('hit_priority', 'conservative')

    # Breakeven & ATR trail
    be_cfg = cfg.get('exits', {}).get('breakeven', {})
    be_enabled = bool(be_cfg.get('enabled', False))
    be_trigger_pct = float(be_cfg.get('trigger_pct', 0.0))  # e.g., 0.0025 for +0.25%
    be_plus_bps = float(be_cfg.get('plus_bps', 0.0))        # move SL to entry + X bps (long)
    atr_trail_cfg = cfg.get('exits', {}).get('atr_trail', {})
    atr_trail_enabled = bool(atr_trail_cfg.get('enabled', False))
    atr_trail_mult = float(atr_trail_cfg.get('atr_mult', 0.0))

    cur_day = None
    day_start_equity = equity
    cooldown_left = 0

    for i in range(1, len(df)):
        row_prev = df.iloc[i-1]
        row = df.iloc[i]
        ts, o, h, l, c = int(row['ts']), float(row['open']), float(row['high']), float(row['low']), float(row['close'])
        atr = float(row['atr'])
        atr_pct = (atr / max(c, 1e-12)) * 100.0

        # New day
        day = pd.to_datetime(ts, unit='ms').date()
        if cur_day is None or day != cur_day:
            cur_day = day
            day_start_equity = equity

        # Daily loss cap
        if (day_start_equity - equity) >= daily_max_loss:
            if pos is not None:
                exit_px = _apply_slippage(c, slip_bps, pos.side, is_entry=False)
                pnl_gross = (exit_px - pos.entry) * pos.size if pos.side == 'long' else (pos.entry - exit_px) * pos.size
                pnl_net = pnl_gross - _fee_cost(pos.entry * pos.size, fee) - _fee_cost(exit_px * pos.size, fee)
                equity += pnl_net
                pos.exit_ts, pos.exit, pos.pnl = ts, exit_px, pnl_net
                trades.append(pos)
                pos = None
            continue

        # Manage open
        if pos is not None:
            pos.bars_held += 1
            # Update extremes for trailing logic
            pos.high_since_entry = max(pos.high_since_entry, h)
            pos.low_since_entry  = min(pos.low_since_entry if pos.low_since_entry > 0 else l, l)

            # 1) Breakeven move (once)
            if be_enabled and not pos.moved_to_be:
                if pos.side == 'long':
                    if h >= pos.entry * (1.0 + be_trigger_pct):
                        # move SL to entry + be_plus_bps
                        be_mult = 1.0 + (be_plus_bps / 10000.0)
                        pos.sl = max(pos.sl, pos.entry * be_mult)
                        pos.moved_to_be = True
                else:
                    if l <= pos.entry * (1.0 - be_trigger_pct):
                        be_mult = 1.0 - (be_plus_bps / 10000.0)
                        pos.sl = min(pos.sl, pos.entry * be_mult)
                        pos.moved_to_be = True

            # 2) ATR trailing (monotonic)
            if atr_trail_enabled and atr_trail_mult > 0:
                if pos.side == 'long':
                    trail = pos.high_since_entry - atr_trail_mult * atr
                    if trail > pos.sl:
                        pos.sl = trail
                else:
                    trail = pos.low_since_entry + atr_trail_mult * atr
                    if trail < pos.sl:
                        pos.sl = trail

            # 3) Exit checks
            if pos.side == 'long':
                sl_hit = l <= pos.sl
                tp_hit = h >= pos.tp
                if tp_hit and (hit_priority == 'aggressive' or not sl_hit):
                    fill = _apply_slippage(pos.tp, slip_bps, pos.side, is_entry=False)
                    pnl_gross = (fill - pos.entry) * pos.size
                elif sl_hit:
                    fill = _apply_slippage(pos.sl, slip_bps, pos.side, is_entry=False)
                    pnl_gross = (fill - pos.entry) * pos.size
                else:
                    fill = None
            else:
                sl_hit = h >= pos.sl
                tp_hit = l <= pos.tp
                if tp_hit and (hit_priority == 'aggressive' or not sl_hit):
                    fill = _apply_slippage(pos.tp, slip_bps, pos.side, is_entry=False)
                    pnl_gross = (pos.entry - fill) * pos.size
                elif sl_hit:
                    fill = _apply_slippage(pos.sl, slip_bps, pos.side, is_entry=False)
                    pnl_gross = (pos.entry - fill) * pos.size
                else:
                    fill = None

            # 4) Time stop (optional)
            if fill is None and time_stop_bars > 0 and pos.bars_held >= time_stop_bars:
                fill = _apply_slippage(c, slip_bps, pos.side, is_entry=False)
                pnl_gross = (fill - pos.entry) * pos.size if pos.side == 'long' else (pos.entry - fill) * pos.size

            if fill is not None:
                pnl_net = pnl_gross - _fee_cost(pos.entry * pos.size, fee) - _fee_cost(fill * pos.size, fee)
                equity += pnl_net
                pos.exit_ts, pos.exit, pos.pnl = ts, fill, pnl_net
                trades.append(pos)
                # cooldown after loss
                if pnl_net < 0 and cooldown_bars > 0:
                    cooldown_left = cooldown_bars
                pos = None
                peak_equity = max(peak_equity, equity)
                dd = (peak_equity - equity) / max(peak_equity, 1e-12)
                max_dd = max(max_dd, dd)
                continue

        # Entry filters (when flat)
        if pos is None:
            if cooldown_left > 0:
                cooldown_left -= 1
                continue
            if not (min_atr_pct <= atr_pct <= max_atr_pct):
                continue

            # Volume filter
            vol_ok = True
            if vol_min_mult > 0.0:
                vol_sma = float(row.get('vol_sma', float('nan')))
                if not math.isnan(vol_sma) and vol_sma > 0:
                    vol_ok = float(row['volume']) >= vol_min_mult * vol_sma

            # LONG on bullish OB break
            entered = False
            ob_high = float(row.get('bull_ob_high', float('nan')))
            ob_bar  = int(row.get('bull_ob_bar', -1))
            if not math.isnan(ob_high) and ob_bar >= 0 and vol_ok and cfg.get('long_only', True):
                if df.iloc[i-1]['close'] <= ob_high and c > ob_high:
                    if _bps(c, ob_high) <= max_distance_bps:
                        entry_px = _apply_slippage(c, slip_bps, 'long', is_entry=True)
                        sl_px = entry_px * (1.0 - cfg['sl_pct'])
                        tp_px = entry_px * (1.0 + cfg['tp_pct'])
                        qty = _position_size_fixed_risk(equity, risk_pct, entry_px, sl_px, long_only=True, side='long')
                        if qty > 0:
                            pos = Trade(
                                side='long', entry_ts=ts, entry=entry_px, size=qty,
                                sl=sl_px, tp=tp_px, reason='bull_ob_break',
                                high_since_entry=h, low_since_entry=l
                            )
                            entered = True

            # SHORT on bearish OB break (only if allowed)
            if (not entered) and allow_short and vol_ok:
                ob_low = float(row.get('bear_ob_low', float('nan')))
                ob_bar = int(row.get('bear_ob_bar', -1))
                if not math.isnan(ob_low) and ob_bar >= 0:
                    if df.iloc[i-1]['close'] >= ob_low and c < ob_low:
                        if _bps(c, ob_low) <= max_distance_bps:
                            entry_px = _apply_slippage(c, slip_bps, 'short', is_entry=True)
                            sl_px = entry_px * (1.0 + cfg['sl_pct'])
                            tp_px = entry_px * (1.0 - cfg['tp_pct'])
                            qty = _position_size_fixed_risk(equity, risk_pct, entry_px, sl_px, long_only=False, side='short')
                            if qty > 0:
                                pos = Trade(
                                    side='short', entry_ts=ts, entry=entry_px, size=qty,
                                    sl=sl_px, tp=tp_px, reason='bear_ob_break',
                                    high_since_entry=h, low_since_entry=l
                                )

        # update peak DD while flat too
        peak_equity = max(peak_equity, equity)

    # Force-close any open position at last close
    if pos is not None:
        last_close = float(df.iloc[-1]['close'])
        fill = _apply_slippage(last_close, slip_bps, pos.side, is_entry=False)
        pnl_gross = (fill - pos.entry) * pos.size if pos.side == 'long' else (pos.entry - fill) * pos.size
        pnl_net = pnl_gross - _fee_cost(pos.entry * pos.size, fee) - _fee_cost(fill * pos.size, fee)
        equity += pnl_net
        pos.exit_ts, pos.exit, pos.pnl = int(df.iloc[-1]['ts']), fill, pnl_net
        trades.append(pos)

    pnl_series = pd.Series([t.pnl for t in trades], dtype='float') if trades else pd.Series([], dtype='float')
    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series <= 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0

    return {
        "final_equity": equity,
        "net_pnl": float(pnl_series.sum()) if len(pnl_series) else 0.0,
        "total_trades": len(trades),
        "win_rate": float(len(wins) / len(trades) * 100.0) if len(trades) else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float('inf'),
        "max_drawdown": max_dd,
        "trades": [t.__dict__ for t in trades],
    }
