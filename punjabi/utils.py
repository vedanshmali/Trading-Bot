import json
import os
import time
from datetime import datetime, timezone, timedelta

def read_state(path='state.json'):
    """Reads the current bot state from a JSON file."""
    if not os.path.exists(path):
        return {"position": None}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupt or empty, return default state
        return {"position": None}

def write_state(state, path='state.json'):
    """Writes the bot's current state to a JSON file."""
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)

def get_sleep_time(timeframe: str) -> int:
    """Calculates the number of seconds to sleep until the next full candle."""
    now = datetime.now(timezone.utc)
    
    # Convert timeframe string (e.g., '15m', '1h') to seconds
    if 'm' in timeframe:
        minutes = int(timeframe.replace('m', ''))
        delta = timedelta(minutes=minutes)
    elif 'h' in timeframe:
        hours = int(timeframe.replace('h', ''))
        delta = timedelta(hours=hours)
    else: # Default to 15 minutes if format is unknown
        delta = timedelta(minutes=15)
        
    # Calculate the timestamp of the next candle
    next_candle_ts = ((now.timestamp() // delta.total_seconds()) + 1) * delta.total_seconds()
    
    # Calculate sleep duration, add a small buffer (e.g., 5 seconds)
    sleep_duration = next_candle_ts - now.timestamp() + 5
    return max(sleep_duration, 0)

def log(message, level="info"):
    """Simple colored logger."""
    now = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    color_map = {
        "info": "\033[94m", "debug": "\033[90m", "success": "\033[92m",
        "warning": "\033[93m", "error": "\033[91m", "end": "\033[0m",
    }
    color = color_map.get(level.lower(), "")
    end_color = color_map["end"] if color else ""
    print(f"{color}[{now}] [{level.upper()}] {message}{end_color}")