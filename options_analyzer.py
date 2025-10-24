"""
Options chain analysis and strategy recommendations.
"""
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    OPTIONS_MAX_DTE,
    OPTIONS_MIN_DTE,
    OPTIONS_MIN_OPEN_INTEREST,
    OPTIONS_MIN_VOLUME,
)
from polygon_client import PolygonClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

class OptionsAnalyzer:
    """
    Analyzes options chains to recommend strategies for Strat setups.
    """

    def __init__(self, polygon_client: PolygonClient):
        """
        Initializes the OptionsAnalyzer.

        Args:
            polygon_client: An instance of the PolygonClient.
        """
        self.client = polygon_client

    def _filter_liquid_contracts(self, chain: pd.DataFrame) -> pd.DataFrame:
        """
        Filters an options chain for liquid contracts.
        """
        return chain[
            (chain['volume'] >= OPTIONS_MIN_VOLUME) &
            (chain['open_interest'] >= OPTIONS_MIN_OPEN_INTEREST)
        ]

    def _calculate_breakeven(self, strike: float, premium: float, contract_type: str) -> float:
        """
        Calculates the breakeven price for a single option contract.
        """
        if contract_type == 'call':
            return strike + premium
        elif contract_type == 'put':
            return strike - premium
        return 0.0

    def analyze_setup_for_options(
        self, 
        symbol: str, 
        entry_price: float, 
        stop_price: float, 
        target_r1: float, 
        target_r2: float, 
        expectancy_r: float, 
        win_rate: float, 
        side: str = 'long'
    ) -> Dict:
        """
        Performs a comprehensive options analysis for a given Strat setup.
        """
        result = {
            'symbol': symbol,
            'strategy': 'skip',
            'reasoning': '',
            'expiration': None,
            'dte': None,
            'current_price': None,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'target_r1': target_r1,
            'target_r2': target_r2,
            'recommended_contracts': [],
            'spreads': [],
            'iv_rank': None, # Placeholder
            'error': None,
        }

        try:
            # 1. Get current price and nearest expiration
            snapshot = self.client.get_snapshot(symbol)
            if not snapshot:
                result['error'] = "Failed to get current price for symbol."
                return result
            result['current_price'] = snapshot['price']

            expiration = self.client.get_nearest_expiration(symbol, OPTIONS_MIN_DTE, OPTIONS_MAX_DTE)
            if not expiration:
                result['error'] = f"No suitable expiration found within {OPTIONS_MIN_DTE}-{OPTIONS_MAX_DTE} DTE."
                return result
            
            today = pd.Timestamp.now(tz='America/New_York').normalize()
            exp_date = pd.to_datetime(expiration).tz_localize('America/New_York')
            result['dte'] = (exp_date - today).days
            result['expiration'] = expiration

            # 2. Get and filter options chain
            chain = self.client.get_options_chain(symbol, expiration)
            if chain.empty:
                result['error'] = "Failed to fetch options chain."
                return result
            
            liquid_chain = self._filter_liquid_contracts(chain)
            if liquid_chain.empty:
                result['error'] = "No liquid options contracts found."
                return result

            # 3. Determine strategy
            contract_type = 'call' if side == 'long' else 'put'
            if expectancy_r > 0.6 and win_rate > 0.65:
                result['strategy'] = f"long_{contract_type}"
                result['reasoning'] = f"High conviction setup (Exp: {expectancy_r:.2f}R, Win: {win_rate:.1%}). Recommending naked long {contract_type}."
            elif expectancy_r >= 0.3:
                result['strategy'] = f"bull_{contract_type}_spread" if side == 'long' else f"bear_{contract_type}_spread"
                result['reasoning'] = f"Moderate conviction setup (Exp: {expectancy_r:.2f}R). Recommending a vertical spread to define risk."
            else:
                result['reasoning'] = f"Edge too thin (Exp: {expectancy_r:.2f}R). No options strategy recommended."
                return result

            # 4. Find optimal contracts/spreads
            side_chain = liquid_chain[liquid_chain['type'] == contract_type].copy()
            if side_chain.empty:
                result['error'] = f"No liquid {contract_type} contracts found."
                return result

            # Find ATM contract
            atm_strike_idx = (side_chain['strike'] - result['current_price']).abs().idxmin()
            atm_contract = side_chain.loc[atm_strike_idx]

            if 'long' in result['strategy']:
                atm_contract_dict = atm_contract.to_dict()
                atm_contract_dict['breakeven'] = self._calculate_breakeven(atm_contract['strike'], atm_contract['ask'], contract_type)
                result['recommended_contracts'].append(atm_contract_dict)
            
            elif 'spread' in result['strategy']:
                # Simple spread: buy ATM, sell OTM
                long_leg = atm_contract
                
                if side == 'long': # Bull Call Spread
                    otm_strikes = side_chain[side_chain['strike'] > long_leg['strike']]
                    if otm_strikes.empty:
                        result['error'] = "Could not find OTM strike for spread."
                        return result
                    short_leg = otm_strikes.iloc[0]
                else: # Bear Put Spread
                    otm_strikes = side_chain[side_chain['strike'] < long_leg['strike']]
                    if otm_strikes.empty:
                        result['error'] = "Could not find OTM strike for spread."
                        return result
                    short_leg = otm_strikes.iloc[-1]

                net_debit = long_leg['ask'] - short_leg['bid']
                max_profit = abs(long_leg['strike'] - short_leg['strike']) - net_debit
                max_loss = net_debit

                spread_info = {
                    'long_leg': long_leg.to_dict(),
                    'short_leg': short_leg.to_dict(),
                    'net_debit': net_debit * 100,
                    'max_profit': max_profit * 100,
                    'max_loss': max_loss * 100,
                    'breakeven': self._calculate_breakeven(long_leg['strike'], net_debit, contract_type),
                    'roi_pct': (max_profit / max_loss) * 100 if max_loss > 0 else float('inf'),
                }
                result['spreads'].append(spread_info)

        except Exception as e:
            logging.error(f"Error during options analysis for {symbol}: {e}")
            result['error'] = str(e)

        return result

    def format_recommendation_for_display(self, recommendation: Dict) -> str:
        """
        Converts a recommendation dictionary to a formatted markdown string.
        """
        if recommendation['error']:
            return f"### ⚠️ Analysis Error\n**Symbol:** {recommendation['symbol']}\n**Error:** {recommendation['error']}"

        if recommendation['strategy'] == 'skip':
            return f"### 🟡 Strategy: Skip\n**Symbol:** {recommendation['symbol']}\n**Reasoning:** {recommendation['reasoning']}"

        rec = recommendation
        strat_name = rec['strategy'].replace('_', ' ').title()
        md = f"### ✅ Recommended: {strat_name}\n"
        md += f"**Symbol:** {rec['symbol']} | **Expiration:** {rec['expiration']} ({rec['dte']} DTE)\n"
        md += f"**Reasoning:** {rec['reasoning']}\n\n---\n\n"

        if 'long' in rec['strategy'] and rec['recommended_contracts']:
            contract = rec['recommended_contracts'][0]
            md += f"#### 🎯 **Contract Details**\n"
            md += f"- **Strike:** ${contract['strike']:.2f} ({contract['type'].upper()})\n"
            md += f"- **Premium (Ask):** ${contract['ask']:.2f}\n"
            md += f"- **Breakeven:** ${contract['breakeven']:.2f}\n"
            md += f"- **Liquidity:** Vol: {contract['volume']} | OI: {contract['open_interest']}\n"
            md += f"- **Greeks:** Delta: {contract['delta']:.2f} | Theta: {contract['theta']:.3f}\n"

        if 'spread' in rec['strategy'] and rec['spreads']:
            spread = rec['spreads'][0]
            md += f"#### 💰 **Spread Details**\n"
            md += f"- **Long Leg:** {spread['long_leg']['strike']:.2f}C @ ${spread['long_leg']['ask']:.2f}\n"
            md += f"- **Short Leg:** {spread['short_leg']['strike']:.2f}C @ ${spread['short_leg']['bid']:.2f}\n"
            md += f"- **Net Debit:** ${spread['net_debit']:.2f}\n"
            md += f"- **Max Profit:** ${spread['max_profit']:.2f} ({spread['roi_pct']:.1f}% ROI)\n"
            md += f"- **Max Loss:** ${spread['max_loss']:.2f}\n"
            md += f"- **Breakeven:** ${spread['breakeven']:.2f}\n"

        return md

    # Placeholder for future implementation
    def calculate_iv_rank(self, symbol: str, current_iv: float, lookback_days: int = 252) -> Optional[float]:
        logging.warning("IV Rank calculation is not yet implemented.")
        return None

    def get_optimal_strikes(self, chain: pd.DataFrame, entry_price: float, target_r1: float, target_r2: float, contract_type: str) -> Dict[str, float]:
        side_chain = chain[chain['type'] == contract_type]
        if side_chain.empty:
            return {}
        
        strikes = side_chain['strike']
        return {
            'entry': strikes.iloc[(strikes - entry_price).abs().argsort()[:1]].iloc[0],
            'target_r1': strikes.iloc[(strikes - target_r1).abs().argsort()[:1]].iloc[0],
            'target_r2': strikes.iloc[(strikes - target_r2).abs().argsort()[:1]].iloc[0],
        }

    def calculate_vertical_spread_payoff(self, long_strike: float, short_strike: float, long_premium: float, short_premium: float, at_prices: List[float]) -> pd.DataFrame:
        net_premium = long_premium - short_premium
        payoffs = []
        for price in at_prices:
            # Payoff from long option
            long_payoff = max(0, price - long_strike) - long_premium
            # Payoff from short option
            short_payoff = -(max(0, price - short_strike) - short_premium)
            total_payoff = long_payoff + short_payoff
            payoffs.append({
                'stock_price': price,
                'payoff': total_payoff,
                'profit': total_payoff * 100, # Per 100 shares
                'return_pct': (total_payoff / net_premium) * 100 if net_premium > 0 else 0
            })
        return pd.DataFrame(payoffs)
