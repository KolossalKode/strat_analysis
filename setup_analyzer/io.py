import io
import os
import zipfile
from typing import Optional, Sequence

import pandas as pd


def _read_detailed_excel_from_zip(zip_path: str) -> Optional[pd.DataFrame]:
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Find the detailed Excel entry; support any date prefix
        names = [n for n in zf.namelist() if n.endswith("FTFC_Performance_Detailed.xlsx")]
        if not names:
            return None
        with zf.open(names[0], 'r') as fh:
            data = fh.read()
            bio = io.BytesIO(data)
            return pd.read_excel(bio)


def load_detailed(path: str) -> pd.DataFrame:
    """
    Load the detailed output dataframe.

    Accepts:
    - A ZIP produced by strat_app (containing *FTFC_Performance_Detailed.xlsx)
    - A direct Excel (.xlsx) or CSV file with the detailed dataframe
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Path not found: {path}")

    lower = path.lower()
    if lower.endswith('.zip'):
        df = _read_detailed_excel_from_zip(path)
        if df is None:
            raise ValueError("Could not find *FTFC_Performance_Detailed.xlsx in ZIP")
        return df
    elif lower.endswith('.xlsx'):
        return pd.read_excel(path)
    elif lower.endswith('.csv'):
        return pd.read_csv(path)
    else:
        raise ValueError("Unsupported input format. Use .zip, .xlsx, or .csv")


def coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Normalize expected columns if present
    if 'Reversal Time' in df.columns:
        df['Reversal Time'] = pd.to_datetime(df['Reversal Time'], errors='coerce', utc=True).dt.tz_convert(None)
    if 'Entry Price' in df.columns:
        df['Entry Price'] = pd.to_numeric(df['Entry Price'], errors='coerce')
    return df


def detect_horizons(df: pd.DataFrame, fallback: Sequence[int] = (1, 3, 5, 10)) -> list[int]:
    cols = [c for c in df.columns if c.startswith('Fwd_') and c.endswith('_PercMoveFromEntry')]
    vals: list[int] = []
    for c in cols:
        mid = c.split('_')[1]
        try:
            vals.append(int(mid))
        except Exception:
            continue
    if not vals:
        return list(fallback)
    return sorted(set(vals))

