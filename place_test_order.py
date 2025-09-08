import os, time, math
from dotenv import load_dotenv
from coindcx_client import CoinDCXClient

load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
client = CoinDCXClient(API_KEY, API_SECRET)

MARKET = "BTCUSDT"       # spot market code without slash
NOTIONAL_USDT = 5.10     # small cushion over 5
FEE_BUFFER = 0.995       # leave a bit for fees
STEP = 1e-8              # BTC precision = 8 dp

def round_step(x, step):
    return math.floor(x / step) * step

# 1) check USDT free balance
bals = client.fetch_balances()
usdt_free = next((float(b.get('balance',0)) for b in bals if str(b.get('currency')).upper()=='USDT'), 0.0)
print("USDT free:", usdt_free)
if usdt_free < NOTIONAL_USDT * 0.98:
    raise SystemExit("Not enough USDT for test trade. Reduce NOTIONAL_USDT or top up.")

# 2) get a fresh approximate price (last 1m close)
raw = client.fetch_candles("BTC/USDT", timeframe="1m", limit=2)
last_close = float(raw[-1][4])
print("Last close:", last_close)

# 3) convert desired USDT notional -> base qty (BTC) and round to 8 dp
qty_btc_raw = (NOTIONAL_USDT / last_close) * FEE_BUFFER
qty_btc = round_step(qty_btc_raw, STEP)
print(f"Planned BUY: ~{NOTIONAL_USDT} USDT ≈ {qty_btc:.8f} BTC (raw {qty_btc_raw:.12f})")

if qty_btc <= 0:
    raise SystemExit("Computed qty too small after rounding. Increase NOTIONAL_USDT slightly.")

# 4) place market BUY with base qty (8 dp)
resp_buy = client.create_spot_order_market(market=MARKET, side='buy', total_quantity=qty_btc)
print("BUY resp:", resp_buy)

print("Wait 3s…")
time.sleep(3)

# 5) SELL the same BTC amount back
print(f"Planned SELL: {qty_btc:.8f} BTC")
resp_sell = client.create_spot_order_market(market=MARKET, side='sell', total_quantity=qty_btc)
print("SELL resp:", resp_sell)

print("Done. Check CoinDCX → Orders → Spot → History for BTC/USDT.")
