"""
Centralized configuration for Strat Analysis Decision Engine
"""
from typing import List, Tuple, Dict, Optional, Callable

# Polygon.io API Configuration
POLYGON_API_KEY_ENV = "POLYGON_API_KEY"
POLYGON_RATE_LIMIT_DELAY = 0.01  # seconds between requests (100/sec for paid)

# Cache Settings
CACHE_DIR = "./data/polygon_cache"
CACHE_MAX_AGE_HOURS = 24  # How long cached data stays fresh
OHLC_MONTHS_BACK = 6  # Default history to fetch

# Timeframe Definitions
TIMEFRAMES = {
    '30min': {'polygon_multiplier': 30, 'polygon_timespan': 'minute', 'resample_freq': '30T', 'display_name': '30 Min'},
    '1hour': {'polygon_multiplier': 1, 'polygon_timespan': 'hour', 'resample_freq': '1H', 'display_name': '1 Hour'},
    '2hour': {'polygon_multiplier': 2, 'polygon_timespan': 'hour', 'resample_freq': '2H', 'display_name': '2 Hour'},
    '4hour': {'polygon_multiplier': 4, 'polygon_timespan': 'hour', 'resample_freq': '4H', 'display_name': '4 Hour'},
    'daily': {'polygon_multiplier': 1, 'polygon_timespan': 'day', 'resample_freq': 'D', 'display_name': 'Daily'},
    'weekly': {'polygon_multiplier': 1, 'polygon_timespan': 'week', 'resample_freq': 'W', 'display_name': 'Weekly'},
    'monthly': {'polygon_multiplier': 1, 'polygon_timespan': 'month', 'resample_freq': 'M', 'display_name': 'Monthly'},
}

# Timeframe hierarchy for FTFC analysis (smallest to largest)
TIMEFRAME_ORDER = ['30min', '1hour', '2hour', '4hour', 'daily', 'weekly', 'monthly']

# Default symbols for quick selection
DEFAULT_SYMBOLS = [
    'SPY', 'QQQ', 'IWM', 'DIA',  # Indices
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',  # Mega caps
    'AMD', 'AVGO', 'QCOM', 'MU',  # Semiconductors
    'JPM', 'BAC', 'GS', 'MS',  # Financials
    'XLE', 'XLF', 'XLK', 'XLV',  # Sector ETFs
]

# Extended symbol universe (200+ symbols)
EXTENDED_SYMBOLS = DEFAULT_SYMBOLS + [
    'ABBV', 'ADBE', 'AGG', 'ARKK', 'BA', 'C', 'CAT', 'COIN', 'COST', 'CRM',
    'CSCO', 'CVX', 'DIS', 'DOW', 'EEM', 'EFA', 'F', 'FXI', 'GLD', 'GME',
    'HD', 'HON', 'IBM', 'INTC', 'JNJ', 'KO', 'LLY', 'LMT', 'MA', 'MCD',
    'MRK', 'MRNA', 'NKE', 'ORCL', 'PEP', 'PFE', 'PG', 'PYPL', 'RTX', 'SBUX',
    'SLV', 'SOFI', 'SQ', 'T', 'TGT', 'TMUS', 'UNH', 'V', 'VZ', 'WFC', 'WMT', 'XOM'
    # Add more symbols as needed
]

# The Strat Pattern Definitions
REVERSAL_PATTERNS = {
    ("3", "1", "2u"): "3-1-2u",
    ("3", "1", "2d"): "3-1-2d",
    ("2u", "1", "2d"): "2u-1-2d",
    ("2d", "1", "2u"): "2d-1-2u",
    ("2u", "2d"): "2u-2d",
    ("2d", "2u"): "2d-2u",
}

# Analysis Parameters
MIN_HIGHER_TFS_FOR_FTFC = 3  # Minimum higher timeframes needed for confluence
PERFORMANCE_LOOKAHEAD_BARS = 10  # How many bars forward to track performance

# Risk Model Defaults
DEFAULT_STOP_PCT = 0.05  # 5% stop loss
DEFAULT_CONTRACTS = 3  # Scale out across 3 positions
DEFAULT_SCALE_OUT_R = [1.0, 2.0]  # Scale at +1R and +2R
DEFAULT_TRAILING_AFTER_R = 2.0  # Start trailing after +2R
DEFAULT_TRAILING_GAP_R = 1.0  # Trail 1R below max favorable price

# Live Signals Configuration
LIVE_SIGNALS_LOOKBACK_DAYS = 5  # How many days back to scan for recent setups
LIVE_SIGNALS_REFRESH_SECONDS = 300  # 5-minute auto-refresh
LIVE_SIGNALS_MIN_EXPECTANCY = 0.3  # Minimum R-expectancy to display
LIVE_SIGNALS_MIN_FREQUENCY = 1.0  # Minimum triggers per week

# Options Configuration
OPTIONS_MIN_DTE = 7  # Minimum days to expiration
OPTIONS_MAX_DTE = 45  # Maximum days to expiration
OPTIONS_STRIKE_RANGE_PCT = 0.15  # ±15% from current price
OPTIONS_MIN_VOLUME = 10  # Minimum option volume to consider liquid
OPTIONS_MIN_OPEN_INTEREST = 50  # Minimum OI to consider liquid

# UI Configuration
STATUS_EMOJI = {
    'fresh': '🟢',
    'stale': '🟡',
    'missing': '🔴',
    'loading': '⏳',
    'success': '✅',
    'warning': '⚠️',
    'error': '❌',
}

# Display formatting
CURRENCY_FORMAT = "${:,.2f}"
PERCENT_FORMAT = "{:+.2f}%"
R_MULTIPLE_FORMAT = "{:+.2f}R"

def validate_timeframe(tf: str) -> bool:
    """
    Validates if a given timeframe string is a valid key in the TIMEFRAMES dictionary.

    Args:
        tf: The timeframe string to validate.

    Returns:
        True if the timeframe is valid, False otherwise.
    """
    return tf in TIMEFRAMES
