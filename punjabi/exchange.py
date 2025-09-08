import ccxt
import os
from utils import log

def create_exchange(cfg: dict) -> ccxt.Exchange:
    """Initializes and returns a ccxt exchange instance."""
    exchange_id = cfg.get('exchange_id')
    if not exchange_id:
        raise ValueError("exchange_id not found in config.")

    try:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({
            'apiKey': os.getenv('EXCHANGE_API_KEY'),
            'secret': os.getenv('EXCHANGE_API_SECRET'),
            'options': {
                'defaultType': 'spot',
            },
        })
        exchange.load_markets()
        log(f"Successfully connected to {exchange.name}.", "success")
        return exchange
    except Exception as e:
        log(f"Error connecting to exchange: {e}", "error")
        raise

def fetch_candles(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int):
    """Fetches the latest OHLCV candle data."""
    try:
        # ccxt returns data in a standard format: [timestamp, open, high, low, close, volume]
        return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        log(f"Error fetching candles: {e}", "error")
        return None

def create_market_order(exchange: ccxt.Exchange, symbol: str, side: str, amount: float):
    """Places a market order on the exchange."""
    log(f"Placing market order: {side.upper()} {amount:.8f} {symbol}", "warning")
    try:
        # We need to format the amount to the exchange's required precision
        market = exchange.market(symbol)
        formatted_amount = exchange.amount_to_precision(symbol, amount)
        
        order = exchange.create_order(market['symbol'], 'market', side, formatted_amount)
        log(f"Order placed successfully. Order ID: {order.get('id')}", "success")
        return order
    except Exception as e:
        log(f"Error placing order: {e}", "error")
        return None