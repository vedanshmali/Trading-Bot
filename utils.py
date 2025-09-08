# utils.py
import json
import os
import math
from datetime import datetime, timezone

def log(level: str, msg: str) -> None:
    """Simple logger with timestamp + level."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level.upper()}] {msg}")

def ts_to_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

def round_step(value: float, step: float) -> float:
    if not step:
        return value
    return math.floor(value / step) * step

def read_state(path: str = 'state.json'):
    if not os.path.exists(path):
        return {"position": None, "equity": None, "consecutive_losses": 0}
    with open(path, 'r') as f:
        return json.load(f)

def write_state(state, path: str = 'state.json'):
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)
