# fetch_binance_data.py
import requests
import pandas as pd
import time
import argparse
from datetime import datetime, timezone
from utils import log

def fetch_binance_data(symbol, timeframe, start_date_str, end_date_str):
    """Fetches historical k-line data from Binance public API in chunks."""
    base_url = "https://api.binance.com/api/v3/klines"
    
    # Convert string dates to UTC timestamps in milliseconds
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    
    all_candles = []
    limit = 1000 # Binance API limit per request
    
    log(f"Fetching data for {symbol} ({timeframe}) from {start_date_str} to {end_date_str}...", "info")

    while True:
        try:
            params = {
                'symbol': symbol,
                'interval': timeframe,
                'startTime': start_ts,
                'endTime': end_ts,
                'limit': limit
            }
            
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                break # No more data in the requested range
                
            all_candles.extend(data)
            
            # Move the start time to the last candle's timestamp + 1 to get the next chunk
            start_ts = data[-1][0] + 1
            
            log(f"Fetched {len(data)} candles. Last candle time: {pd.to_datetime(data[-1][0], unit='ms')}", "debug")
            time.sleep(0.5) # Be respectful to the API

        except Exception as e:
            log(f"An error occurred: {e}", "error")
            break
            
    if not all_candles:
        log("Could not fetch any data for the specified range.", "warning")
        return None

    # Format the data into our standard CSV format
    df = pd.DataFrame(all_candles, columns=[
        'ts', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
        'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
        'taker_buy_quote_asset_volume', 'ignore'
    ])
    
    df = df[['ts', 'open', 'high', 'low', 'close', 'volume']]
    for col in df.columns:
        if col != 'ts':
            df[col] = pd.to_numeric(df[col])

    df.drop_duplicates(subset='ts', inplace=True)
    df.sort_values('ts', inplace=True)
    return df

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download historical crypto data from Binance.")
    parser.add_argument('--symbol', type=str, required=True, help='Trading symbol for Binance, e.g., BTCUSDT')
    parser.add_argument('--timeframe', type=str, required=True, help='Timeframe, e.g., 1h, 4h, 1d')
    parser.add_argument('--start', type=str, required=True, help='Start date in YYYY-MM-DD format.')
    parser.add_argument('--end', type=str, required=True, help='End date in YYYY-MM-DD format.')
    parser.add_argument('--output', type=str, required=True, help='Output CSV file name.')
    
    args = parser.parse_args()
    
    data_df = fetch_binance_data(args.symbol, args.timeframe, args.start, args.end)
    
    if data_df is not None:
        data_df.to_csv(args.output, index=False)
        log(f"Successfully saved {len(data_df)} candles to {args.output}", "success")