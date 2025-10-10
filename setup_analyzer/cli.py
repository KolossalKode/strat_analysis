import argparse
import json
from typing import List

import pandas as pd

from .io import load_detailed, coerce_dtypes, detect_horizons, load_ohlc_prices
from .engine import RiskModel, summarize_setups, to_machine_json


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze Strat FTFC detailed output and produce ranked setups + JSON")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--zip', type=str, help='Path to ZIP produced by strat_app (contains *FTFC_Performance_Detailed.xlsx)')
    src.add_argument('--detailed', type=str, help='Path to detailed Excel/CSV file')

    parser.add_argument('--group-by', type=str, default='Reversal Timeframe,Strat Pattern',
                        help='Comma-separated columns defining a setup')
    parser.add_argument('--horizons', type=str, default='1,3,5,10', help='Comma-separated forward bar horizons')
    parser.add_argument('--lookback-weeks', type=int, default=52, help='Weeks for frequency calculation')
    parser.add_argument('--min-samples', type=int, default=10, help='Minimum samples per setup to include')
    parser.add_argument('--top-n', type=int, default=10, help='Top N setups to print')
    parser.add_argument('--side', type=str, default='long', choices=['long', 'short', 'auto'], help='Trade direction policy')
    parser.add_argument('--emit-json', type=str, default=None, help='Path to write machine-readable JSON insights')
    parser.add_argument('--prices-dir', type=str,
                        help='Dir with OHLC CSVs ({SYMBOL}_{TF}.csv) for intrabar simulation')

    args = parser.parse_args(argv)

    # Load detailed dataframe
    path = args.zip or args.detailed
    df = load_detailed(path)
    df = coerce_dtypes(df)

    # Determine horizons
    if args.horizons.strip():
        horizons = sorted({int(h.strip()) for h in args.horizons.split(',') if h.strip()})
    else:
        horizons = detect_horizons(df)
    if not horizons:
        horizons = detect_horizons(df)

    group_by = [c.strip() for c in args.group_by.split(',') if c.strip()]

    # Load prices if provided
    prices = None
    if args.prices_dir:
        try:
            prices = load_ohlc_prices(args.prices_dir)
            if prices:
                print(f"Loaded {len(prices)} OHLC files from {args.prices_dir}")
        except FileNotFoundError:
            print(f"Warning: --prices-dir not found: {args.prices_dir}")
        except Exception as e:
            print(f"Warning: failed to load OHLC data: {e}")

    risk = RiskModel()
    summary = summarize_setups(
        df,
        group_by=group_by,
        horizons=horizons,
        lookback_weeks=args.lookback_weeks,
        side=args.side,
        min_samples=args.min_samples,
        risk=risk,
        prices=prices,
    )

    # Print ranked list
    top = summary.head(args.top_n)
    if top.empty:
        print("No setups meet the minimum sample criteria.")
    else:
        cols = group_by + ['sample_count', 'frequency_per_week', 'win_rate', 'expectancy_R']
        print("\nTop setups (ranked by expectancy_R):\n")
        print(top[cols].to_string(index=False, justify='left', float_format=lambda x: f"{x:.4f}"))

    # Emit JSON if requested
    if args.emit_json:
        payload = to_machine_json(summary, group_by=group_by, horizons=horizons, risk=risk)
        with open(args.emit_json, 'w') as f:
            json.dump(payload, f, indent=2)
        print(f"\nWrote JSON insights to {args.emit_json}")


if __name__ == '__main__':
    main()

