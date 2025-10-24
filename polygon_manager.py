"""
High-level data management for Polygon.io with intelligent caching.
"""
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from config import CACHE_DIR, CACHE_MAX_AGE_HOURS, TIMEFRAMES
from polygon_client import PolygonClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

class PolygonDataManager:
    """
    Manages fetching, caching, and processing of OHLC data from Polygon.io.
    """

    def __init__(self, api_key: str, cache_dir: str = CACHE_DIR):
        """
        Initializes the data manager.

        Args:
            api_key: Your Polygon.io API key.
            cache_dir: The directory to store cached data.
        """
        self.client = PolygonClient(api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, symbol: str, timeframe: str) -> Path:
        """
        Generates the cache file path for a given symbol and timeframe.
        """
        return self.cache_dir / f"{symbol.upper()}_{timeframe}.parquet"

    def _is_cache_valid(self, cache_path: Path, max_age_hours: int) -> bool:
        """
        Checks if a cache file exists and is within the maximum age.
        """
        if not cache_path.exists():
            return False
        
        file_mod_time = cache_path.stat().st_mtime
        age_seconds = time.time() - file_mod_time
        age_hours = age_seconds / 3600
        
        return age_hours < max_age_hours

    def _validate_ohlc(self, df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Performs data quality checks on an OHLC DataFrame.
        """
        original_len = len(df)
        
        # Remove rows with NaN in essential columns
        df = df.dropna(subset=['open', 'high', 'low', 'close'])
        if len(df) < original_len:
            logging.warning(f"[{symbol}|{timeframe}] Removed {original_len - len(df)} rows with NaNs.")

        # Remove invalid candles
        invalid_candles = df[df['high'] < df['low']]
        if not invalid_candles.empty:
            logging.warning(f"[{symbol}|{timeframe}] Removed {len(invalid_candles)} invalid candles (high < low).")
            df = df[df['high'] >= df['low']]

        # Remove zero/negative prices
        negative_prices = df[(df['open'] <= 0) | (df['high'] <= 0) | (df['low'] <= 0) | (df['close'] <= 0)]
        if not negative_prices.empty:
            logging.warning(f"[{symbol}|{timeframe}] Removed {len(negative_prices)} rows with zero/negative prices.")
            df = df[~((df['open'] <= 0) | (df['high'] <= 0) | (df['low'] <= 0) | (df['close'] <= 0))]

        # TODO: Detect large time gaps

        return df

    def _add_strat_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds 'label' column with Strat classifications: '1', '2u', '2d', '3'.
        """
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)

        conditions = [
            (df['high'] > df['prev_high']) & (df['low'] < df['prev_low']),  # Outside bar (3)
            (df['high'] <= df['prev_high']) & (df['low'] >= df['prev_low']), # Inside bar (1)
            (df['high'] > df['prev_high']) & (df['low'] >= df['prev_low']),  # Directional up (2u)
            (df['high'] <= df['prev_high']) & (df['low'] < df['prev_low']),   # Directional down (2d)
        ]
        choices = ['3', '1', '2u', '2d']
        
        df['label'] = pd.Series(pd.NA, index=df.index)
        df['label'] = pd.Series(np.select(conditions, choices, default='N/A'), index=df.index)

        df.loc[df.index[0], 'label'] = 'N/A' # First bar has no label
        
        return df.drop(columns=['prev_high', 'prev_low'])

    def get_ohlc(
        self, 
        symbol: str, 
        timeframe: str, 
        force_refresh: bool = False, 
        months_back: int = 6
    ) -> Optional[pd.DataFrame]:
        """
        Main method to get OHLC data using a cache-first approach.
        """
        cache_path = self._get_cache_path(symbol, timeframe)

        if not force_refresh and self._is_cache_valid(cache_path, CACHE_MAX_AGE_HOURS):
            try:
                df = pd.read_parquet(cache_path)
                logging.info(f"[{symbol}|{timeframe}] Loaded {len(df)} bars from cache.")
                return df
            except Exception as e:
                logging.error(f"[{symbol}|{timeframe}] Failed to read from cache: {e}. Fetching fresh data.")

        logging.info(f"[{symbol}|{timeframe}] Cache miss or refresh forced. Fetching from Polygon.")
        tf_config = TIMEFRAMES[timeframe]
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=months_back * 30)).strftime('%Y-%m-%d')

        df = self.client.get_bars(
            symbol=symbol,
            timespan=tf_config['polygon_timespan'],
            multiplier=tf_config['polygon_multiplier'],
            from_date=from_date,
            to_date=to_date,
        )

        if df is None or df.empty:
            logging.warning(f"[{symbol}|{timeframe}] No data fetched from Polygon.")
            return None

        df = self._validate_ohlc(df, symbol, timeframe)
        df = self._add_strat_labels(df)

        # Save to cache atomically
        temp_path = cache_path.with_suffix('.tmp')
        try:
            df.to_parquet(temp_path, compression='snappy')
            os.replace(temp_path, cache_path)
            logging.info(f"[{symbol}|{timeframe}] Saved {len(df)} bars to cache.")
        except Exception as e:
            logging.error(f"[{symbol}|{timeframe}] Failed to save to cache: {e}")
            if temp_path.exists():
                os.remove(temp_path)

        return df

    def batch_fetch(
        self, 
        symbols: List[str], 
        timeframes: List[str], 
        months_back: int = 6, 
        progress_callback: Optional[Callable] = None
    ) -> Dict[Tuple[str, str], pd.DataFrame]:
        """
        Fetch data for multiple symbols and timeframes efficiently.
        """
        results = {}
        total_tasks = len(symbols) * len(timeframes)
        completed_tasks = 0

        for symbol in symbols:
            for timeframe in timeframes:
                completed_tasks += 1
                if progress_callback:
                    progress_callback(completed_tasks, total_tasks, symbol, timeframe)
                
                try:
                    df = self.get_ohlc(symbol, timeframe, months_back=months_back)
                    if df is not None:
                        results[(symbol, timeframe)] = df
                except Exception as e:
                    logging.error(f"[BATCH] Failed to fetch {symbol}|{timeframe}: {e}")
        
        return results

    def get_cache_stats(self) -> pd.DataFrame:
        """
        Returns a DataFrame with statistics about the cache.
        """
        records = []
        for path in self.cache_dir.glob('*.parquet'):
            try:
                symbol, timeframe = path.stem.split('_')
                stat = path.stat()
                age_hours = (time.time() - stat.st_mtime) / 3600
                size_mb = stat.st_size / (1024 * 1024)

                if age_hours < 24:
                    status = '🟢' # Fresh
                elif 24 <= age_hours <= 168:
                    status = '🟡' # Stale
                else:
                    status = '🔴' # Expired

                # To get bar count and dates, we need to read the file
                df = pd.read_parquet(path)
                records.append({
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'bars_count': len(df),
                    'start_date': df.index.min().strftime('%Y-%m-%d'),
                    'end_date': df.index.max().strftime('%Y-%m-%d'),
                    'age_hours': round(age_hours, 2),
                    'size_mb': round(size_mb, 3),
                    'status_emoji': status,
                })
            except Exception as e:
                logging.warning(f"Could not process cache file {path.name}: {e}")
        
        return pd.DataFrame(records)

    def clear_cache(
        self, 
        symbols: Optional[List[str]] = None, 
        older_than_days: Optional[int] = None
    ):
        """
        Clear cache selectively.
        """
        for path in self.cache_dir.glob('*.parquet'):
            clear = False
            if symbols:
                symbol, _ = path.stem.split('_')
                if symbol in symbols:
                    clear = True
            elif older_than_days is not None:
                age_days = (time.time() - path.stat().st_mtime) / (3600 * 24)
                if age_days > older_than_days:
                    clear = True
            else: # Clear all
                clear = True
            
            if clear:
                try:
                    path.unlink()
                    logging.info(f"Removed {path.name} from cache.")
                except OSError as e:
                    logging.error(f"Error removing {path.name}: {e}")

    def preload_symbols(
        self, 
        symbols: List[str], 
        timeframes: List[str], 
        force: bool = False
    ) -> Dict:
        """
        Preload cache for common symbols.
        """
        success_count = 0
        failure_count = 0
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    df = self.get_ohlc(symbol, timeframe, force_refresh=force)
                    if df is not None and not df.empty:
                        success_count += 1
                    else:
                        failure_count += 1
                except Exception as e:
                    logging.error(f"[PRELOAD] Failed for {symbol}|{timeframe}: {e}")
                    failure_count += 1
        return {'success': success_count, 'failure': failure_count}
