# coindcx_client.py
import time, hmac, hashlib, json, requests
from typing import Dict, Any, List, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PUBLIC_BASE = "https://public.coindcx.com"
PRIVATE_BASE = "https://api.coindcx.com"

class CoinDCXClient:
    """
    More robust CoinDCX REST client with resilient session, pair resolution,
    and fallback mechanisms for fetching candle data.
    """
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, timeout: int = 20):
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.session = self._create_resilient_session()

    def _create_resilient_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=5, connect=5, read=5,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
        session.mount("https://", adapter)
        session.headers.update({"Connection": "keep-alive"})
        return session

    def _probe_pair(self, symbol_with_slash: str, timeframe: str = "1h") -> Optional[str]:
        core = symbol_with_slash.replace("/", "_").upper()
        # Common prefixes used by CoinDCX for pairs
        for pfx in ("I-", "B-", "HB-", "H-", "OE-", "BM-", ""):
            test_pair = f"{pfx}{core}"
            url = f"{PUBLIC_BASE}/market_data/candles/?pair={test_pair}&interval={timeframe}&limit=1"
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        return test_pair
            except requests.RequestException:
                continue
        return None

    def resolve_candles_pair(self, symbol_with_slash: str, timeframe: str = "1h") -> str:
        pair = self._probe_pair(symbol_with_slash, timeframe)
        if pair:
            return pair
        raise RuntimeError(f"Could not resolve a valid candles 'pair' for {symbol_with_slash} on CoinDCX.")

    def _normalize_candles(self, data: List[Dict]) -> List[List[float]]:
        out: List[List[float]] = []
        if not isinstance(data, list) or not data:
            return out
        for row in data:
            try:
                # Standard OHLCV format from CoinDCX candles endpoint
                out.append([
                    int(row['time']), float(row['open']), float(row['high']),
                    float(row['low']), float(row['close']), float(row['volume'])
                ])
            except (KeyError, TypeError):
                continue
        out.sort(key=lambda x: x[0])
        return out

    def fetch_candles(self, symbol_with_slash: str, timeframe: str = "1m", limit: int = 500) -> List[List[float]]:
        pair = self.resolve_candles_pair(symbol_with_slash, timeframe)
        lim = min(int(limit), 1000)
        url = f"{PUBLIC_BASE}/market_data/candles/?pair={pair}&interval={timeframe}&limit={lim}"
        try:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            norm = self._normalize_candles(r.json())
            if not norm:
                raise RuntimeError(f"Candle data for pair '{pair}' was empty.")
            return norm
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch candles for {symbol_with_slash} (pair: {pair}): {e}")
        except Exception as e:
            raise RuntimeError(f"An unexpected error occurred while fetching candles: {e}")

    def _auth_headers(self, body: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret must be provided for private endpoints.")
        json_body = json.dumps(body, separators=(',', ':'))
        signature = hmac.new(self.api_secret.encode(), json_body.encode(), hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.api_key,
            "X-AUTH-SIGNATURE": signature,
        }, json_body

    def fetch_balances(self) -> List[Dict[str, Any]]:
        url = f"{PRIVATE_BASE}/exchange/v1/users/balances"
        body = {"timestamp": int(time.time() * 1000)}
        headers, json_body = self._auth_headers(body)
        r = self.session.post(url, data=json_body, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def create_spot_order_market(self, market: str, side: str, total_quantity: float) -> Dict[str, Any]:
        url = f"{PRIVATE_BASE}/exchange/v1/orders/create"
        body = {
            "market": market,
            "side": side.lower(),
            "order_type": "market_order",
            "total_quantity": float(total_quantity),
            "timestamp": int(time.time() * 1000),
        }
        headers, json_body = self._auth_headers(body)
        r = self.session.post(url, data=json_body, headers=headers, timeout=self.timeout)
        
        try:
            data = r.json()
        except json.JSONDecodeError:
            raise RuntimeError(f"Order API returned non-JSON response ({r.status_code}): {r.text}")

        if r.status_code >= 400:
            raise RuntimeError(f"Order error {r.status_code}: {data}")
        return data