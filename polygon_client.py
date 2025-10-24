"""
Low-level Polygon.io API wrapper for stocks and options data.
"""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd
from polygon import RESTClient
from requests.exceptions import HTTPError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

class PolygonClient:
    """
    A low-level client for interacting with the Polygon.io REST API.

    Handles rate limiting, request retries, and data conversion.
    """

    def __init__(self, api_key: str):
        """
        Initializes the Polygon REST client.

        Args:
            api_key: Your Polygon.io API key.
        """
        if not api_key:
            raise ValueError("Polygon API key cannot be empty.")
        self.client = RESTClient(api_key)
        self._last_request_time = 0
        self._rate_limit_delay = 0.01  # 100 requests/sec for paid plans

    def _respect_rate_limit(self):
        """
        Ensures requests do not exceed the API rate limit.
        """
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.monotonic()

    def _validate_date_format(self, date_str: str) -> bool:
        """
        Ensures dates are in YYYY-MM-DD format.

        Args:
            date_str: The date string to validate.

        Returns:
            True if the format is valid, False otherwise.
        """
        try:
            pd.to_datetime(date_str, format='%Y-%m-%d')
            return True
        except ValueError:
            logging.error(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
            return False

    def _handle_api_error(self, error: Exception, context: str):
        """
        Unified error handling and logging for API calls.

        Args:
            error: The exception that was caught.
            context: A string describing the context of the API call.
        """
        if isinstance(error, HTTPError) and error.response.status_code == 429:
            logging.warning(f"Rate limit exceeded for {context}. Retrying after delay...")
        else:
            logging.error(f"API error during {context}: {error}")

    def get_bars(
        self,
        symbol: str,
        timespan: str,
        multiplier: int,
        from_date: str,
        to_date: str,
        limit: int = 50000,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV bars from Polygon, handling pagination and retries.

        Args:
            symbol: The stock ticker symbol.
            timespan: The size of the time window (e.g., 'minute', 'hour').
            multiplier: The number of timespans in the window (e.g., 1).
            from_date: The start date in YYYY-MM-DD format.
            to_date: The end date in YYYY-MM-DD format.
            limit: The maximum number of bars to fetch per request.

        Returns:
            A DataFrame with OHLCV data, or None if an error occurs.
        """
        if not self._validate_date_format(from_date) or not self._validate_date_format(to_date):
            return None

        context = f"get_bars for {symbol} ({timespan})"
        for attempt in range(3):
            try:
                self._respect_rate_limit()
                aggs = self.client.get_aggs(
                    ticker=symbol,
                    multiplier=multiplier,
                    timespan=timespan,
                    from_=from_date,
                    to=to_date,
                    limit=limit,
                )
                if not aggs:
                    logging.warning(f"No data returned for {symbol} from {from_date} to {to_date}.")
                    return None

                df = pd.DataFrame(aggs)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df = df.set_index('timestamp').tz_localize('UTC').tz_convert('America/New_York')
                df = df.rename(columns={'transactions': 'ticks'})
                logging.info(f"Successfully fetched {len(df)} bars for {symbol}.")
                return df

            except Exception as e:
                self._handle_api_error(e, context)
                time.sleep(2 ** attempt)  # Exponential backoff
        return None

    def get_last_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get the most recent bid/ask quote for a symbol.

        Args:
            symbol: The stock ticker symbol.

        Returns:
            A dictionary with quote data, or None on failure.
        """
        context = f"get_last_quote for {symbol}"
        try:
            self._respect_rate_limit()
            quote = self.client.get_last_quote(symbol)
            if quote:
                return {
                    'bid': quote.bid_price,
                    'ask': quote.ask_price,
                    'bid_size': quote.bid_size,
                    'ask_size': quote.ask_size,
                    'timestamp': pd.to_datetime(quote.participant_timestamp, unit='ns').tz_localize('UTC').tz_convert('America/New_York'),
                }
            return None
        except Exception as e:
            self._handle_api_error(e, context)
            return None

    def get_snapshot(self, symbol: str) -> Optional[Dict]:
        """
        Get a real-time snapshot of a symbol (last trade + quote).

        Args:
            symbol: The stock ticker symbol.

        Returns:
            A dictionary with snapshot data, or None on failure.
        """
        context = f"get_snapshot for {symbol}"
        try:
            self._respect_rate_limit()
            snapshot = self.client.get_snapshot(symbol)
            if snapshot and snapshot.ticker:
                return {
                    'price': snapshot.ticker.last_trade.price,
                    'volume': snapshot.ticker.day.volume,
                    'open': snapshot.ticker.day.open,
                    'high': snapshot.ticker.day.high,
                    'low': snapshot.ticker.day.low,
                    'close': snapshot.ticker.day.close,
                    'prev_close': snapshot.ticker.prev_day.close,
                    'change_pct': snapshot.ticker.todays_change_perc,
                }
            return None
        except Exception as e:
            self._handle_api_error(e, context)
            return None

    def get_options_contracts(
        self,
        underlying: str,
        contract_type: Optional[str] = None,
        expiration: Optional[str] = None,
        strike: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict]:
        """
        List available option contracts.

        Args:
            underlying: The underlying stock ticker.
            contract_type: 'call', 'put', or None for both.
            expiration: 'YYYY-MM-DD' or None for all.
            strike: Specific strike or None for all.
            limit: Max number of contracts to return.

        Returns:
            A list of dictionaries, each representing an option contract.
        """
        context = f"get_options_contracts for {underlying}"
        try:
            self._respect_rate_limit()
            contracts = self.client.list_options_contracts(
                underlying_ticker=underlying,
                contract_type=contract_type,
                expiration_date=expiration,
                strike_price=strike,
                limit=limit,
            )
            return [
                {
                    'ticker': c.ticker,
                    'underlying': c.underlying_ticker,
                    'type': c.contract_type,
                    'strike': c.strike_price,
                    'expiration': c.expiration_date,
                    'shares_per_contract': c.shares_per_contract,
                }
                for c in contracts
            ]
        except Exception as e:
            self._handle_api_error(e, context)
            return []

    def get_options_chain(
        self,
        underlying: str,
        expiration: Optional[str] = None,
        min_strike: Optional[float] = None,
        max_strike: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Get a full options chain with quotes and greeks.

        Args:
            underlying: The underlying stock ticker.
            expiration: The expiration date in 'YYYY-MM-DD'.
            min_strike: The minimum strike price to include.
            max_strike: The maximum strike price to include.

        Returns:
            A DataFrame containing the options chain, or an empty DataFrame on failure.
        """
        context = f"get_options_chain for {underlying} expiring {expiration}"
        try:
            self._respect_rate_limit()
            chain = self.client.get_chain(
                ticker=underlying,
                expiration_date=expiration,
                strike_price_gte=min_strike,
                strike_price_lte=max_strike,
            )
            
            if not chain:
                logging.warning(f"No options chain data for {underlying} on {expiration}.")
                return pd.DataFrame()

            records = []
            for contract in chain:
                greeks = contract.greeks
                records.append({
                    'ticker': contract.ticker,
                    'type': contract.contract_type,
                    'strike': contract.strike_price,
                    'expiration': contract.expiration_date,
                    'bid': contract.quote.bid,
                    'ask': contract.quote.ask,
                    'last': contract.last_trade.price if contract.last_trade else None,
                    'volume': contract.day.volume,
                    'open_interest': contract.open_interest,
                    'iv': contract.implied_volatility,
                    'delta': greeks.delta if greeks else None,
                    'gamma': greeks.gamma if greeks else None,
                    'theta': greeks.theta if greeks else None,
                    'vega': greeks.vega if greeks else None,
                    'underlying_price': contract.underlying_asset.price,
                })
            return pd.DataFrame(records)

        except Exception as e:
            self._handle_api_error(e, context)
            return pd.DataFrame()

    def get_nearest_expiration(
        self, underlying: str, min_dte: int = 7, max_dte: int = 45
    ) -> Optional[str]:
        """
        Find the nearest option expiration date within a DTE range.

        Args:
            underlying: The underlying stock ticker.
            min_dte: Minimum days to expiration.
            max_dte: Maximum days to expiration.

        Returns:
            The nearest expiration date as a 'YYYY-MM-DD' string, or None.
        """
        context = f"get_nearest_expiration for {underlying}"
        try:
            self._respect_rate_limit()
            expirations = self.client.list_options_contracts(
                underlying_ticker=underlying,
                limit=1000, # Fetch a good number of contracts to find expirations
                expired=False
            )
            
            today = pd.Timestamp.now(tz='America/New_York').normalize()
            valid_expirations = []
            seen_dates = set()

            for contract in expirations:
                if contract.expiration_date in seen_dates:
                    continue
                seen_dates.add(contract.expiration_date)
                
                exp_date = pd.to_datetime(contract.expiration_date).tz_localize('America/New_York')
                dte = (exp_date - today).days
                if min_dte <= dte <= max_dte:
                    valid_expirations.append((dte, contract.expiration_date))
            
            if not valid_expirations:
                return None
            
            # Return the expiration with the smallest DTE
            return min(valid_expirations, key=lambda x: x[0])[1]

        except Exception as e:
            self._handle_api_error(e, context)
            return None

    def get_atm_strike(
        self, underlying: str, current_price: Optional[float] = None
    ) -> Optional[float]:
        """
        Find the at-the-money strike (closest to the current price).

        Args:
            underlying: The underlying stock ticker.
            current_price: The current price of the underlying. Fetched if not provided.

        Returns:
            The ATM strike price, or None on failure.
        """
        if current_price is None:
            snapshot = self.get_snapshot(underlying)
            if not snapshot:
                return None
            current_price = snapshot['price']

        context = f"get_atm_strike for {underlying}"
        try:
            # Fetch a few contracts to find available strikes
            self._respect_rate_limit()
            contracts = self.client.list_options_contracts(
                underlying_ticker=underlying,
                limit=100, # A handful of contracts should reveal strike increments
                expired=False
            )
            if not contracts:
                return None
            
            strikes = sorted(list(set(c.strike_price for c in contracts)))
            
            # Find the strike closest to the current price
            atm_strike = min(strikes, key=lambda s: abs(s - current_price))
            return atm_strike

        except Exception as e:
            self._handle_api_error(e, context)
            return None
