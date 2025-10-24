# Mobile Alerts Setup Guide

Complete guide to setting up automated FTFC scanner with mobile notifications.

## 📱 What You'll Get

Automated scans that run **on schedule** and send alerts to your phone:

- **1-Hour Candles**: Alert 15 min before each hour (during market hours)
- **4-Hour Candles**: Alert at 11:45am and 3:45pm ET
- **Daily**: Alert at 3:45pm ET (before market close)
- **Pre-Market**: Alert at 8:45am ET (daily prep)
- **Weekly**: Alert Friday 3:45pm ET (weekend prep)

---

## 🚀 Quick Setup (30 minutes)

### Step 1: Choose Notification Method

**Recommendation: Telegram** (Free, easy, reliable)

| Method | Cost | Pros | Cons |
|--------|------|------|------|
| **Telegram** | Free | Easy setup, instant, unlimited | Requires Telegram app |
| Twilio SMS | $0.0075/SMS | Real SMS to any phone | Costs money, needs account |
| Email | Free | Works anywhere | Slower, might miss in spam |
| Pushover | $5 one-time | Native push notifications | One-time fee |

**I'll walk through Telegram setup** (recommended). Other methods are documented below.

---

### Step 2: Set Up Telegram Bot (10 minutes)

#### 2a. Create Telegram Bot

1. Open Telegram app on your phone
2. Search for `@BotFather` (official Telegram bot)
3. Send `/newbot` command
4. Give your bot a name (e.g., "My FTFC Scanner")
5. Give your bot a username (e.g., "my_ftfc_bot")
6. **BotFather will reply with your bot token** - copy this!
   ```
   Use this token to access HTTP API:
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

#### 2b. Get Your Chat ID

1. Search for your new bot in Telegram (by the username you created)
2. Send it a message (anything, like "hello")
3. Open this URL in your browser (replace `YOUR_BOT_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
   Example:
   ```
   https://api.telegram.org/bot123456789:ABCdefGHI/getUpdates
   ```

4. You'll see JSON response. Find your `chat_id`:
   ```json
   {
     "ok": true,
     "result": [{
       "message": {
         "chat": {
           "id": 987654321,  <-- This is your chat ID
           ...
         }
       }
     }]
   }
   ```

5. Copy this number (e.g., `987654321`)

---

### Step 3: Configure Alert Settings (5 minutes)

Edit `alert_config.json`:

```json
{
  "symbols": [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN"
  ],
  "timeframes": ["1hour", "4hour", "daily", "weekly"],
  "use_ohlc_precision": true,

  "alert_filter": {
    "min_expectancy": 0.4,
    "min_win_rate": 0.55,
    "min_ftfc_count": 3,
    "max_bars_ago": 3,
    "max_alerts": 10
  },

  "notification": {
    "service": "telegram",
    "telegram_bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "telegram_chat_id": "987654321"
  }
}
```

**Important**: Replace `telegram_bot_token` and `telegram_chat_id` with YOUR values from Step 2.

**Alert Filter Explained**:
- `min_expectancy`: 0.4 = Only send setups with >= 0.4R average profit
- `min_win_rate`: 0.55 = Only send setups that win >= 55% of the time
- `min_ftfc_count`: 3 = Only send if >= 3 higher timeframes align
- `max_bars_ago`: 3 = Only send recent setups (within last 3 bars)
- `max_alerts`: 10 = Max 10 setups per notification (prevents spam)

Adjust these to control **alert volume**:
- **Too many alerts?** Increase `min_expectancy` to 0.5+, increase `min_win_rate` to 0.60+
- **Too few alerts?** Decrease `min_expectancy` to 0.3, decrease `min_ftfc_count` to 2

---

### Step 4: Install Python Dependencies (2 minutes)

```bash
cd /Users/grahamgordon/Desktop/Strat_Analysis/Polygon_Strat_Analysis/strat_analysis

# Install all requirements (if not done already)
pip install -r requirements.txt

# Install additional dependencies for scheduling
pip install requests python-dotenv
```

For Twilio SMS (optional):
```bash
pip install twilio
```

---

### Step 5: Test the Scanner (5 minutes)

#### Test 1: Manual Scan (no notifications)

```bash
export POLYGON_API_KEY='your_polygon_api_key'

python3 scheduled_scanner.py \
  --config alert_config.json \
  --timeframes daily \
  --dry-run
```

You should see:
```
INFO - Initializing scanner for 8 symbols × 1 timeframes
INFO - Fetching OHLC data...
INFO - Found 5 reversal setups
INFO - 2 setups passed filtering
INFO - [DRY RUN] Would send:
=== FTFC Alerts: daily (2 setups) ===

1. SPY daily 3-1-2u @ $450.25
...
INFO - ✓ Scanner completed successfully
```

#### Test 2: Send Real Notification

Remove `--dry-run` to actually send to your phone:

```bash
python3 scheduled_scanner.py \
  --config alert_config.json \
  --timeframes daily
```

**Check your Telegram** - you should receive a message from your bot!

---

### Step 6: Set Up Automated Scheduling (10 minutes)

#### Option A: macOS LaunchAgent (Recommended for Mac)

1. **Edit the LaunchAgent file**:

   Open `com.strat.scanner.plist` and update:
   - Line 10: Verify Python path matches your system (`which python3`)
   - Line 11: Verify full path to `market_scheduler.py`
   - Line 14: Verify full path to `alert_config.json`
   - Line 21: Add your Polygon API key

2. **Install the LaunchAgent**:

   ```bash
   # Copy plist to LaunchAgents directory
   cp com.strat.scanner.plist ~/Library/LaunchAgents/

   # Load and start the agent
   launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
   launchctl start com.strat.scanner
   ```

3. **Verify it's running**:

   ```bash
   # Check status
   launchctl list | grep strat

   # Check logs
   tail -f logs/scheduler.log
   tail -f logs/scheduler_stdout.log
   ```

4. **Stop/Restart** (if needed):

   ```bash
   # Stop
   launchctl stop com.strat.scanner
   launchctl unload ~/Library/LaunchAgents/com.strat.scanner.plist

   # Restart (after config changes)
   launchctl unload ~/Library/LaunchAgents/com.strat.scanner.plist
   launchctl load ~/Library/LaunchAgents/com.strat.scanner.plist
   ```

#### Option B: Linux cron (For Linux servers)

1. **Create a cron wrapper script**:

   ```bash
   nano ~/run_scanner.sh
   ```

   Add:
   ```bash
   #!/bin/bash
   export POLYGON_API_KEY='your_api_key_here'
   cd /path/to/strat_analysis
   /usr/bin/python3 market_scheduler.py --config alert_config.json --daemon
   ```

   Make executable:
   ```bash
   chmod +x ~/run_scanner.sh
   ```

2. **Add to crontab**:

   ```bash
   crontab -e
   ```

   Add line:
   ```
   @reboot /home/youruser/run_scanner.sh >> /home/youruser/strat_analysis/logs/cron.log 2>&1
   ```

   This starts the scheduler on boot.

#### Option C: Run Manually (Testing)

Just keep it running in a terminal:

```bash
export POLYGON_API_KEY='your_key'
python3 market_scheduler.py --config alert_config.json --daemon
```

Press Ctrl+C to stop.

---

## 📊 Customization Guide

### Adjust Scan Timing

Edit `market_scheduler.py` if you want different timing:

**Current Schedule** (lines 50-120):
- Pre-market: 8:45am ET
- Hourly: :45 past each hour (9:45, 10:45, 11:45, etc.)
- 4H closes: 11:45am, 3:45pm
- Daily close: 3:45pm
- Weekly: Friday 3:45pm

**Example: Change to 10 minutes before close**:

Find line ~75:
```python
scan_time = make_datetime(scan_date, dt_time(hour, 45)) - timedelta(hours=1)
```

Change to:
```python
scan_time = make_datetime(scan_date, dt_time(hour, 50)) - timedelta(hours=1)
```

### Filter by Specific Symbols

Edit `alert_config.json`:

```json
"symbols": ["SPY", "QQQ", "AAPL"]  // Only these 3
```

### Change Notification Frequency

To avoid spam, adjust `max_alerts`:

```json
"alert_filter": {
  "max_alerts": 3  // Only top 3 setups per scan
}
```

### Multiple Notification Methods

You can send to multiple channels by running multiple scanner instances with different configs:

```bash
# Telegram config
python3 scheduled_scanner.py --config telegram_config.json --timeframes daily

# Email config
python3 scheduled_scanner.py --config email_config.json --timeframes weekly
```

---

## 📧 Alternative Notification Methods

### Twilio SMS Setup

1. Sign up at https://www.twilio.com/try-twilio
2. Get phone number (~$1/mo + $0.0075/SMS)
3. Find Account SID and Auth Token in dashboard
4. Edit `alert_config.json`:

```json
"notification": {
  "service": "twilio",
  "twilio_account_sid": "ACxxxxxxxxxxxx",
  "twilio_auth_token": "your_auth_token",
  "twilio_from_number": "+15551234567",
  "twilio_to_number": "+15559876543"
}
```

**Pro**: Real SMS, works on any phone
**Con**: Costs money, 160-character limit (setups truncated)

---

### Email Setup (Gmail)

1. Enable 2FA on your Gmail account
2. Create App Password: https://myaccount.google.com/apppasswords
3. Edit `alert_config.json`:

```json
"notification": {
  "service": "email",
  "email_smtp_server": "smtp.gmail.com",
  "email_smtp_port": 587,
  "email_username": "yourname@gmail.com",
  "email_password": "your_app_password_here",
  "email_to": "yourname@gmail.com"
}
```

**Pro**: Free, no extra apps
**Con**: Slower, might land in spam, less mobile-friendly

---

### Pushover Setup

1. Buy Pushover app ($5 one-time): https://pushover.net/
2. Create account, get User Key
3. Create Application, get API Token
4. Edit `alert_config.json`:

```json
"notification": {
  "service": "pushover",
  "pushover_user_key": "uxxxxxxxxxxxxxx",
  "pushover_api_token": "axxxxxxxxxxxxxx"
}
```

**Pro**: Native iOS/Android push, very clean
**Con**: $5 cost, another app to install

---

## 🔧 Troubleshooting

### "Scanner not running on schedule"

**Check**:
```bash
# macOS
launchctl list | grep strat
tail -f logs/scheduler.log

# Linux
ps aux | grep scheduler
```

**Fix**:
- Verify LaunchAgent is loaded
- Check file paths in .plist are absolute and correct
- Check POLYGON_API_KEY is set in .plist

---

### "No alerts sent"

**Check**:
```bash
tail -f logs/scanner_*.log
```

Look for:
- "No FTFC reversals found" → Lower filter thresholds
- "No setups passed filtering" → Lower `min_expectancy` / `min_win_rate`
- "Market is closed" → Expected outside 9:30am-4pm ET weekdays

**Fix**:
- Adjust `alert_filter` in config (see Step 3)
- Verify market is open (if using `--check-market` flag)
- Run manual test: `python3 scheduled_scanner.py --config alert_config.json --dry-run`

---

### "Telegram bot not responding"

**Check**:
```bash
# Test API directly
curl https://api.telegram.org/botYOUR_BOT_TOKEN/getMe
```

**Fix**:
- Verify `telegram_bot_token` is correct in config
- Verify `telegram_chat_id` is correct
- Make sure you sent a message to the bot first (Step 2b)

---

### "Too many alerts!"

**Reduce volume**:

Edit `alert_config.json`:
```json
"alert_filter": {
  "min_expectancy": 0.6,  // Higher = fewer alerts
  "min_win_rate": 0.65,   // Higher = fewer alerts
  "max_alerts": 3         // Lower = fewer per scan
}
```

Or scan less frequently by removing timeframes:
```json
"timeframes": ["daily", "weekly"]  // Skip 1hour, 4hour
```

---

### "Scanner crashes/errors"

**Check logs**:
```bash
tail -100 logs/scanner_$(date +%Y%m%d).log
tail -100 logs/scheduler_stderr.log
```

**Common errors**:
- `No module named 'requests'` → Run `pip install requests`
- `API key invalid` → Check POLYGON_API_KEY in .plist or environment
- `No data returned` → Verify API subscription (need Starter plan minimum)

---

## 📱 Example Notification

Here's what you'll receive on your phone:

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

Clean, concise, actionable. 🎯

---

## 🎯 Recommended Workflow

### Daily Routine:

1. **8:45am** - Pre-market alert
   - Review daily/weekly setups
   - Plan potential trades

2. **11:45am** - 4H candle alert
   - Mid-day check for new setups

3. **3:45pm** - Daily close alert
   - Review end-of-day setups
   - Plan overnight/next day trades

### Weekly Routine:

1. **Friday 3:45pm** - Weekly alert
   - Review swing trade setups
   - Plan for next week

---

## 🔐 Security Notes

- **Never commit** `alert_config.json` with real credentials to GitHub
- **Protect your** `.plist` file (contains API key)
- **Use app passwords** for email (not your main password)
- **Keep bot tokens secret** - anyone with the token can control your bot

Add to `.gitignore`:
```
alert_config.json
com.strat.scanner.plist
logs/
*.log
```

---

## ✅ Final Checklist

Before going live:

- [ ] Telegram bot created and tested
- [ ] `alert_config.json` configured with correct credentials
- [ ] Test scan runs successfully with `--dry-run`
- [ ] Real notification received on phone
- [ ] LaunchAgent/cron installed and running
- [ ] Logs directory created: `mkdir -p logs`
- [ ] Checked logs: `tail -f logs/scheduler.log`
- [ ] Alert filters tuned to prevent spam
- [ ] Verified market hours logic works

---

## 🚀 You're Done!

Your scanner is now running 24/7, sending you high-quality FTFC setups right to your phone.

**Next**: Let it run for a few days, then tune the `alert_filter` settings based on the quality of alerts you receive.

**Pro tip**: Save good setups from alerts, track their performance, refine your `min_expectancy` threshold based on real results.

Happy trading! 📈
