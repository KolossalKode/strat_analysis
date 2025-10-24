# FTFC Trading Scanner with Mobile Alerts

**Automated FTFC (Full Timeframe Continuity) reversal detection using The Strat methodology, powered by Polygon.io real-time data, with mobile alerts sent directly to your phone.**

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen.svg)

---

## 🎯 What This Does

Automatically scans stocks for high-probability FTFC reversal setups and sends **mobile alerts** at optimal times:

- **15 minutes before each hourly candle close** (1H, 4H timeframes)
- **45 minutes before market open** (daily prep)
- **15 minutes before daily close** (end-of-day review)
- **Friday before weekly close** (swing trade planning)

### Example Alert on Your Phone:

```
=== FTFC Alerts: 4hour (2 setups) ===

1. SPY 4hour 3-1-2u @ $450.25
Entry: 450.25 | Stop: 427.74 (-5.0%)
T1: 472.76 (+5.0%) | T2: 495.27 (+10.0%)
Exp: 0.65R | Win: 68% | FTFC: 4

2. QQQ 4hour 2d-1-2u @ $380.50
Entry: 380.50 | Stop: 361.48 (-5.0%)
T1: 399.53 (+5.0%) | T2: 418.55 (+10.0%)
Exp: 0.52R | Win: 61% | FTFC: 3
```

**Clean. Concise. Actionable.** ✨

---

## ✨ Key Features

### 🔍 Pattern Detection
- Detects 6 reversal patterns: 3-1-2u, 3-1-2d, 2u-1-2d, 2d-1-2u, 2u-2d, 2d-2u
- Multi-timeframe confluence validation (FTFC)
- Configurable minimum alignment threshold

### 📊 Performance Analysis
- OHLC-precise trade simulation with 3-contract scaling
- Win rate and R-expectancy calculations
- Historical performance tracking
- Forward move percentiles (p25, p50, p75, p90)

### 📱 Mobile Notifications
- **Telegram** (Free, recommended)
- **Twilio SMS** (Real SMS to any phone)
- **Email** (Gmail, any SMTP)
- **Pushover** (Native push notifications)

### 🤖 Smart Automation
- Market-aware scheduling (only scans during trading hours)
- Intelligent filtering (prevents alert spam)
- Caching for fast repeated scans
- Robust error handling and logging

### 🎨 Interactive UI
- Streamlit web interface for manual scanning
- Filterable results tables
- Summary statistics dashboard
- CSV/Excel export

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [Polygon.io](https://polygon.io) API key (Starter plan $200/mo minimum)
- macOS, Linux, or Windows

### Installation (5 minutes)

```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/strat-analysis.git
cd strat-analysis

# Install dependencies
pip install -r requirements.txt

# Set up configuration
cp alert_config.json.example alert_config.json
# Edit alert_config.json with your credentials

export POLYGON_API_KEY='your_polygon_api_key_here'

# Test the scanner
python3 test_scanner.py
```

### Run Interactive Scanner

```bash
streamlit run strat_app.py
```

Then open http://localhost:8501 in your browser.

### Set Up Mobile Alerts (30 minutes)

See **[MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)** for complete instructions.

**Quick version**:

1. Create Telegram bot via @BotFather
2. Add credentials to `alert_config.json`
3. Test: `python3 scheduled_scanner.py --config alert_config.json --dry-run`
4. Deploy: Set up LaunchAgent (macOS) or cron (Linux)

---

## 📚 Documentation

| Guide | Description | Time |
|-------|-------------|------|
| **[QUICKSTART.md](QUICKSTART.md)** | Basic scanner usage | 5 min |
| **[MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)** | Mobile alerts setup | 30 min |
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | Command cheat sheet | Reference |
| **[AUTOMATION_COMPLETE.md](AUTOMATION_COMPLETE.md)** | Full feature list | Reference |

---

## 🎛️ Configuration

### Alert Quality Filters

Edit `alert_config.json`:

```json
"alert_filter": {
  "min_expectancy": 0.4,   // Minimum R-expectancy (0.3-1.0)
  "min_win_rate": 0.55,    // Minimum win rate (0.50-0.80)
  "min_ftfc_count": 3,     // Min higher TF confluence (2-5)
  "max_bars_ago": 3,       // Max bars since setup (1-10)
  "max_alerts": 10         // Max alerts per scan (1-20)
}
```

**Tune for your needs**:
- **More alerts**: Lower `min_expectancy` and `min_win_rate`
- **Higher quality**: Increase thresholds
- **Less spam**: Lower `max_alerts`

### Symbols and Timeframes

```json
"symbols": ["SPY", "QQQ", "AAPL", "MSFT"],
"timeframes": ["1hour", "4hour", "daily", "weekly"]
```

---

## 📊 Project Structure

```
strat_analysis/
├── strat_app.py                  # Streamlit UI (manual scanning)
├── scheduled_scanner.py          # Automated scanner
├── market_scheduler.py           # Market-aware scheduler
├── config.py                     # Global constants
├── polygon_client.py             # Polygon API wrapper
├── polygon_manager.py            # Data caching & management
├── options_analyzer.py           # Options chain analysis
├── setup_analyzer/
│   └── engine.py                 # FTFC detection & simulation
├── alert_config.json.example     # Config template
├── com.strat.scanner.plist.example  # macOS LaunchAgent template
├── requirements.txt              # Python dependencies
└── data/
    └── polygon_cache/            # Cached OHLC data (auto-created)
```

---

## 🔧 Usage Examples

### Manual Scan (Interactive)

```bash
streamlit run strat_app.py
```

### Automated Scan (CLI)

```bash
# Test without sending notifications
python3 scheduled_scanner.py \
  --config alert_config.json \
  --timeframes daily \
  --dry-run

# Run real scan (sends alerts)
python3 scheduled_scanner.py \
  --config alert_config.json \
  --timeframes 1hour 4hour daily
```

### Continuous Scheduler

```bash
# Run in foreground (see output)
python3 market_scheduler.py --config alert_config.json --daemon

# Run in background (macOS LaunchAgent)
launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
```

### View Logs

```bash
# Real-time scheduler log
tail -f logs/scheduler.log

# Today's scanner results
tail -f logs/scanner_$(date +%Y%m%d).log
```

---

## 🎯 The Strat Methodology

This scanner implements **Rob Smith's Strat** methodology for multi-timeframe analysis:

### Bar Types
- **1 (Inside)**: High ≤ prev high AND low ≥ prev low
- **2u (Directional Up)**: High > prev high AND low ≥ prev low
- **2d (Directional Down)**: High ≤ prev high AND low < prev low
- **3 (Outside)**: High > prev high AND low < prev low

### Reversal Patterns
- **3-1-2u**: Outside → Inside → Directional Up (bullish reversal)
- **3-1-2d**: Outside → Inside → Directional Down (bearish reversal)
- **2d-1-2u**: Down → Inside → Up (bullish reversal)
- **2u-1-2d**: Up → Inside → Down (bearish reversal)
- **2u-2d** / **2d-2u**: Direct directional changes

### FTFC (Full Timeframe Continuity)
A reversal setup where **multiple higher timeframes** align in the same direction as the reversal, providing strong confluence.

Example: A 1H chart shows a 3-1-2u pattern while the 4H, Daily, and Weekly charts all show "2u" (uptrend) = **FTFC with 3 higher TF alignment**.

---

## 🔐 Security Best Practices

- **Never commit** `alert_config.json` or `.plist` files with real credentials
- Use **app-specific passwords** for email (not your main password)
- Store API keys in **environment variables** or `.env` file
- Keep `.env` and `alert_config.json` in `.gitignore`

---

## 🐛 Troubleshooting

### No alerts received

```bash
# Check logs
tail -100 logs/scanner_$(date +%Y%m%d).log
```

Common causes:
- "No FTFC reversals found" → Market quiet, normal behavior
- "No setups passed filtering" → Lower thresholds in `alert_config.json`
- "Market is closed" → Expected outside 9:30am-4pm ET weekdays

### Scheduler not running

```bash
# macOS
launchctl list | grep strat
# Should show: com.strat.scanner (PID)

# If not found, reload:
launchctl unload ~/Library/LaunchAgents/com.strat.scanner.plist
launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
```

### Telegram bot not responding

```bash
# Test bot token
curl https://api.telegram.org/botYOUR_TOKEN/getMe
```

Should return `{"ok":true,...}`

---

## 📈 Performance Expectations

With default config (16 symbols, 4 timeframes):

| Metric | Value |
|--------|-------|
| Scan duration | 10-30 seconds (with cache) |
| Alerts per day | 2-5 (varies by market) |
| Alerts per week | 10-30 |
| High-quality setups | 1-2/week (>0.6R, >65% win) |

**First run**: Slower (builds cache)
**Subsequent runs**: Fast (uses cache)

---

## ⚠️ Disclaimer

**This software is for educational and informational purposes only.**

- Not financial advice
- Past performance does not guarantee future results
- Trading involves substantial risk of loss
- Use at your own risk
- Verify all signals before trading

---

## 🙏 Credits

- **The Strat** methodology by [Rob Smith](https://twitter.com/RobInTheBlack)
- Market data by [Polygon.io](https://polygon.io)
- Built with Python, Streamlit, Pandas, Plotly

---

## 📞 Support

- **Setup help**: See [MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)
- **Command reference**: See [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- **Issues**: Open an issue on GitHub

---

**Ready to never miss a high-quality FTFC setup again?**

Start with [QUICKSTART.md](QUICKSTART.md) or jump straight to [MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)!

Happy trading! 📈🚀
