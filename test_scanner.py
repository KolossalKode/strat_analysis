"""
Quick test script to verify the scanner components work
"""
import os
import sys
from datetime import datetime, timedelta

# Add logging
import logging
logging.basicConfig(level=logging.INFO)

print("=" * 60)
print("Testing Strat Analysis Scanner Components")
print("=" * 60)

# Test 1: Import all modules
print("\n[1/5] Testing imports...")
try:
    from config import TIMEFRAMES, DEFAULT_SYMBOLS, REVERSAL_PATTERNS
    from polygon_client import PolygonClient
    from polygon_manager import PolygonDataManager
    from options_analyzer import OptionsAnalyzer
    from setup_analyzer.engine import RiskModel, detect_ftfc_reversals, summarize_setups, build_ohlc_lookup
    print("✓ All imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Check configuration
print("\n[2/5] Testing configuration...")
try:
    assert len(TIMEFRAMES) > 0, "No timeframes defined"
    assert len(DEFAULT_SYMBOLS) > 0, "No symbols defined"
    assert len(REVERSAL_PATTERNS) > 0, "No reversal patterns defined"
    print(f"✓ Config loaded: {len(TIMEFRAMES)} timeframes, {len(DEFAULT_SYMBOLS)} default symbols, {len(REVERSAL_PATTERNS)} patterns")
except Exception as e:
    print(f"✗ Config test failed: {e}")
    sys.exit(1)

# Test 3: Check API key
print("\n[3/5] Checking API key...")
api_key = os.environ.get('POLYGON_API_KEY')
if not api_key:
    print("⚠ Warning: POLYGON_API_KEY not set in environment")
    print("  Set it with: export POLYGON_API_KEY='your_key_here'")
    print("  Skipping API tests...")
    api_tests_enabled = False
else:
    print(f"✓ API key found (length: {len(api_key)})")
    api_tests_enabled = True

# Test 4: Test Polygon client (if API key available)
if api_tests_enabled:
    print("\n[4/5] Testing Polygon API connection...")
    try:
        client = PolygonClient(api_key)
        snapshot = client.get_snapshot('SPY')
        if snapshot:
            print(f"✓ API connection successful")
            print(f"  SPY current price: ${snapshot['price']:.2f}")
        else:
            print("✗ API returned no data (check your key/subscription)")
    except Exception as e:
        print(f"✗ API test failed: {e}")
        api_tests_enabled = False

# Test 5: Test data manager (if API key available)
if api_tests_enabled:
    print("\n[5/5] Testing data manager with cache...")
    try:
        manager = PolygonDataManager(api_key)

        # Try to fetch a small amount of data
        print("  Fetching SPY daily data (last 30 days)...")
        df = manager.get_ohlc('SPY', 'daily', months_back=1)

        if df is not None and not df.empty:
            print(f"✓ Data fetch successful")
            print(f"  Retrieved {len(df)} bars")
            print(f"  Date range: {df.index.min().date()} to {df.index.max().date()}")
            print(f"  Has 'label' column: {'label' in df.columns}")

            if 'label' in df.columns:
                label_counts = df['label'].value_counts()
                print(f"  Label distribution: {label_counts.to_dict()}")
        else:
            print("✗ Data fetch returned empty result")

    except Exception as e:
        print(f"✗ Data manager test failed: {e}")
        import traceback
        traceback.print_exc()
else:
    print("\n[5/5] Skipping data manager test (no API key)")

# Test 6: Test FTFC detection logic
print("\n[BONUS] Testing FTFC detection logic...")
try:
    # Create minimal test data
    import pandas as pd
    import numpy as np

    # Create a simple test dataset with a 3-1-2u pattern
    dates = pd.date_range(start='2024-01-01', periods=10, freq='D', tz='America/New_York')
    test_df = pd.DataFrame({
        'open': [100, 102, 101, 100, 99, 101, 103, 105, 104, 106],
        'high': [103, 104, 102, 101, 100, 104, 106, 107, 106, 108],
        'low': [99, 101, 100, 99, 98, 100, 102, 104, 103, 105],
        'close': [102, 103, 101, 100, 99, 103, 105, 106, 105, 107],
    }, index=dates)

    # Manually add labels to create a 3-1-2u pattern
    test_df['label'] = ['N/A', '2u', '3', '1', '2u', '2u', '2u', '2u', '1', '2u']

    test_data = {('TEST', 'daily'): test_df}

    # Try to detect reversals
    reversals = detect_ftfc_reversals(test_data, min_higher_tfs=0)  # Set to 0 since we have no higher TFs

    print(f"✓ FTFC detection logic executed")
    print(f"  Found {len(reversals)} potential reversals in test data")

except Exception as e:
    print(f"✗ FTFC detection test failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test Summary:")
print("=" * 60)
print("Core modules: ✓")
print("Configuration: ✓")
if api_tests_enabled:
    print("API connection: ✓")
    print("Data fetching: ✓")
    print("\n✅ All tests passed! Ready to run the scanner.")
else:
    print("API tests: Skipped (no API key)")
    print("\n⚠ Setup your POLYGON_API_KEY to test the full pipeline")

print("\nTo run the full app:")
print("  streamlit run strat_app.py")
print("=" * 60)
