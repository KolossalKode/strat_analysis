# Quick Start Guide

## 1. Install Dependencies (2 minutes)

```bash
cd /Users/grahamgordon/Desktop/Strat_Analysis/Polygon_Strat_Analysis/strat_analysis
pip install -r requirements.txt
```

## 2. Configure API Key (1 minute)

### Option A: Environment Variable (Recommended for testing)
```bash
export POLYGON_API_KEY='your_polygon_api_key_here'
```

### Option B: Create .env file (Recommended for permanent setup)
```bash
echo "POLYGON_API_KEY=your_polygon_api_key_here" > .env
```

**Get your API key**: https://polygon.io/dashboard/api-keys

**Note**: You need a paid Polygon subscription (Starter $200/mo minimum) for the aggregates API used by this tool.

## 3. Test Installation (1 minute)

```bash
python3 test_scanner.py
```

You should see:
```
✓ All imports successful
✓ Config loaded
✓ API key found
✓ API connection successful
✓ Data fetch successful
✅ All tests passed! Ready to run the scanner.
```

## 4. Launch the App (30 seconds)

```bash
streamlit run strat_app.py
```

Your browser will open to http://localhost:8501

## 5. Run Your First Scan (2 minutes)

### In the Sidebar:

1. **API Key**: Should auto-populate if you set the environment variable. Otherwise, paste it here.

2. **Symbols**: Select a few to start
   - ✅ SPY (S&P 500)
   - ✅ QQQ (Nasdaq)
   - ✅ IWM (Russell 2000)

3. **Timeframes**: Select 3-4
   - ✅ 1hour
   - ✅ 4hour
   - ✅ daily
   - ✅ weekly

4. **Options**:
   - ✅ Use OHLC Precision (recommended)
   - Months of History: 6 (default is fine)
   - Min Higher TF Confluence: 3 (default is fine)

5. Click **🚀 Run Scanner**

### What You'll See:

1. **Progress Bar**: Shows fetching progress (3 symbols × 4 timeframes = 12 fetches)

2. **Log Container**: Real-time updates
   ```
   Fetching SPY 1hour...
   Fetching SPY 4hour...
   ...
   Found 15 reversal setups.
   Analysis complete!
   ```

3. **Results Dashboard**:
   - Total Setups Found: 15
   - Unique Patterns: 4
   - Avg Win Rate: 62.5%
   - Avg Expectancy: 0.45R

4. **Three Tabs**:
   - **Overview**: Summary stats by pattern/timeframe
   - **Detailed Reversals**: Every setup with filters
   - **Downloads**: Export CSV files

## 6. Interpreting Results

### Overview Tab

Look for setups with:
- **Win Rate > 60%**: Good edge
- **Expectancy > 0.4R**: Strong profitability
- **Freq/Week > 1.0**: Tradeable frequency

Example:
```
Timeframe: 4hour
Pattern: 3-1-2u
Count: 8
Win Rate: 65.0%
Expectancy: 0.72R
Freq/Week: 1.2
```

This means: The 3-1-2u pattern on the 4-hour chart has occurred 8 times, won 65% of those trades, and averaged +0.72R profit per trade. It triggers about once per week.

### Detailed Reversals Tab

Every row is a specific trade setup:

| Symbol | Timeframe | Pattern | Entry | Stop | T1 | T2 | Trend | FTFC Count | Bars Ago |
|--------|-----------|---------|-------|------|----|----|-------|------------|----------|
| SPY | 4hour | 3-1-2u | 450.25 | 427.74 | 472.76 | 495.27 | 2u | 4 | 12 |

- **Entry**: Where you'd enter the trade (close of reversal bar)
- **Stop**: Where you'd exit if it fails (-1R)
- **T1**: First target (scale out 1st contract at +1R)
- **T2**: Second target (scale out 2nd contract at +2R)
- **FTFC Count**: How many higher timeframes are aligned
- **Bars Ago**: How recently this triggered

**Use filters** to narrow down:
- Symbol: Focus on one ticker
- Timeframe: Compare patterns across TFs
- Pattern: See all instances of a specific setup

### Downloads Tab

- **Detailed CSV**: Every reversal with all columns (good for Excel analysis)
- **Summary CSV**: Aggregated stats (good for strategy selection)

## Common First-Run Issues

### Issue: "No FTFC reversals found"

**Why**: Your criteria might be too strict, or recent market hasn't had many reversals.

**Fix**:
1. Lower "Min Higher TF Confluence" to 2
2. Increase "Months of History" to 12
3. Add more symbols (try 10-15)

### Issue: Scanner takes >5 minutes

**Why**: Fetching data for many symbols/timeframes without cache.

**Fix**:
1. First run is always slower (building cache)
2. Second run will be <30 seconds (using cache)
3. Or reduce symbols to 5-10 for faster testing

### Issue: All win rates are 50%

**Why**: Not enough historical data, or patterns are weak.

**Fix**:
1. Increase history to 12-24 months
2. Try different symbols (some are more "Strat-friendly" than others)
3. Check "Use OHLC Precision" is ON

## What to Do Next

### Try Different Configurations:

**Conservative (High Win Rate)**:
- Min Confluence: 4
- Result: Fewer setups, but higher quality

**Aggressive (More Opportunities)**:
- Min Confluence: 2
- Result: More setups, but lower average quality

**Intraday Focus**:
- Timeframes: 30min, 1hour, 2hour, 4hour
- Symbols: SPY, QQQ (liquid ETFs)
- Result: More frequent triggers, faster resolution

**Swing Trading Focus**:
- Timeframes: 4hour, daily, weekly
- Symbols: Individual stocks (AAPL, MSFT, TSLA)
- Result: Slower triggers, multi-day holds

### Analyze Your Results:

1. **Best Patterns**: Which reversals have highest expectancy?
2. **Best Timeframes**: Does 4hour outperform daily for your symbols?
3. **FTFC Importance**: Compare setups with 3 vs 4+ aligned TFs
4. **Symbol-Specific**: Does SPY behave differently than QQQ?

### Set Up Alerts (Manual for now):

1. Run scanner daily
2. Filter "Bars Ago" = 0-5 (recent setups)
3. Filter "Expectancy R" > 0.5 (high quality)
4. Review those setups for potential trades

## Pro Tips

1. **Cache is your friend**: After the first scan, subsequent scans are 10x faster. Don't clear cache unless data is stale.

2. **Start small**: Don't scan 50 symbols on your first run. Start with 3-5, verify it works, then expand.

3. **Compare OHLC vs Close-only**: Run once with OHLC precision ON, once with OFF. Compare win rates and expectancies. OHLC is usually more realistic (lower win rates, but more accurate).

4. **Use CSV exports**: Excel/Google Sheets are great for deeper analysis. You can pivot, chart, and slice the data however you want.

5. **Monitor cache stats** (Settings tab): If cache files are >7 days old, refresh them for current data.

## Need Help?

1. **Check test_scanner.py output**: Diagnostics for what's broken
2. **Check COMPLETION_SUMMARY.md**: Detailed technical info
3. **Check logs in the Scanner tab**: Real-time error messages

## Ready? Let's Go!

```bash
streamlit run strat_app.py
```

Happy trading! 📈
