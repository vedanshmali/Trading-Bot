def calculate_position_size(equity: float, risk_pct: float, entry_price: float, stop_loss_price: float) -> float:
    """Calculates position size based on fixed fractional risk."""
    
    # For short positions, the order is reversed
    if entry_price > stop_loss_price: # Long trade
        risk_per_share = entry_price - stop_loss_price
    else: # Short trade
        risk_per_share = stop_loss_price - entry_price

    if risk_per_share <= 0:
        return 0.0
    
    risk_amount = equity * risk_pct
    quantity = risk_amount / risk_per_share
    return float(max(quantity, 0.0))