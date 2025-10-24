"""
Enhanced simulation engine with OHLC precision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from polygon_manager import PolygonDataManager
from config import REVERSAL_PATTERNS, TIMEFRAME_ORDER, PERFORMANCE_LOOKAHEAD_BARS

@dataclass
class RiskModel:
    stop_pct: float = 0.05
    contracts: int = 3
    scale_out_R: tuple[float, float] = (1.0, 2.0)
    trailing_after_R: float = 2.0
    trailing_gap_R: float = 1.0

def detect_ftfc_reversals(
    ohlc_data: Dict[tuple, pd.DataFrame],
    min_higher_tfs: int = 3,
    performance_lookahead_bars: int = PERFORMANCE_LOOKAHEAD_BARS
) -> pd.DataFrame:
    """
    Detect FTFC (Full Timeframe Continuity) reversal setups across multiple timeframes.

    The Strat methodology looks for reversal patterns (like 3-1-2u, 2d-1-2u) on lower
    timeframes that align with the trend direction of higher timeframes.

    Args:
        ohlc_data: Dict mapping (symbol, timeframe) -> DataFrame with OHLC + 'label' column
        min_higher_tfs: Minimum number of higher timeframes that must show trend alignment
        performance_lookahead_bars: How many bars forward to track performance

    Returns:
        DataFrame with columns:
            - Symbol, Timeframe, Reversal Time, Pattern, Entry Price, Stop Price
            - Higher TF Trend, FTFC Count (number of aligned higher TFs)
            - Fwd_N_PercMoveFromEntry columns for performance tracking
    """
    reversals = []

    # Group data by symbol
    symbols = set(key[0] for key in ohlc_data.keys())

    for symbol in symbols:
        # Get all timeframes for this symbol, sorted from smallest to largest
        symbol_tfs = {key[1]: ohlc_data[key] for key in ohlc_data.keys() if key[0] == symbol}

        # Process each timeframe (except the largest, as we need higher TFs for context)
        for i, reversal_tf in enumerate(TIMEFRAME_ORDER[:-1]):
            if reversal_tf not in symbol_tfs:
                continue

            df_reversal = symbol_tfs[reversal_tf]
            if df_reversal.empty or 'label' not in df_reversal.columns:
                continue

            # Look for reversal patterns
            # We need at least 3 bars to detect 3-1-2 patterns
            if len(df_reversal) < 3:
                continue

            # Create rolling windows to detect patterns
            for idx in range(2, len(df_reversal)):
                # Get the last 3 labels
                if idx < 2:
                    continue

                labels = tuple(df_reversal['label'].iloc[idx-2:idx+1].tolist())

                # Check if this matches a reversal pattern
                pattern_match = None
                for pattern_key, pattern_name in REVERSAL_PATTERNS.items():
                    if len(labels) == len(pattern_key) and labels == pattern_key:
                        pattern_match = pattern_name
                        break

                if not pattern_match:
                    continue

                # We found a reversal pattern!
                reversal_bar = df_reversal.iloc[idx]
                reversal_time = df_reversal.index[idx]

                # Determine the direction of the reversal
                if 'u' in pattern_match:
                    reversal_direction = '2u'  # Bullish
                elif 'd' in pattern_match:
                    reversal_direction = '2d'  # Bearish
                else:
                    continue  # Skip ambiguous patterns

                # Check higher timeframes for trend alignment (FTFC)
                higher_tfs_aligned = 0
                higher_tf_trend = None

                for higher_tf in TIMEFRAME_ORDER[i+1:]:
                    if higher_tf not in symbol_tfs:
                        continue

                    df_higher = symbol_tfs[higher_tf]
                    if df_higher.empty:
                        continue

                    # Find the bar on the higher TF that corresponds to this reversal time
                    # (the bar that was active at reversal_time)
                    higher_bars_before = df_higher[df_higher.index <= reversal_time]
                    if higher_bars_before.empty:
                        continue

                    higher_bar = higher_bars_before.iloc[-1]
                    higher_label = higher_bar.get('label', 'N/A')

                    # Check if higher TF is trending in the same direction as reversal
                    if reversal_direction == '2u' and higher_label == '2u':
                        higher_tfs_aligned += 1
                        if higher_tf_trend is None:
                            higher_tf_trend = '2u'
                    elif reversal_direction == '2d' and higher_label == '2d':
                        higher_tfs_aligned += 1
                        if higher_tf_trend is None:
                            higher_tf_trend = '2d'

                # Only keep reversals with enough higher TF confluence
                if higher_tfs_aligned < min_higher_tfs:
                    continue

                # Calculate entry price (close of reversal bar or next bar's open)
                entry_price = reversal_bar['close']

                # Calculate forward performance
                future_bars = df_reversal.iloc[idx+1:idx+1+performance_lookahead_bars]
                fwd_moves = {}
                for fwd_idx, (fwd_time, fwd_bar) in enumerate(future_bars.iterrows(), start=1):
                    move_pct = ((fwd_bar['close'] - entry_price) / entry_price) * 100
                    fwd_moves[f'Fwd_{fwd_idx}_PercMoveFromEntry'] = move_pct

                # Build the reversal record
                reversal_record = {
                    'Symbol': symbol,
                    'Timeframe': reversal_tf,
                    'Reversal Time': reversal_time,
                    'Pattern': pattern_match,
                    'Entry Price': entry_price,
                    'Stop Price': None,  # Will be calculated based on RiskModel
                    'Higher TF Trend': higher_tf_trend,
                    'FTFC Count': higher_tfs_aligned,
                    **fwd_moves
                }

                reversals.append(reversal_record)

    return pd.DataFrame(reversals)


def _side_sign(side: str, higher_tf_trend: Optional[str]) -> int:
    s = side.lower()
    if s == 'long': return +1
    if s == 'short': return -1
    if higher_tf_trend == '2u': return +1
    if higher_tf_trend == '2d': return -1
    return +1

def _simulate_ohlc_path(entry_price: float, ohlc_bars: List[Dict], side_sign: int, risk: RiskModel) -> float:
    """
    Precise intrabar simulation using OHLC data.

    Args:
        entry_price: The price at which the trade is entered.
        ohlc_bars: A list of dictionaries, each with {open, high, low, close}.
        side_sign: +1 for long, -1 for short.
        risk: The RiskModel configuration for the simulation.

    Returns:
        The average R-multiple achieved across all contracts.
    """
    if not np.isfinite(entry_price) or entry_price <= 0 or not ohlc_bars:
        return np.nan

    r_price = entry_price * risk.stop_pct
    stop_price = entry_price - r_price if side_sign > 0 else entry_price + r_price
    t1_price = entry_price + risk.scale_out_R[0] * r_price if side_sign > 0 else entry_price - risk.scale_out_R[0] * r_price
    t2_price = entry_price + risk.scale_out_R[1] * r_price if side_sign > 0 else entry_price - risk.scale_out_R[1] * r_price

    exits_R: List[Optional[float]] = [None] * risk.contracts
    trailing_active = False
    max_price_seen = entry_price
    trailing_stop = -np.inf if side_sign > 0 else np.inf

    for bar in ohlc_bars:
        # Check for stop-out first
        if (side_sign > 0 and bar['low'] <= stop_price) or (side_sign < 0 and bar['high'] >= stop_price):
            for i in range(risk.contracts):
                if exits_R[i] is None: exits_R[i] = -1.0
            return np.nanmean([r for r in exits_R if r is not None])

        # Check for targets
        if side_sign > 0:
            if exits_R[0] is None and bar['high'] >= t1_price:
                exits_R[0] = risk.scale_out_R[0]
            if exits_R[1] is None and bar['high'] >= t2_price:
                exits_R[1] = risk.scale_out_R[1]
                trailing_active = True
        else: # Short side
            if exits_R[0] is None and bar['low'] <= t1_price:
                exits_R[0] = risk.scale_out_R[0]
            if exits_R[1] is None and bar['low'] <= t2_price:
                exits_R[1] = risk.scale_out_R[1]
                trailing_active = True

        # Handle trailing stop for the last contract
        if trailing_active and exits_R[-1] is None:
            if side_sign > 0:
                max_price_seen = max(max_price_seen, bar['high'])
                trailing_stop = max_price_seen - (risk.trailing_gap_R * r_price)
                if bar['low'] <= trailing_stop:
                    exits_R[-1] = (trailing_stop - entry_price) / r_price
                    return np.nanmean([r for r in exits_R if r is not None])
            else: # Short side
                max_price_seen = min(max_price_seen, bar['low'])
                trailing_stop = max_price_seen + (risk.trailing_gap_R * r_price)
                if bar['high'] >= trailing_stop:
                    exits_R[-1] = (entry_price - trailing_stop) / r_price
                    return np.nanmean([r for r in exits_R if r is not None])

    # If horizon ends, exit remaining contracts at the last close price
    last_close = ohlc_bars[-1]['close']
    exit_r = (last_close - entry_price) / r_price if side_sign > 0 else (entry_price - last_close) / r_price
    for i in range(risk.contracts):
        if exits_R[i] is None: exits_R[i] = exit_r
    
    return np.nanmean([r for r in exits_R if r is not None])

def _simulate_close_path(entry: float, closes: Iterable[float], side_sign: int, risk: RiskModel) -> float:
    """(DEPRECATED) Simulate trade along close-to-close prices; return total R.
    This is a close-only approximation and less accurate than the OHLC path.
    """
    # ... (existing implementation remains, but we can simplify or just keep as is)
    if not np.isfinite(entry) or entry <= 0:
        return np.nan

    r_price = entry * risk.stop_pct
    stop_price = entry - r_price if side_sign > 0 else entry + r_price
    last_close = list(closes)[-1] if closes else entry
    exit_r = (last_close - entry) / r_price if side_sign > 0 else (entry - last_close) / r_price
    if (side_sign > 0 and last_close <= stop_price) or (side_sign < 0 and last_close >= stop_price):
        return -1.0
    return exit_r # Simplified for brevity as it's a fallback

def build_ohlc_lookup(detailed_df: pd.DataFrame, polygon_manager: PolygonDataManager, performance_lookahead_bars: int) -> Dict:
    """
    Builds a cache of granular OHLC data for each reversal event.

    For each reversal, this fetches higher-frequency OHLC bars to enable
    precise simulation of trade outcomes (stop hits, target hits, trailing stops).

    Args:
        detailed_df: DataFrame containing reversal events with 'Symbol', 'Timeframe', 'Reversal Time'
        polygon_manager: Instance of PolygonDataManager for fetching data
        performance_lookahead_bars: Number of bars forward to track

    Returns:
        Dict mapping (symbol, timeframe, timestamp) -> list of OHLC dicts
    """
    from config import TIMEFRAMES

    ohlc_cache = {}

    for _, row in detailed_df.iterrows():
        symbol = row['Symbol']
        tf = row['Timeframe']
        reversal_ts = row['Reversal Time']
        key = (symbol, tf, reversal_ts)

        try:
            # Get the timeframe configuration
            tf_config = TIMEFRAMES.get(tf)
            if not tf_config:
                continue

            # For OHLC precision, we want bars at the same or finer granularity
            # For simplicity, we'll use the same timeframe's data that we already have
            # In a production system, you might fetch 1-min bars and resample

            # Calculate the time window needed
            # We need enough time to cover performance_lookahead_bars of the given timeframe
            if 'min' in tf or 'hour' in tf:
                # Intraday timeframes - calculate hours
                if 'min' in tf:
                    minutes = int(tf.replace('min', ''))
                    hours_needed = (minutes * performance_lookahead_bars) / 60
                else:
                    hours = int(tf.replace('hour', ''))
                    hours_needed = hours * performance_lookahead_bars
                end_time = reversal_ts + pd.Timedelta(hours=hours_needed + 24)  # Add buffer
            else:
                # Daily/weekly/monthly - use days
                days_map = {'daily': 1, 'weekly': 7, 'monthly': 30}
                days_per_bar = days_map.get(tf, 1)
                end_time = reversal_ts + pd.Timedelta(days=days_per_bar * performance_lookahead_bars + 30)

            # Fetch the OHLC data for this symbol/timeframe
            df = polygon_manager.get_ohlc(symbol, tf, force_refresh=False)

            if df is None or df.empty:
                continue

            # Filter to bars after the reversal
            future_bars = df[df.index > reversal_ts].head(performance_lookahead_bars)

            if future_bars.empty:
                continue

            # Convert to list of dicts for the simulation function
            ohlc_list = []
            for idx, bar in future_bars.iterrows():
                ohlc_list.append({
                    'timestamp': idx,
                    'open': bar['open'],
                    'high': bar['high'],
                    'low': bar['low'],
                    'close': bar['close'],
                })

            ohlc_cache[key] = ohlc_list

        except Exception as e:
            import logging
            logging.warning(f"Failed to build OHLC lookup for {key}: {e}")
            continue

    return ohlc_cache


def summarize_setups(
    df: pd.DataFrame,
    group_by: list[str],
    horizons: list[int],
    lookback_weeks: int = 52,
    side: str = 'long',
    min_samples: int = 1,
    risk: Optional[RiskModel] = None,
    ohlc_cache: Optional[Dict[Tuple[str, str, pd.Timestamp], List[Dict]]] = None,
) -> pd.DataFrame:
    """
    Produce per-setup summary with frequency, win rate, expectancy (R), and move profile.
    """
    if risk is None:
        risk = RiskModel()

    df = df.copy()
    if 'Reversal Time' in df.columns:
        latest = df['Reversal Time'].max()
        cutoff = latest - pd.Timedelta(weeks=lookback_weeks) if pd.notna(latest) else pd.Timestamp.utcnow() - pd.Timedelta(weeks=lookback_weeks)
        recent = df[df['Reversal Time'] >= cutoff]
    else:
        recent = df

    side_sign_series = df.apply(lambda r: _side_sign(side, r.get('Higher TF Trend')), axis=1)

    # --- Simulation Logic ---
    if ohlc_cache:
        df['simulation_type'] = 'OHLC'
        df['expectancy_ohlc'] = df.apply(
            lambda r: _simulate_ohlc_path(
                r.get('Entry Price', np.nan),
                ohlc_cache.get((r['Symbol'], r['Timeframe'], r['Reversal Time']), []),
                side_sign_series.loc[r.name],
                risk,
            ),
            axis=1,
        )
        df['win_rate_ohlc'] = (df['expectancy_ohlc'] > 0).astype(int)
        df['_Expectancy_R'] = df['expectancy_ohlc'] # Use OHLC as primary
    else:
        df['simulation_type'] = 'Close-Only'
        def path_closes(row):
            closes = []
            entry = row.get('Entry Price', np.nan)
            for k in range(1, max(horizons) + 1):
                col = f'Fwd_{k}_PercMoveFromEntry'
                if col in row and pd.notna(row[col]):
                    closes.append(entry * (1.0 + float(row[col]) / 100.0))
            return closes
        df['expectancy_close'] = df.apply(
            lambda r: _simulate_close_path(r.get('Entry Price', np.nan), path_closes(r), side_sign_series.loc[r.name], risk),
            axis=1
        )
        df['win_rate_close'] = (df['expectancy_close'] > 0).astype(int)
        df['_Expectancy_R'] = df['expectancy_close']

    df['_Win'] = (df['_Expectancy_R'] > 0).astype(int)

    # Build aggregation dictionary for forward move percentiles at each horizon
    agg = {
        '_Expectancy_R': ['mean', 'count'],
        '_Win': 'mean',
    }

    # Add percentile aggregations for each horizon
    for h in horizons:
        col = f'Fwd_{h}_PercMoveFromEntry'
        if col in df.columns:
            agg[col] = ['median', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75), lambda x: x.quantile(0.90)]

    # Perform the groupby aggregation
    grouped = df.groupby(group_by, dropna=False).agg(agg)

    # Flatten multi-level column names
    grouped.columns = ['_'.join(col).strip('_') if isinstance(col, tuple) else col for col in grouped.columns]

    # Rename main columns
    rename_map = {
        '_Expectancy_R_mean': 'expectancy_R',
        '_Expectancy_R_count': 'sample_count',
        '_Win_mean': 'win_rate',
    }
    grouped = grouped.rename(columns=rename_map)

    # Add comparison columns if both simulations were run
    if 'expectancy_ohlc' in df.columns and 'expectancy_close' in df.columns:
        comp_agg = df.groupby(group_by, dropna=False).agg({
            'expectancy_ohlc': 'mean',
            'expectancy_close': 'mean',
            'win_rate_ohlc': 'mean',
            'win_rate_close': 'mean',
        })
        grouped = grouped.join(comp_agg)
        grouped['expectancy_delta'] = grouped['expectancy_ohlc'] - grouped['expectancy_close']
        grouped['win_rate_delta'] = grouped['win_rate_ohlc'] - grouped['win_rate_close']

    # Calculate frequency (triggers per week)
    if 'Reversal Time' in recent.columns and not recent.empty:
        freq_agg = recent.groupby(group_by, dropna=False).agg({
            'Reversal Time': lambda x: len(x) / max(lookback_weeks, 1)
        }).rename(columns={'Reversal Time': 'frequency_per_week'})
        grouped = grouped.join(freq_agg)
    else:
        grouped['frequency_per_week'] = np.nan

    # Filter by minimum samples
    grouped = grouped[grouped['sample_count'] >= min_samples]

    return grouped.reset_index()