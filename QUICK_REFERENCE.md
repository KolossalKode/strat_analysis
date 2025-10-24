# Quick Reference Card

## 🚀 Common Commands

### Run Interactive Scanner (Streamlit UI)
```bash
export POLYGON_API_KEY='your_key'
streamlit run strat_app.py
```

### Run Scheduled Scanner (One-time test)
```bash
# Dry run (no notifications sent)
python3 scheduled_scanner.py --config alert_config.json --timeframes daily --dry-run

# Real run (sends notifications)
python3 scheduled_scanner.py --config alert_config.json --timeframes daily 4hour
```

### Run Market Scheduler (Continuous)
```bash
# Foreground (see output)
python3 market_scheduler.py --config alert_config.json --daemon

# Background (via LaunchAgent on macOS)
launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
launchctl start com.strat.scanner
```

### Check Status
```bash
# Scheduler status
launchctl list | grep strat

# View logs
tail -f logs/scheduler.log
tail -f logs/scanner_$(date +%Y%m%d).log

# Test installation
python3 test_scanner.py
```

### Stop/Restart Scheduler
```bash
# Stop
launchctl stop com.strat.scanner

# Restart (after config changes)
launchctl unload ~/Library/LaunchAgents/com.strat.scanner.plist
launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
```

---

## ⚙️ Configuration Files

| File | Purpose |
|------|---------|
| `alert_config.json` | Scanner settings, notification credentials, filter thresholds |
| `com.strat.scanner.plist` | macOS LaunchAgent config (auto-start on boot) |
| `.env` | Environment variables (POLYGON_API_KEY) |
| `config.py` | Global constants (timeframes, symbols, patterns) |

---

## 📊 Alert Filter Tuning

Edit `alert_config.json`:

```json
"alert_filter": {
  "min_expectancy": 0.4,    // Higher = fewer, better alerts
  "min_win_rate": 0.55,     // Higher = fewer, better alerts
  "min_ftfc_count": 3,      // Higher = fewer, stronger confluence
  "max_bars_ago": 3,        // Lower = only very recent setups
  "max_alerts": 10          // Lower = less spam
}
```

**Too many alerts?**
- Increase `min_expectancy` to 0.5-0.6
- Increase `min_win_rate` to 0.60-0.65
- Increase `min_ftfc_count` to 4

**Too few alerts?**
- Decrease `min_expectancy` to 0.3
- Decrease `min_win_rate` to 0.50
- Decrease `min_ftfc_count` to 2
- Increase `max_bars_ago` to 5

---

## 📱 Notification Setup (Telegram)

1. Create bot: Talk to @BotFather in Telegram
2. Get chat ID: https://api.telegram.org/botYOUR_TOKEN/getUpdates
3. Edit `alert_config.json`:
   ```json
   "notification": {
     "service": "telegram",
     "telegram_bot_token": "123456:ABC...",
     "telegram_chat_id": "987654321"
   }
   ```
4. Test: `python3 scheduled_scanner.py --config alert_config.json --dry-run`

Full guide: [MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)

---

## 🕒 Scan Schedule

Default timing (all times in ET):

| Time | Trigger | Timeframes |
|------|---------|------------|
| 8:45am | Pre-market | Daily, Weekly |
| 9:45am | 1H close | 1hour |
| 10:45am | 1H close | 1hour |
| 11:45am | 1H + 4H close | 1hour, 4hour |
| 12:45pm | 1H close | 1hour |
| 1:45pm | 1H close | 1hour |
| 2:45pm | 1H close | 1hour |
| 3:45pm | 1H + 4H + Daily close | 1hour, 4hour, daily (+ weekly on Friday) |

**Customize** in `market_scheduler.py` (line ~75)

---

## 🐛 Troubleshooting

### No alerts received
```bash
# Check logs
tail -100 logs/scanner_$(date +%Y%m%d).log

# Look for:
# - "No FTFC reversals found" → Lower thresholds
# - "No setups passed filtering" → Adjust alert_filter
# - "Market is closed" → Expected outside market hours
```

### Scheduler not running
```bash
# macOS
launchctl list | grep strat
# Should show: com.strat.scanner (PID)

# If not found:
launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
```

### Scanner errors
```bash
# View errors
cat logs/scheduler_stderr.log

# Common fixes:
pip install -r requirements.txt  # Missing dependencies
export POLYGON_API_KEY='...'      # Missing API key
```

---

## 📁 Project Structure

```
strat_analysis/
├── strat_app.py                 # Streamlit UI (manual scanning)
├── scheduled_scanner.py         # Automated scanner (run on schedule)
├── market_scheduler.py          # Scheduler daemon (triggers scanner)
├── alert_config.json            # Config: symbols, filters, notifications
├── com.strat.scanner.plist      # macOS LaunchAgent config
├── config.py                    # Global constants
├── polygon_client.py            # Polygon API wrapper
├── polygon_manager.py           # Data management with caching
├── options_analyzer.py          # Options chain analysis
├── setup_analyzer/
│   └── engine.py                # FTFC detection & simulation
├── logs/
│   ├── scheduler.log            # Scheduler activity
│   ├── scanner_YYYYMMDD.log     # Scanner results
│   └── scheduler_stderr.log     # Errors
└── data/
    └── polygon_cache/           # Cached OHLC data (Parquet files)
```

---

## 🎯 Typical Workflow

### Morning (8:45am alert)
1. Check Telegram for pre-market alert
2. Review daily/weekly setups
3. Add to watchlist
4. Plan entries for the day

### Mid-day (11:45am, 3:45pm alerts)
1. Check 4H setup alerts
2. Look for entries aligning with daily trend
3. Set alerts in broker platform

### End of day (3:45pm alert)
1. Review daily close setups
2. Plan overnight/next-day trades
3. Check performance of earlier setups

### Weekly (Friday 3:45pm)
1. Review weekly alert for swing trades
2. Plan multi-day positions
3. Check higher TF trends

---

## 💡 Pro Tips

1. **Start conservative**: Use high filter thresholds (min_expectancy=0.5) for first week
2. **Track results**: Save alerts, check actual outcomes, tune thresholds
3. **Check logs daily**: `tail logs/scanner_$(date +%Y%m%d).log`
4. **Cache management**: Clear old cache monthly via Settings tab in Streamlit UI
5. **Multiple configs**: Create `conservative_config.json` and `aggressive_config.json` for different strategies

---

## 📞 Support

- **Setup issues**: See [MOBILE_ALERTS_SETUP.md](MOBILE_ALERTS_SETUP.md)
- **Scanner bugs**: Check [COMPLETION_SUMMARY.md](COMPLETION_SUMMARY.md)
- **Quick start**: See [QUICKSTART.md](QUICKSTART.md)

---

## 🔑 Environment Variables

Set once (add to `~/.zshrc` or `~/.bashrc` for persistence):

```bash
export POLYGON_API_KEY='your_polygon_api_key_here'
```

Or use `.env` file:
```bash
echo "POLYGON_API_KEY=your_key" > .env
```

---

## 📈 Expected Results

With default config (min_expectancy=0.4, min_win_rate=0.55):

- **Alerts per day**: 2-5 (varies by market volatility)
- **Alerts per week**: 10-30
- **False positives**: ~35-40% (by design - 55% win rate)
- **High-quality setups** (>0.6R, >65% win): 1-2 per week

**Adjust filters** based on your preferences and actual results.

---

This is your cheat sheet. Keep it handy! 🚀
