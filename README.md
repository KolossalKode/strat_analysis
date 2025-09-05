**Strat Analysis**

This repository contains a Streamlit app for FTFC reversal analysis (`strat_app.py`) and a companion analyzer that turns the app’s detailed output into actionable trade setup insights with ranking and machine‑readable JSON.

What’s included
- Streamlit app: Runs The Strat FTFC scan across multiple timeframes using Alpha Vantage data and exports results.
- Setup analyzer (CLI): Consumes the app’s detailed output (ZIP/Excel) and produces:
  - When/where to buy: entry timeframe and setup/pattern
  - Frequency: triggers per week over a recent window (default 52 weeks)
  - Risk & execution: 5% initial stop, 3 contracts, scale at +1R and +2R, trailing stop (1R below max close after +2R)
  - Historical move profile: p50/p75/p90 by forward bars
  - Deliverables: a ranked list and a JSON output per setup for automation

Prerequisites
- Python 3.10+
- An Alpha Vantage API key to run the Streamlit scanner (free)

Install dependencies
- Create/activate your virtualenv (optional) then install:

  - `pip install -r requirements.txt`

Running the Streamlit FTFC app
- Start the app:

  - `streamlit run strat_app.py`

- Steps in UI:
  - Enter your Alpha Vantage API key in the sidebar
  - Select symbols and run the analysis
  - Use the “Download Results (.zip)” button to save the output bundle locally

Analyzer: Inputs and assumptions
- Primary input: the ZIP produced by the Streamlit app, which contains an Excel file named like `YYYY-MM-DD_FTFC_Performance_Detailed.xlsx`.
- Alternate input: a direct path to an Excel/CSV containing the detailed dataframe with columns:
  - `Symbol`, `Reversal Time`, `Reversal Timeframe`, `FTFC Trigger Label`, `Strat Pattern`, `Higher TF Trend`, `Entry Price`, and `Fwd_{k}_PercMoveFromEntry` for k=1..N (N typically 10)
- Direction: defaults to long-only. You can switch to `--side auto` to map Higher TF Trend: `2u`→long, `2d`→short.
- Execution model (close-to-close approximation):
  - Entry at the bar after the trigger (approximated by the trigger’s entry price and forward closes)
  - Initial stop: 5% from entry (defines 1R)
  - Position: 3 contracts
  - Scale out: 1 at +1R, 1 at +2R
  - Trailing stop: starts after +2R; trail at 1R below the max close since entry
  - Note: Without intrabar OHLC, fills assume closes only; this provides a conservative, reproducible approximation. If you have OHLC data, see `--prices-dir` notes below.

Analyzer: CLI usage
- Run via module to analyze a ZIP from the app and emit insights:

  - `python -m setup_analyzer --zip path/to/Strat_Analysis_Results.zip --top-n 10 --lookback-weeks 52 --min-samples 20 --emit-json insights.json`

- Or analyze a direct detailed Excel/CSV file:

  - `python -m setup_analyzer --detailed path/to/FTFC_Performance_Detailed.xlsx --top-n 10 --emit-json insights.json`

- Optional arguments:
  - `--side {long,short,auto}`: default `long`
  - `--group-by`: comma-separated columns to define a setup (default: `Reversal Timeframe,Strat Pattern`)
  - `--horizons`: comma-separated integers of forward bars (default: `1,3,5,10`)
  - `--prices-dir`: directory with per-symbol/timeframe OHLC CSVs named `{SYMBOL}_{TF}.csv` with columns `timestamp,open,high,low,close,volume` if you want to enable OHLC-aware simulation (optional)

Outputs
- Ranked list (top N) printed to stdout with key metrics: count, frequency/wk, win rate, expectancy (R), p50/p75/p90 for configured horizons.
- Machine‑readable JSON: one object per setup containing:
  - `setup`: `{timeframe, pattern, (optional) trend/label if included in grouping}`
  - `sample_count`, `frequency_per_week`, `win_rate`, `expectancy_R`
  - `risk_model`: details of stop, scale, trailing used
  - `move_profile`: `{bars: {1:{p50,p75,p90}, 3:{...}, ...}}`

Example JSON snippet
```
[
  {
    "setup": {"Reversal Timeframe": "60min", "Strat Pattern": "3-1-2u"},
    "sample_count": 128,
    "frequency_per_week": 2.46,
    "win_rate": 0.62,
    "expectancy_R": 0.41,
    "risk_model": {
      "stop_pct": 0.05,
      "contracts": 3,
      "scale_out_R": [1, 2],
      "trailing_after_R": 2,
      "trailing_gap_R": 1
    },
    "move_profile": {
      "bars": {
        "1": {"p50": 0.4, "p75": 0.9, "p90": 1.6},
        "3": {"p50": 0.8, "p75": 1.6, "p90": 2.7},
        "5": {"p50": 1.1, "p75": 2.1, "p90": 3.2},
        "10": {"p50": 1.6, "p75": 2.9, "p90": 4.6}
      }
    }
  }
]
```

Notes and next steps
- The analyzer defaults to close-to-close simulation to stay independent of external data. If you can provide OHLC bars per symbol/timeframe, the module can be extended to intrabar-aware fills via `--prices-dir`.
- If you want the analyzer to write CSV summaries alongside JSON or integrate directly with `strat_app.py` UI, let me know and I can wire it up.
