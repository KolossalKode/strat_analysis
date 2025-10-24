"""
Scheduled Scanner: Runs FTFC analysis on schedule and sends alerts to mobile.

Usage:
    python scheduled_scanner.py --timeframes 1hour 4hour daily --notify telegram
    python scheduled_scanner.py --config alert_config.json
"""
import os
import sys
import json
import logging
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import argparse

import pandas as pd

from config import (
    TIMEFRAMES, DEFAULT_SYMBOLS, POLYGON_API_KEY_ENV,
    DEFAULT_STOP_PCT, DEFAULT_CONTRACTS, DEFAULT_SCALE_OUT_R,
    DEFAULT_TRAILING_AFTER_R, DEFAULT_TRAILING_GAP_R
)
from polygon_manager import PolygonDataManager
from setup_analyzer.engine import RiskModel, detect_ftfc_reversals, summarize_setups, build_ohlc_lookup

# Configure logging
log_dir = Path("./logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"scanner_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class MarketHours:
    """Utilities for checking market hours and trading times."""

    @staticmethod
    def is_market_open(now: Optional[datetime] = None) -> bool:
        """Check if US stock market is currently open."""
        if now is None:
            now = datetime.now()

        # Convert to Eastern Time (market timezone)
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('America/New_York')
        now_et = now.astimezone(eastern) if now.tzinfo else now.replace(tzinfo=eastern)

        # Check if weekend
        if now_et.weekday() in (5, 6):  # Saturday, Sunday
            return False

        # Check if within trading hours (9:30 AM - 4:00 PM ET)
        market_open = time(9, 30)
        market_close = time(16, 0)
        current_time = now_et.time()

        # TODO: Add holiday check (NYSE calendar)
        return market_open <= current_time < market_close

    @staticmethod
    def next_candle_close(timeframe: str, now: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate when the current candle closes for a given timeframe."""
        if now is None:
            now = datetime.now()

        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('America/New_York')
        now_et = now.astimezone(eastern) if now.tzinfo else now.replace(tzinfo=eastern)

        tf_config = TIMEFRAMES.get(timeframe)
        if not tf_config:
            return None

        if '1hour' in timeframe:
            # Next hour boundary
            next_close = now_et.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif '4hour' in timeframe:
            # 4H candles close at 12pm and 4pm
            if now_et.hour < 12:
                next_close = now_et.replace(hour=12, minute=0, second=0, microsecond=0)
            else:
                next_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        elif timeframe == 'daily':
            # Daily closes at 4pm
            next_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            if now_et.time() >= time(16, 0):
                next_close += timedelta(days=1)
        elif timeframe == 'weekly':
            # Weekly closes Friday 4pm
            days_until_friday = (4 - now_et.weekday()) % 7
            next_close = (now_et + timedelta(days=days_until_friday)).replace(
                hour=16, minute=0, second=0, microsecond=0
            )
        else:
            return None

        return next_close


class AlertFilter:
    """Filters and ranks setups for mobile alerts."""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize with filtering configuration.

        Config keys:
            min_expectancy: Minimum R-expectancy (default: 0.3)
            min_win_rate: Minimum win rate (default: 0.50)
            min_ftfc_count: Minimum FTFC alignment (default: 3)
            max_bars_ago: Maximum bars since reversal (default: 5)
            max_alerts: Maximum number of alerts to send (default: 10)
        """
        self.config = config or {}
        self.min_expectancy = self.config.get('min_expectancy', 0.3)
        self.min_win_rate = self.config.get('min_win_rate', 0.50)
        self.min_ftfc_count = self.config.get('min_ftfc_count', 3)
        self.max_bars_ago = self.config.get('max_bars_ago', 5)
        self.max_alerts = self.config.get('max_alerts', 10)

    def filter_setups(self, detailed_df: pd.DataFrame, summary_df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter setups based on quality criteria and recency.

        Returns:
            Filtered DataFrame sorted by quality (expectancy descending)
        """
        if detailed_df.empty:
            return detailed_df

        filtered = detailed_df.copy()

        # Filter by FTFC count
        if 'FTFC Count' in filtered.columns:
            filtered = filtered[filtered['FTFC Count'] >= self.min_ftfc_count]

        # Filter by recency (only recent setups)
        if 'Bars Ago' in filtered.columns:
            filtered = filtered[filtered['Bars Ago'] <= self.max_bars_ago]

        # Merge with summary stats to get expectancy and win rate
        if not summary_df.empty and 'Timeframe' in filtered.columns and 'Pattern' in filtered.columns:
            filtered = filtered.merge(
                summary_df[['Timeframe', 'Pattern', 'expectancy_R', 'win_rate']],
                on=['Timeframe', 'Pattern'],
                how='left'
            )

            # Filter by expectancy and win rate
            if 'expectancy_R' in filtered.columns:
                filtered = filtered[filtered['expectancy_R'] >= self.min_expectancy]
            if 'win_rate' in filtered.columns:
                filtered = filtered[filtered['win_rate'] >= self.min_win_rate]

            # Sort by expectancy (best first)
            filtered = filtered.sort_values('expectancy_R', ascending=False)

        # Limit to max_alerts
        filtered = filtered.head(self.max_alerts)

        return filtered


class AlertFormatter:
    """Formats setups for mobile notifications."""

    @staticmethod
    def format_setup_short(row: pd.Series) -> str:
        """
        Format a single setup as a concise text message.

        Example:
            SPY 4H 3-1-2u @ $450.25
            Entry: 450.25 | Stop: 427.74 (-5%)
            T1: 472.76 (+5%) | T2: 495.27 (+10%)
            Exp: 0.65R | Win: 68% | FTFC: 4
        """
        symbol = row.get('Symbol', '???')
        tf = row.get('Timeframe', '???')
        pattern = row.get('Pattern', '???')
        entry = row.get('Entry Price', 0)
        stop = row.get('Stop Price', 0)
        t1 = row.get('T1', 0)
        t2 = row.get('T2', 0)
        expectancy = row.get('expectancy_R', 0)
        win_rate = row.get('win_rate', 0)
        ftfc_count = row.get('FTFC Count', 0)

        # Calculate percentages
        stop_pct = ((stop - entry) / entry * 100) if entry > 0 else 0
        t1_pct = ((t1 - entry) / entry * 100) if entry > 0 else 0
        t2_pct = ((t2 - entry) / entry * 100) if entry > 0 else 0

        lines = [
            f"{symbol} {tf} {pattern} @ ${entry:.2f}",
            f"Entry: {entry:.2f} | Stop: {stop:.2f} ({stop_pct:+.1f}%)",
            f"T1: {t1:.2f} ({t1_pct:+.1f}%) | T2: {t2:.2f} ({t2_pct:+.1f}%)",
            f"Exp: {expectancy:.2f}R | Win: {win_rate*100:.0f}% | FTFC: {ftfc_count}"
        ]

        return "\n".join(lines)

    @staticmethod
    def format_summary(setups: pd.DataFrame, timeframe: str) -> str:
        """
        Format all setups for a timeframe as a single message.

        Example:
            === FTFC Alerts: 4H (3 setups) ===

            1. SPY 4H 3-1-2u @ $450.25
            Entry: 450.25 | Stop: 427.74
            Exp: 0.65R | Win: 68%

            2. QQQ 4H 2d-1-2u @ $380.50
            ...
        """
        if setups.empty:
            return f"No new {timeframe} setups found."

        lines = [f"=== FTFC Alerts: {timeframe} ({len(setups)} setups) ===", ""]

        for idx, (_, row) in enumerate(setups.iterrows(), start=1):
            lines.append(f"{idx}. {AlertFormatter.format_setup_short(row)}")
            lines.append("")

        return "\n".join(lines)


class NotificationService:
    """Sends alerts via various channels."""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize notification service.

        Config keys:
            service: 'telegram', 'twilio', 'email', 'pushover'
            telegram_bot_token: Telegram bot token
            telegram_chat_id: Your Telegram chat ID
            twilio_account_sid: Twilio account SID
            twilio_auth_token: Twilio auth token
            twilio_from_number: Twilio phone number
            twilio_to_number: Your phone number
            email_smtp_server: SMTP server (e.g., smtp.gmail.com)
            email_smtp_port: SMTP port (e.g., 587)
            email_username: Email username
            email_password: Email password or app password
            email_to: Recipient email address
        """
        self.config = config or {}
        self.service = self.config.get('service', 'telegram')

    def send(self, message: str, title: Optional[str] = None) -> bool:
        """
        Send a notification via configured service.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if self.service == 'telegram':
                return self._send_telegram(message)
            elif self.service == 'twilio':
                return self._send_twilio(message)
            elif self.service == 'email':
                return self._send_email(message, title)
            elif self.service == 'pushover':
                return self._send_pushover(message, title)
            else:
                logger.error(f"Unknown notification service: {self.service}")
                return False
        except Exception as e:
            logger.error(f"Failed to send notification via {self.service}: {e}")
            return False

    def _send_telegram(self, message: str) -> bool:
        """Send via Telegram bot."""
        import requests

        bot_token = self.config.get('telegram_bot_token')
        chat_id = self.config.get('telegram_chat_id')

        if not bot_token or not chat_id:
            logger.error("Telegram bot_token or chat_id not configured")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'  # Allows *bold* and _italic_
        }

        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram notification sent successfully")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False

    def _send_twilio(self, message: str) -> bool:
        """Send via Twilio SMS."""
        from twilio.rest import Client

        account_sid = self.config.get('twilio_account_sid')
        auth_token = self.config.get('twilio_auth_token')
        from_number = self.config.get('twilio_from_number')
        to_number = self.config.get('twilio_to_number')

        if not all([account_sid, auth_token, from_number, to_number]):
            logger.error("Twilio credentials not fully configured")
            return False

        client = Client(account_sid, auth_token)
        message_obj = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )

        logger.info(f"Twilio SMS sent: {message_obj.sid}")
        return True

    def _send_email(self, message: str, title: Optional[str] = None) -> bool:
        """Send via email."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_server = self.config.get('email_smtp_server', 'smtp.gmail.com')
        smtp_port = self.config.get('email_smtp_port', 587)
        username = self.config.get('email_username')
        password = self.config.get('email_password')
        to_address = self.config.get('email_to')

        if not all([username, password, to_address]):
            logger.error("Email credentials not fully configured")
            return False

        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = to_address
        msg['Subject'] = title or f"FTFC Alert - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        msg.attach(MIMEText(message, 'plain'))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

        logger.info(f"Email sent to {to_address}")
        return True

    def _send_pushover(self, message: str, title: Optional[str] = None) -> bool:
        """Send via Pushover."""
        import requests

        user_key = self.config.get('pushover_user_key')
        api_token = self.config.get('pushover_api_token')

        if not all([user_key, api_token]):
            logger.error("Pushover credentials not configured")
            return False

        url = "https://api.pushover.net/1/messages.json"
        payload = {
            'token': api_token,
            'user': user_key,
            'message': message,
            'title': title or "FTFC Alert"
        }

        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Pushover notification sent successfully")
            return True
        else:
            logger.error(f"Pushover API error: {response.status_code}")
            return False


def run_scanner(
    symbols: List[str],
    timeframes: List[str],
    alert_filter: AlertFilter,
    notifier: NotificationService,
    use_ohlc_precision: bool = True
) -> Dict:
    """
    Run the FTFC scanner and send alerts.

    Returns:
        Dict with keys: success, setups_found, alerts_sent, error
    """
    result = {
        'success': False,
        'setups_found': 0,
        'alerts_sent': 0,
        'error': None
    }

    try:
        # Initialize data manager
        api_key = os.environ.get(POLYGON_API_KEY_ENV)
        if not api_key:
            raise ValueError(f"{POLYGON_API_KEY_ENV} environment variable not set")

        logger.info(f"Initializing scanner for {len(symbols)} symbols × {len(timeframes)} timeframes")
        manager = PolygonDataManager(api_key)

        # Fetch data
        logger.info("Fetching OHLC data...")
        all_data = manager.batch_fetch(symbols, timeframes, months_back=6)

        if not all_data:
            logger.warning("No data fetched from Polygon")
            result['error'] = "No data fetched"
            return result

        logger.info(f"Fetched {len(all_data)} symbol/timeframe combinations")

        # Detect reversals
        logger.info("Detecting FTFC reversals...")
        detailed_df = detect_ftfc_reversals(
            ohlc_data=all_data,
            min_higher_tfs=alert_filter.min_ftfc_count,
            performance_lookahead_bars=10
        )

        if detailed_df.empty:
            logger.info("No FTFC reversals found")
            result['success'] = True
            return result

        logger.info(f"Found {len(detailed_df)} reversal setups")

        # Run simulations
        logger.info("Running performance simulations...")
        risk_model = RiskModel(
            stop_pct=DEFAULT_STOP_PCT,
            contracts=DEFAULT_CONTRACTS,
            scale_out_R=DEFAULT_SCALE_OUT_R,
            trailing_after_R=DEFAULT_TRAILING_AFTER_R,
            trailing_gap_R=DEFAULT_TRAILING_GAP_R
        )

        ohlc_cache = None
        if use_ohlc_precision:
            logger.info("Building OHLC cache...")
            ohlc_cache = build_ohlc_lookup(detailed_df, manager, 10)

        summary_df = summarize_setups(
            df=detailed_df,
            group_by=['Timeframe', 'Pattern'],
            horizons=[1, 3, 5, 10],
            lookback_weeks=52,
            side='auto',
            min_samples=1,
            risk=risk_model,
            ohlc_cache=ohlc_cache
        )

        # Calculate entry/stop/targets
        detailed_df['Stop Price'] = detailed_df.apply(
            lambda row: row['Entry Price'] * (1 - DEFAULT_STOP_PCT) if row['Higher TF Trend'] == '2u'
            else row['Entry Price'] * (1 + DEFAULT_STOP_PCT),
            axis=1
        )
        detailed_df['T1'] = detailed_df.apply(
            lambda row: row['Entry Price'] * (1 + DEFAULT_STOP_PCT * DEFAULT_SCALE_OUT_R[0]) if row['Higher TF Trend'] == '2u'
            else row['Entry Price'] * (1 - DEFAULT_STOP_PCT * DEFAULT_SCALE_OUT_R[0]),
            axis=1
        )
        detailed_df['T2'] = detailed_df.apply(
            lambda row: row['Entry Price'] * (1 + DEFAULT_STOP_PCT * DEFAULT_SCALE_OUT_R[1]) if row['Higher TF Trend'] == '2u'
            else row['Entry Price'] * (1 - DEFAULT_STOP_PCT * DEFAULT_SCALE_OUT_R[1]),
            axis=1
        )

        # Calculate bars ago
        detailed_df['Bars Ago'] = detailed_df.apply(
            lambda row: len(all_data.get((row['Symbol'], row['Timeframe']), pd.DataFrame())[
                all_data.get((row['Symbol'], row['Timeframe']), pd.DataFrame()).index > row['Reversal Time']
            ]) if (row['Symbol'], row['Timeframe']) in all_data else 0,
            axis=1
        )

        result['setups_found'] = len(detailed_df)

        # Filter for alerts
        logger.info("Filtering setups for alerts...")
        filtered_setups = alert_filter.filter_setups(detailed_df, summary_df)

        if filtered_setups.empty:
            logger.info("No setups passed filtering criteria")
            result['success'] = True
            return result

        logger.info(f"{len(filtered_setups)} setups passed filtering")

        # Group by timeframe and send alerts
        for tf in filtered_setups['Timeframe'].unique():
            tf_setups = filtered_setups[filtered_setups['Timeframe'] == tf]
            message = AlertFormatter.format_summary(tf_setups, tf)

            logger.info(f"Sending alert for {tf} ({len(tf_setups)} setups)")
            if notifier.send(message, title=f"FTFC Alert: {tf}"):
                result['alerts_sent'] += len(tf_setups)

        result['success'] = True
        logger.info(f"Scanner run complete: {result['setups_found']} setups found, {result['alerts_sent']} alerts sent")

    except Exception as e:
        logger.error(f"Scanner error: {e}", exc_info=True)
        result['error'] = str(e)

    return result


def main():
    """Main entry point for scheduled scanner."""
    parser = argparse.ArgumentParser(description="Scheduled FTFC Scanner with Mobile Alerts")
    parser.add_argument('--config', type=str, help="Path to JSON configuration file")
    parser.add_argument('--symbols', nargs='+', help="Symbols to scan (overrides config)")
    parser.add_argument('--timeframes', nargs='+', help="Timeframes to scan (overrides config)")
    parser.add_argument('--notify', type=str, choices=['telegram', 'twilio', 'email', 'pushover'],
                        help="Notification service (overrides config)")
    parser.add_argument('--dry-run', action='store_true', help="Run scanner but don't send notifications")
    parser.add_argument('--check-market', action='store_true', help="Only run if market is open")

    args = parser.parse_args()

    # Load configuration
    config = {}
    if args.config and Path(args.config).exists():
        with open(args.config, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded configuration from {args.config}")

    # Override with CLI arguments
    if args.symbols:
        config['symbols'] = args.symbols
    if args.timeframes:
        config['timeframes'] = args.timeframes
    if args.notify:
        config['notification'] = config.get('notification', {})
        config['notification']['service'] = args.notify

    # Set defaults
    symbols = config.get('symbols', DEFAULT_SYMBOLS[:10])
    timeframes = config.get('timeframes', ['1hour', '4hour', 'daily'])
    alert_config = config.get('alert_filter', {})
    notification_config = config.get('notification', {})

    logger.info(f"Scanner configuration: {len(symbols)} symbols, {len(timeframes)} timeframes")

    # Check market hours if requested
    if args.check_market and not MarketHours.is_market_open():
        logger.info("Market is closed. Skipping scan.")
        return

    # Initialize services
    alert_filter = AlertFilter(alert_config)
    notifier = NotificationService(notification_config)

    if args.dry_run:
        logger.info("DRY RUN MODE: Notifications will not be sent")
        # Replace send method with a no-op
        notifier.send = lambda msg, title=None: (logger.info(f"[DRY RUN] Would send:\n{msg}"), True)[1]

    # Run scanner
    result = run_scanner(
        symbols=symbols,
        timeframes=timeframes,
        alert_filter=alert_filter,
        notifier=notifier,
        use_ohlc_precision=config.get('use_ohlc_precision', True)
    )

    # Log result
    if result['success']:
        logger.info(f"✓ Scanner completed successfully")
        logger.info(f"  Setups found: {result['setups_found']}")
        logger.info(f"  Alerts sent: {result['alerts_sent']}")
    else:
        logger.error(f"✗ Scanner failed: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
