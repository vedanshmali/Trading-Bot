# markets_check.py
from coindcx_client import CoinDCXClient

c = CoinDCXClient()

print("Fetching markets...")
mkts = c.list_markets()
print(f"Count markets: {len(mkts)} (first 20): {mkts[:20]}")

print("\nTrying to fetch detailed market info...")
try:
    details = c.market_details()
    print(f"Count market_details: {len(details)} (showing ETH/USDT & BTC/USDT if present)")
    for m in details:
        sym = str(m.get('symbol','')).upper()
        if sym in ('ETHUSDT','BTCUSDT','ETHINR','BTCINR'):
            print({'symbol': m.get('symbol'), 'pair': m.get('pair'), 'ecode': m.get('ecode')})
except FileNotFoundError:
    print("market_details is 404 here — will probe candles pairs directly.")

def try_symbol(sym):
    sym_slash = f"{sym[:-4]}/{sym[-4:]}" if sym.endswith(("USDT","INR","USD","BTC")) else sym
    try:
        order_symbol, pair = c.resolve_symbol_and_pair(sym_slash, timeframe="1h")
        print(f"OK: {sym_slash} -> order_symbol={order_symbol}, candles_pair={pair}")
    except Exception as e:
        print(f"FAIL: {sym_slash} -> {e}")

print("\nProbing common symbols:")
for sym in ("ETHUSDT","BTCUSDT","ETHINR","BTCINR"):
    try_symbol(sym)
