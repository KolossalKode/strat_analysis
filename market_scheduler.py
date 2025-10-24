"""
Market-Aware Scheduler: Runs scanner at strategic times relative to candle closes.

This script runs continuously and triggers the scanner at the right times:
- 15 minutes before each 1H candle close (hourly during market hours)
- 15 minutes before each 4H candle close (12:45pm, 3:45pm ET)
- 15 minutes before daily close (3:45pm ET)
- 45 minutes before market open (8:45am ET) for daily analysis
- Friday 3:45pm ET for weekly analysis

Usage:
    python market_scheduler.py --config alert_config.json --daemon
"""
import os
import sys
import time
import logging
import argparse
import subprocess
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import List, Tuple, Optional
from zoneinfo import ZoneInfo

# Configure logging
log_dir = Path("./logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "scheduler.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

EASTERN = ZoneInfo('America/New_York')


class ScanSchedule:
    """Calculates next scan times based on market hours and candle closes."""

    @staticmethod
    def get_market_hours() -> Tuple[dt_time, dt_time]:
        """Returns (market_open, market_close) as time objects."""
        return dt_time(9, 30), dt_time(16, 0)

    @staticmethod
    def is_trading_day(dt: datetime) -> bool:
        """Check if given datetime is a trading day (weekday, not holiday)."""
        # Weekend check
        if dt.weekday() in (5, 6):
            return False

        # TODO: Add NYSE holiday calendar check
        # For now, just check weekends

        return True

    @staticmethod
    def next_scan_times(now: Optional[datetime] = None) -> List[Tuple[datetime, str, List[str]]]:
        """
        Calculate all upcoming scan times for today and tomorrow.

        Returns:
            List of (datetime, description, timeframes) tuples, sorted chronologically
        """
        if now is None:
            now = datetime.now(EASTERN)

        scans = []

        # Helper to create datetime from time
        def make_datetime(base_date: datetime, target_time: dt_time) -> datetime:
            return base_date.replace(
                hour=target_time.hour,
                minute=target_time.minute,
                second=0,
                microsecond=0
            )

        # Process today and tomorrow
        for day_offset in [0, 1]:
            scan_date = now + timedelta(days=day_offset)

            if not ScanSchedule.is_trading_day(scan_date):
                continue

            # Pre-market scan (45 min before open) - daily analysis
            pre_market_time = make_datetime(scan_date, dt_time(8, 45))
            if pre_market_time > now:
                scans.append((
                    pre_market_time,
                    "Pre-Market Scan",
                    ['daily', 'weekly']
                ))

            # Hourly scans (15 min before each hour during market hours)
            # Market hours: 9:30am - 4:00pm, so candles close at 10:00, 11:00, 12:00, 1:00, 2:00, 3:00, 4:00
            for hour in [10, 11, 12, 13, 14, 15, 16]:
                scan_time = make_datetime(scan_date, dt_time(hour - 1, 45)) if hour > 9 else make_datetime(scan_date, dt_time(hour, 45))
                # Adjust: scan at :45 of the hour before candle close
                scan_time = make_datetime(scan_date, dt_time(hour, 45)) - timedelta(hours=1)

                if scan_time > now and dt_time(9, 30) <= scan_time.time() <= dt_time(16, 0):
                    scans.append((
                        scan_time,
                        f"1H Candle Close ({hour}:00)",
                        ['1hour']
                    ))

            # 4H candle closes: 12:00pm and 4:00pm (scan at 11:45am and 3:45pm)
            for close_hour, scan_hour, scan_min in [(12, 11, 45), (16, 15, 45)]:
                scan_time = make_datetime(scan_date, dt_time(scan_hour, scan_min))
                if scan_time > now:
                    tfs = ['4hour', 'daily'] if close_hour == 16 else ['4hour']
                    # Add weekly on Friday close
                    if close_hour == 16 and scan_date.weekday() == 4:  # Friday
                        tfs.append('weekly')

                    scans.append((
                        scan_time,
                        f"4H/Daily Candle Close ({close_hour}:00)",
                        tfs
                    ))

        # Sort by time
        scans.sort(key=lambda x: x[0])

        return scans


class Scheduler:
    """Runs the scanner on schedule."""

    def __init__(self, config_path: str, check_interval: int = 60):
        """
        Initialize scheduler.

        Args:
            config_path: Path to alert_config.json
            check_interval: How often to check for scheduled scans (seconds)
        """
        self.config_path = Path(config_path)
        self.check_interval = check_interval
        self.last_scan_times = {}  # Track (description, timeframes) -> last_run_time

    def should_run_scan(self, scan_time: datetime, description: str, timeframes: List[str]) -> bool:
        """
        Check if we should run this scan.

        Prevents duplicate runs for the same scan window.
        """
        now = datetime.now(EASTERN)

        # Check if scan time has passed but is within the check interval window
        time_since_scan = (now - scan_time).total_seconds()
        if not (0 <= time_since_scan <= self.check_interval * 2):
            return False

        # Check if we've already run this scan recently
        scan_key = (description, tuple(sorted(timeframes)))
        last_run = self.last_scan_times.get(scan_key)

        if last_run:
            # Don't re-run if we've run this exact scan in the last hour
            if (now - last_run).total_seconds() < 3600:
                return False

        return True

    def run_scan(self, timeframes: List[str], description: str) -> bool:
        """
        Execute the scanner script.

        Returns:
            True if scan completed successfully, False otherwise
        """
        try:
            logger.info(f"Triggering scan: {description} | Timeframes: {timeframes}")

            # Build command
            cmd = [
                sys.executable,  # Use same Python interpreter
                'scheduled_scanner.py',
                '--config', str(self.config_path),
                '--timeframes', *timeframes,
                '--check-market'  # Only run if market is appropriate for these TFs
            ]

            # Run scanner
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                logger.info(f"✓ Scan completed successfully: {description}")
                logger.debug(f"Scanner output:\n{result.stdout}")
                return True
            else:
                logger.error(f"✗ Scan failed: {description}")
                logger.error(f"Error output:\n{result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"✗ Scan timed out: {description}")
            return False
        except Exception as e:
            logger.error(f"✗ Error running scan: {e}", exc_info=True)
            return False

    def run_forever(self):
        """
        Main scheduler loop - runs continuously.

        Checks every `check_interval` seconds for scans that need to run.
        """
        logger.info("Scheduler started")
        logger.info(f"Config: {self.config_path}")
        logger.info(f"Check interval: {self.check_interval}s")

        while True:
            try:
                now = datetime.now(EASTERN)
                logger.info(f"Checking for scheduled scans... ({now.strftime('%Y-%m-%d %H:%M:%S %Z')})")

                # Get upcoming scans
                upcoming_scans = ScanSchedule.next_scan_times(now)

                if not upcoming_scans:
                    logger.info("No scans scheduled (market closed?)")
                else:
                    # Log next few scans
                    logger.info(f"Next 5 scans:")
                    for scan_time, desc, tfs in upcoming_scans[:5]:
                        time_until = (scan_time - now).total_seconds() / 60
                        logger.info(f"  - {scan_time.strftime('%H:%M')} ({time_until:.0f} min): {desc} | TFs: {tfs}")

                    # Check if any scan should run now
                    for scan_time, description, timeframes in upcoming_scans:
                        if self.should_run_scan(scan_time, description, timeframes):
                            success = self.run_scan(timeframes, description)

                            # Record this scan
                            scan_key = (description, tuple(sorted(timeframes)))
                            self.last_scan_times[scan_key] = now

                            # Brief pause between scans if multiple trigger at once
                            time.sleep(5)

                # Sleep until next check
                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                logger.info("Scheduler stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                time.sleep(self.check_interval)

    def run_once(self, dry_run: bool = False):
        """
        Run immediate scan (for testing).

        Args:
            dry_run: If True, only show what would be scanned
        """
        now = datetime.now(EASTERN)
        logger.info(f"Running immediate scan at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        scans = ScanSchedule.next_scan_times(now)

        if not scans:
            logger.info("No scans scheduled (market closed?)")
            return

        # Run the nearest upcoming scan immediately
        scan_time, description, timeframes = scans[0]

        if dry_run:
            logger.info(f"[DRY RUN] Would run: {description} | Timeframes: {timeframes}")
        else:
            self.run_scan(timeframes, description)


def main():
    """Main entry point for the scheduler."""
    parser = argparse.ArgumentParser(description="Market-Aware Scan Scheduler")
    parser.add_argument('--config', type=str, required=True, help="Path to alert_config.json")
    parser.add_argument('--daemon', action='store_true', help="Run as background daemon (continuous)")
    parser.add_argument('--once', action='store_true', help="Run immediate scan once and exit")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be scanned without running")
    parser.add_argument('--check-interval', type=int, default=60, help="Check interval in seconds (default: 60)")

    args = parser.parse_args()

    # Validate config file exists
    if not Path(args.config).exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Initialize scheduler
    scheduler = Scheduler(args.config, check_interval=args.check_interval)

    if args.once:
        scheduler.run_once(dry_run=args.dry_run)
    else:
        if not args.daemon:
            logger.warning("No --daemon or --once flag specified. Running in continuous mode.")
            logger.warning("Press Ctrl+C to stop.")
            time.sleep(2)

        scheduler.run_forever()


if __name__ == "__main__":
    main()
