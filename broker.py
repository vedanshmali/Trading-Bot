import ccxt, os
from dotenv import load_dotenv
load_dotenv()

def create_exchange(exchange_id: str, sandbox: bool, options: dict | None = None):
    klass = getattr(ccxt, exchange_id)
    api_key = os.getenv('API_KEY') or ''
    api_secret = os.getenv('API_SECRET') or ''
    params = {'enableRateLimit': True}
    if options:
        params['options'] = options
    exchange = klass({
        'apiKey': api_key,
        'secret': api_secret,
        **params,
    })
    # CoinDCX has no sandbox; keeping the flag for API parity
    exchange.load_markets()
    return exchange

def get_balance_usdt(exchange):
    try:
        bal = exchange.fetch_balance()
        # prefer 'free' balances if present
        for pocket in ('free', 'total'):
            d = bal.get(pocket, {})
            if isinstance(d, dict):
                for code in ('USDT','USD','USDC'):
                    if code in d:
                        return float(d[code])
        # fallback
        for code in ('USDT','USD','USDC'):
            if code in bal:
                try:
                    return float(bal[code])
                except:
                    pass
    except Exception:
        pass
    return None

def market_info(exchange, symbol):
    m = exchange.market(symbol)
    price_prec = m.get('precision', {}).get('price', 2)
    amt_prec   = m.get('precision', {}).get('amount', 6)
    min_cost   = m.get('limits', {}).get('cost', {}).get('min', None)
    amount_step = m.get('limits', {}).get('amount', {}).get('step', None)
    if amount_step is None:
        p = amt_prec if isinstance(amt_prec, int) else 6
        amount_step = 10 ** (-p)
    return {
        'price_precision': price_prec,
        'amount_precision': amt_prec,
        'min_cost': min_cost,
        'min_qty_step': amount_step
    }
