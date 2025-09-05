from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


@dataclass
class RiskModel:
    stop_pct: float = 0.05  # 5%
    contracts: int = 3
    scale_out_R: tuple[float, float] = (1.0, 2.0)  # +1R, +2R
    trailing_after_R: float = 2.0  # start trailing after +2R hit
    trailing_gap_R: float = 1.0  # trail at 1R below max close


def _side_sign(side: str, higher_tf_trend: Optional[str]) -> int:
    # side: 'long' | 'short' | 'auto'
    s = side.lower()
    if s == 'long':
        return +1
    if s == 'short':
        return -1
    # auto: map higher TF trend to side
    if higher_tf_trend == '2u':
        return +1
    if higher_tf_trend == '2d':
        return -1
    return +1


def _simulate_close_path(entry: float, closes: Iterable[float], side_sign: int, risk: RiskModel) -> float:
    """Simulate trade along close-to-close prices; return total R across 3 contracts.

    Notes:
    - Uses close prices only (no intrabar OHLC).
    - For side_sign = +1 (long): R = (price - entry) / (entry * stop_pct)
      For side_sign = -1 (short): R = (entry - price) / (entry * stop_pct)
    - Scale exits: 1/3 each at +1R, +2R, and trailing on last third.
    - If stop is touched by close before targets, entire position exits at -1R.
    - If no full exit by horizon end, exit remaining at last close.
    """
    if not np.isfinite(entry) or entry <= 0:
        return np.nan

    r_price = entry * risk.stop_pct

    # Target levels (in price) relative to entry
    def price_at_R(r: float) -> float:
        if side_sign > 0:
            return entry + r * r_price
        else:
            return entry - r * r_price

    stop_price = price_at_R(-1.0)
    t1_price = price_at_R(risk.scale_out_R[0])
    t2_price = price_at_R(risk.scale_out_R[1])

    # Track exits (per-contract R)
    exits_R: List[Optional[float]] = [None, None, None]
    have_t1 = False
    have_t2 = False
    trailing_active = False
    max_close_seen = entry
    min_close_seen = entry
    trailing_stop_price = None

    def r_from_price(p: float) -> float:
        # Convert a price to R multiple based on side
        if side_sign > 0:
            return (p - entry) / r_price
        else:
            return (entry - p) / r_price

    for c in closes:
        if not np.isfinite(c):
            continue

        # Stop check (close-only). If stop hit before targets, all contracts exit at -1R.
        if (side_sign > 0 and c <= stop_price) or (side_sign < 0 and c >= stop_price):
            exits_R = [-1.0, -1.0 if exits_R[1] is None else exits_R[1], -1.0 if exits_R[2] is None else exits_R[2]]
            # If any prior partial exits, keep them; remaining exit at -1R
            return np.nanmean([r for r in exits_R if r is not None])

        # Hit T1/T2 by close?
        if not have_t1 and ((side_sign > 0 and c >= t1_price) or (side_sign < 0 and c <= t1_price)):
            exits_R[0] = risk.scale_out_R[0]
            have_t1 = True

        if not have_t2 and ((side_sign > 0 and c >= t2_price) or (side_sign < 0 and c <= t2_price)):
            exits_R[1] = risk.scale_out_R[1]
            have_t2 = True
            trailing_active = True
            # initialize trailing stop from this bar's close
            max_close_seen = c if side_sign > 0 else max_close_seen
            min_close_seen = c if side_sign < 0 else min_close_seen
            base = max_close_seen if side_sign > 0 else min_close_seen
            gap = risk.trailing_gap_R * r_price
            trailing_stop_price = base - gap if side_sign > 0 else base + gap

        # Update trailing after +2R
        if trailing_active:
            if side_sign > 0:
                max_close_seen = max(max_close_seen, c)
                trailing_stop_price = max(trailing_stop_price, max_close_seen - risk.trailing_gap_R * r_price)
                if c <= trailing_stop_price:
                    exits_R[2] = r_from_price(trailing_stop_price)
                    return np.nanmean([r for r in exits_R if r is not None])
            else:
                min_close_seen = min(min_close_seen, c)
                trailing_stop_price = min(trailing_stop_price, min_close_seen + risk.trailing_gap_R * r_price) if trailing_stop_price is not None else (min_close_seen + risk.trailing_gap_R * r_price)
                if c >= trailing_stop_price:
                    exits_R[2] = r_from_price(trailing_stop_price)
                    return np.nanmean([r for r in exits_R if r is not None])

    # If we reached the horizon without complete exits, close remaining at last close
    if len(list(closes)) == 0:
        return 0.0

    last_c = list(closes)[-1]
    if exits_R[0] is None:
        # nothing exited; all exit at last close
        r_val = r_from_price(last_c)
        return r_val
    if exits_R[1] is None:
        # only first third out
        r_val = np.nanmean([exits_R[0], r_from_price(last_c), r_from_price(last_c)])
        return r_val
    if exits_R[2] is None:
        # two thirds out
        r_val = np.nanmean([exits_R[0], exits_R[1], r_from_price(last_c)])
        return r_val
    return np.nanmean([r for r in exits_R if r is not None])


def summarize_setups(
    df: pd.DataFrame,
    group_by: list[str],
    horizons: list[int],
    lookback_weeks: int = 52,
    side: str = 'long',
    min_samples: int = 1,
    risk: Optional[RiskModel] = None,
) -> pd.DataFrame:
    """
    Produce per-setup summary with frequency, win rate, expectancy (R), and move profile.
    Expects detailed dataframe with columns described in README.
    """
    if risk is None:
        risk = RiskModel()

    df = df.copy()
    # Time filter for frequency
    if 'Reversal Time' in df.columns:
        latest = df['Reversal Time'].max()
        if pd.notna(latest):
            cutoff = latest - pd.Timedelta(weeks=lookback_weeks)
        else:
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(weeks=lookback_weeks)
        recent = df[df['Reversal Time'] >= cutoff]
    else:
        recent = df

    # Compute expectancy (R) using close-to-close path
    horizon_max = max(horizons) if horizons else 10

    def path_closes(row) -> list[float]:
        closes = []
        entry = row.get('Entry Price', np.nan)
        for k in range(1, horizon_max + 1):
            col = f'Fwd_{k}_PercMoveFromEntry'
            if col in row and pd.notna(row[col]):
                pct = float(row[col]) / 100.0
                closes.append(entry * (1.0 + pct))
        return closes

    side_sign_series = df.apply(lambda r: _side_sign(side, r.get('Higher TF Trend')), axis=1)
    df['_Expectancy_R'] = df.apply(
        lambda r: _simulate_close_path(
            r.get('Entry Price', np.nan),
            path_closes(r),
            side_sign_series.loc[r.name],
            risk,
        ),
        axis=1,
    )
    df['_Win'] = (df['_Expectancy_R'] > 0).astype(int)

    # Build move profile percentiles for requested horizons
    for h in horizons:
        col = f'Fwd_{h}_PercMoveFromEntry'
        if col not in df.columns:
            df[col] = np.nan

    # Aggregate
    agg = {
        '_Expectancy_R': ['mean', 'count'],
        '_Win': 'mean',
    }
    for h in horizons:
        col = f'Fwd_{h}_PercMoveFromEntry'
        agg[col] = [lambda s: np.nanpercentile(s.dropna(), 50) if len(s.dropna()) else np.nan,
                    lambda s: np.nanpercentile(s.dropna(), 75) if len(s.dropna()) else np.nan,
                    lambda s: np.nanpercentile(s.dropna(), 90) if len(s.dropna()) else np.nan]

    grouped = df.groupby(group_by, dropna=False).agg(agg)

    # Flatten MultiIndex columns
    def _lambda_to_pct(name_or_idx):
        mapping = {0: 'p50', 1: 'p75', 2: 'p90', '<lambda_0>': 'p50', '<lambda_1>': 'p75', '<lambda_2>': 'p90'}
        return mapping.get(name_or_idx, str(name_or_idx))

    grouped.columns = [
        (f"{c[0]}__{_lambda_to_pct(c[1])}" if c[0].startswith('Fwd_') else (c[0] if c[1] == '' else f"{c[0]}__{c[1]}"))
        for c in grouped.columns.to_flat_index()
    ]

    grouped = grouped.rename(columns={
        '_Expectancy_R__mean': 'expectancy_R',
        '_Expectancy_R__count': 'sample_count',
        '_Win__mean': 'win_rate',
    })

    # Frequency per week over recent window
    if not recent.empty:
        recent_counts = recent.groupby(group_by).size().rename('recent_count')
        weeks = max(1.0, lookback_weeks)
        freq = (recent_counts / weeks).rename('frequency_per_week')
        grouped = grouped.join(freq, how='left')
    else:
        grouped['frequency_per_week'] = np.nan

    # Filter by min_samples
    grouped = grouped[grouped['sample_count'] >= int(min_samples)]

    # Order by expectancy
    grouped = grouped.sort_values(by=['expectancy_R', 'win_rate', 'sample_count'], ascending=[False, False, False])

    return grouped.reset_index()


def to_machine_json(df: pd.DataFrame, group_by: list[str], horizons: list[int], risk: RiskModel) -> list[Dict]:
    out: List[Dict] = []
    for _, row in df.iterrows():
        setup = {k: row[k] for k in group_by}
        move_profile = {str(h): {
            'p50': _safe_float(row.get(f'Fwd_{h}_PercMoveFromEntry__p50')),
            'p75': _safe_float(row.get(f'Fwd_{h}_PercMoveFromEntry__p75')),
            'p90': _safe_float(row.get(f'Fwd_{h}_PercMoveFromEntry__p90')),
        } for h in horizons}
        out.append({
            'setup': setup,
            'sample_count': int(row.get('sample_count', 0)) if pd.notna(row.get('sample_count', np.nan)) else 0,
            'frequency_per_week': _safe_float(row.get('frequency_per_week')),
            'win_rate': _safe_float(row.get('win_rate')),
            'expectancy_R': _safe_float(row.get('expectancy_R')),
            'risk_model': {
                'stop_pct': risk.stop_pct,
                'contracts': risk.contracts,
                'scale_out_R': list(risk.scale_out_R),
                'trailing_after_R': risk.trailing_after_R,
                'trailing_gap_R': risk.trailing_gap_R,
            },
            'move_profile': { 'bars': move_profile },
        })
    return out


def _safe_float(val) -> Optional[float]:
    try:
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None
