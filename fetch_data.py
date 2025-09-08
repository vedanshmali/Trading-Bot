# fetch_data.py
import pandas as pd
import time
import argparse
from datetime import datetime, timedelta
from coindcx_client import CoinDCXClient
from utils import log

def fetch_and_save_data(symbol, timeframe, days, output_file):
    """Fetches historical data in chunks and saves it to a CSV file."""
    client = CoinDCXClient()
    log(f"Starting data download for {symbol} on {timeframe} for the last {days} days.")

    # CoinDCX API limit is 1000 candles per request
    limit = 1000
    all_candles = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # Note: CoinDCX public API does not support pagination with timestamps.
    # This approach fetches the last 1000 candles from the most recent point.
    # For a true historical fetch covering years, you'd need a different data source or a premium API.
    # However, this will give us the max available data from the free endpoint.
    try:
        log(f"Fetching up to {limit} most recent candles for {symbol}...", "info")
        candles = client.fetch_candles(symbol, timeframe, limit=limit)
        all_candles.extend(candles)

        df = pd.DataFrame(all_candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df.drop_duplicates(subset='ts', inplace=True)
        df.sort_values('ts', inplace=True)

        df.to_csv(output_file, index=False)
        start_date_str = pd.to_datetime(df['ts'].iloc[0], unit='ms')
        end_date_str = pd.to_datetime(df['ts'].iloc[-1], unit='ms')
        log(f"Successfully saved {len(df)} candles to {output_file}", "success")
        log(f"Data ranges from {start_date_str} to {end_date_str}", "info")

    except Exception as e:
        log(f"An error occurred: {e}", "error")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download historical crypto data from CoinDCX.")
    parser.add_argument('--symbol', type=str, default='BTC/USDT', help='Trading symbol, e.g., BTC/USDT')
    parser.add_argument('--timeframe', type=str, default='1h', help='Timeframe, e.g., 1h, 4h, 1d')
    parser.add_argument('--days', type=int, default=41, help='Number of days of data to attempt to fetch (limited by API).')
    parser.add_argument('--output', type=str, default='data.csv', help='Output CSV file name.')

    args = parser.parse_args()
    fetch_and_save_data(args.symbol, args.timeframe, args.days, args.output)