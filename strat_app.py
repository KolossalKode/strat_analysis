"""
Main Streamlit application for the Strat Decision Engine.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import logging

# Project imports
from config import *
from polygon_client import PolygonClient
from polygon_manager import PolygonDataManager
from options_analyzer import OptionsAnalyzer
from setup_analyzer.engine import RiskModel, summarize_setups, build_ohlc_lookup, detect_ftfc_reversals

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Strat Decision Engine", page_icon="📈")

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Session State Initialization ---
def init_session_state():
    defaults = {
        'analysis_complete': False,
        'detailed_df': None,
        'summary_df': None,
        'ohlc_cache_ready': False,
        'polygon_manager': None,
        'api_key_valid': False,
        'active_signals': None,
        'options_recommendation': None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# --- Main App Structure ---

st.title("📈 Strat Decision Engine")
st.markdown("Real-time FTFC reversal analysis powered by Polygon.io")

# --- API Key Management ---
api_key = st.sidebar.text_input("Polygon.io API Key", type="password", help="Enter your Polygon.io API key.")
if not api_key:
    api_key = os.environ.get(POLYGON_API_KEY_ENV)

if api_key and not st.session_state.polygon_manager:
    try:
        manager = PolygonDataManager(api_key)
        # Test connection
        if manager.client.get_snapshot('SPY'):
            st.session_state.polygon_manager = manager
            st.session_state.api_key_valid = True
            st.sidebar.success("API Key Valid & Connected!")
        else:
            st.sidebar.error("API Key is invalid.")
            st.session_state.api_key_valid = False
    except Exception as e:
        st.sidebar.error(f"Connection failed: {e}")
        st.session_state.api_key_valid = False

# Guard for API key
if not st.session_state.api_key_valid:
    st.error("Please provide a valid Polygon.io API key in the sidebar to proceed.")
    st.stop()

# --- UI Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scanner", "Live Signals", "Analyzer", "Options", "Settings"])

# =============================================================================
# TAB 1: SCANNER
# =============================================================================
with tab1:
    st.header("Scanner: Historical Analysis")
    
    with st.sidebar:
        st.header("Scanner Configuration")
        symbols_to_scan = st.multiselect("Symbols", options=EXTENDED_SYMBOLS, default=DEFAULT_SYMBOLS[:4])
        timeframes_to_scan = st.multiselect("Timeframes", options=list(TIMEFRAMES.keys()), default=['1hour', '4hour', 'daily', 'weekly'])
        use_ohlc_precision = st.checkbox("Use OHLC Precision", value=True)
        months_history = st.slider("Months of History", 1, 24, OHLC_MONTHS_BACK)
        min_confluence = st.number_input("Min Higher TF Confluence", 2, 5, MIN_HIGHER_TFS_FOR_FTFC)
        run_scanner_button = st.button("🚀 Run Scanner")

    if run_scanner_button:
        st.session_state.analysis_complete = False
        st.subheader("Analysis in Progress...")
        progress_bar = st.progress(0, text="Starting...")
        log_container = st.container(height=300, border=True)
        
        manager = st.session_state.polygon_manager
        all_data = {}
        total_fetches = len(symbols_to_scan) * len(timeframes_to_scan)
        
        def progress_callback(completed, total, symbol, tf):
            progress_bar.progress(completed / total, text=f"Fetching {symbol} {tf}...")
            log_container.info(f"Fetching {symbol} {tf}...")

        with st.spinner("Fetching data from cache/API..."):
            all_data = manager.batch_fetch(symbols_to_scan, timeframes_to_scan, months_history, progress_callback)

        if not all_data:
            log_container.error("No data fetched. Check API key and symbols.")
            st.error("Failed to fetch data. Please check your configuration.")
            st.stop()

        log_container.info(f"Fetched data for {len(all_data)} symbol/timeframe combinations.")

        # Step 2: Detect FTFC reversals
        progress_bar.progress(0.5, text="Detecting FTFC reversals...")
        log_container.info("Analyzing patterns and higher timeframe confluence...")

        try:
            detailed_df = detect_ftfc_reversals(
                ohlc_data=all_data,
                min_higher_tfs=min_confluence,
                performance_lookahead_bars=PERFORMANCE_LOOKAHEAD_BARS
            )

            if detailed_df.empty:
                log_container.warning("No FTFC reversals found with current criteria.")
                st.warning("No FTFC reversal setups found. Try lowering the confluence threshold or expanding symbol/timeframe selection.")
                st.stop()

            log_container.info(f"Found {len(detailed_df)} reversal setups.")

            # Step 3: Run simulations if OHLC precision is enabled
            progress_bar.progress(0.7, text="Running performance simulations...")

            risk_model = RiskModel(
                stop_pct=DEFAULT_STOP_PCT,
                contracts=DEFAULT_CONTRACTS,
                scale_out_R=DEFAULT_SCALE_OUT_R,
                trailing_after_R=DEFAULT_TRAILING_AFTER_R,
                trailing_gap_R=DEFAULT_TRAILING_GAP_R
            )

            ohlc_cache = None
            if use_ohlc_precision:
                log_container.info("Building OHLC lookup cache for precise simulation...")
                ohlc_cache = build_ohlc_lookup(detailed_df, manager, PERFORMANCE_LOOKAHEAD_BARS)
                log_container.info(f"Built OHLC cache for {len(ohlc_cache)} reversals.")

            # Step 4: Summarize setups
            progress_bar.progress(0.85, text="Summarizing setup performance...")
            log_container.info("Aggregating statistics by pattern and timeframe...")

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

            # Calculate targets and stops for detailed view
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

            # Calculate how many bars ago each reversal occurred
            now = pd.Timestamp.now(tz='America/New_York')
            detailed_df['Bars Ago'] = detailed_df.apply(
                lambda row: len(all_data.get((row['Symbol'], row['Timeframe']), pd.DataFrame())[
                    all_data.get((row['Symbol'], row['Timeframe']), pd.DataFrame()).index > row['Reversal Time']
                ]) if (row['Symbol'], row['Timeframe']) in all_data else 0,
                axis=1
            )

            # Store in session state
            st.session_state.detailed_df = detailed_df
            st.session_state.summary_df = summary_df
            st.session_state.analysis_complete = True
            st.session_state.ohlc_cache_ready = use_ohlc_precision

            progress_bar.progress(1.0, text="Analysis Complete!")
            log_container.success(f"Analysis complete! Found {len(detailed_df)} reversals across {len(summary_df)} unique setups.")
            st.success(f"Scanner complete! Analyzed {len(symbols_to_scan)} symbols × {len(timeframes_to_scan)} timeframes.")

        except Exception as e:
            log_container.error(f"Error during analysis: {str(e)}")
            st.error(f"Analysis failed: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

    if st.session_state.analysis_complete:
        st.subheader("Scanner Results")

        # Summary cards
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Setups Found", len(st.session_state.detailed_df))

        with col2:
            st.metric("Unique Patterns", len(st.session_state.summary_df))

        with col3:
            if 'win_rate' in st.session_state.summary_df.columns:
                avg_win_rate = st.session_state.summary_df['win_rate'].mean() * 100
                st.metric("Avg Win Rate", f"{avg_win_rate:.1f}%")
            else:
                st.metric("Avg Win Rate", "N/A")

        with col4:
            if 'expectancy_R' in st.session_state.summary_df.columns:
                avg_exp = st.session_state.summary_df['expectancy_R'].mean()
                st.metric("Avg Expectancy", f"{avg_exp:.2f}R")
            else:
                st.metric("Avg Expectancy", "N/A")

        st.divider()

        # Tabs for different views
        result_tab1, result_tab2, result_tab3 = st.tabs(["Overview", "Detailed Reversals", "Downloads"])

        with result_tab1:
            st.subheader("Top Setups by Performance")

            # Display summary table
            display_summary = st.session_state.summary_df.copy()

            # Format columns for display
            if 'win_rate' in display_summary.columns:
                display_summary['Win Rate %'] = (display_summary['win_rate'] * 100).round(1)
            if 'expectancy_R' in display_summary.columns:
                display_summary['Expectancy R'] = display_summary['expectancy_R'].round(2)
            if 'frequency_per_week' in display_summary.columns:
                display_summary['Freq/Week'] = display_summary['frequency_per_week'].round(2)

            # Select display columns
            display_cols = ['Timeframe', 'Pattern']
            if 'sample_count' in display_summary.columns:
                display_cols.append('sample_count')
            if 'Win Rate %' in display_summary.columns:
                display_cols.append('Win Rate %')
            if 'Expectancy R' in display_summary.columns:
                display_cols.append('Expectancy R')
            if 'Freq/Week' in display_summary.columns:
                display_cols.append('Freq/Week')

            st.dataframe(
                display_summary[display_cols] if all(c in display_summary.columns for c in display_cols) else display_summary,
                use_container_width=True,
                height=400
            )

        with result_tab2:
            st.subheader("All Reversal Events")

            # Add filters
            filter_col1, filter_col2, filter_col3 = st.columns(3)

            with filter_col1:
                if 'Symbol' in st.session_state.detailed_df.columns:
                    symbol_filter = st.multiselect(
                        "Filter by Symbol",
                        options=sorted(st.session_state.detailed_df['Symbol'].unique()),
                        default=None
                    )

            with filter_col2:
                if 'Timeframe' in st.session_state.detailed_df.columns:
                    tf_filter = st.multiselect(
                        "Filter by Timeframe",
                        options=st.session_state.detailed_df['Timeframe'].unique(),
                        default=None
                    )

            with filter_col3:
                if 'Pattern' in st.session_state.detailed_df.columns:
                    pattern_filter = st.multiselect(
                        "Filter by Pattern",
                        options=sorted(st.session_state.detailed_df['Pattern'].unique()),
                        default=None
                    )

            # Apply filters
            filtered_df = st.session_state.detailed_df.copy()
            if symbol_filter:
                filtered_df = filtered_df[filtered_df['Symbol'].isin(symbol_filter)]
            if tf_filter:
                filtered_df = filtered_df[filtered_df['Timeframe'].isin(tf_filter)]
            if pattern_filter:
                filtered_df = filtered_df[filtered_df['Pattern'].isin(pattern_filter)]

            # Format for display
            display_detailed = filtered_df.copy()

            # Select key columns for display
            key_cols = ['Symbol', 'Timeframe', 'Pattern', 'Reversal Time',
                       'Entry Price', 'Stop Price', 'T1', 'T2',
                       'Higher TF Trend', 'FTFC Count', 'Bars Ago']

            display_cols = [col for col in key_cols if col in display_detailed.columns]

            st.dataframe(
                display_detailed[display_cols],
                use_container_width=True,
                height=500
            )

            st.caption(f"Showing {len(filtered_df)} of {len(st.session_state.detailed_df)} reversals")

        with result_tab3:
            st.subheader("Export Results")

            col1, col2 = st.columns(2)

            with col1:
                st.download_button(
                    label="Download Detailed CSV",
                    data=st.session_state.detailed_df.to_csv(index=False),
                    file_name=f"ftfc_detailed_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )

            with col2:
                st.download_button(
                    label="Download Summary CSV",
                    data=st.session_state.summary_df.to_csv(index=True),
                    file_name=f"ftfc_summary_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )

            st.info("Additional export formats (Excel, JSON, ZIP) coming soon!")

# =============================================================================
# TAB 2: LIVE SIGNALS
# =============================================================================
with tab2:
    st.header("Live Signals: Real-time Opportunities")
    # Placeholder content
    st.info("Live signals feature is under development.")

# =============================================================================
# TAB 3: ANALYZER
# =============================================================================
with tab3:
    st.header("Analyzer: Deep-Dive and Ranking")
    # Placeholder content
    st.info("Analyzer feature is under development.")

# =============================================================================
# TAB 4: OPTIONS
# =============================================================================
with tab4:
    st.header("Options: Strategy Recommendations")
    
    with st.sidebar:
        st.header("Options Analysis")
        if st.session_state.detailed_df is not None:
            setup_options = [f"{row.Symbol} {row.Timeframe} {row.Pattern}" for index, row in st.session_state.detailed_df.iterrows()]
            selected_setup = st.selectbox("Select a setup from Scanner", options=setup_options)
        else:
            st.text_input("Symbol", value="SPY")
        analyze_options_button = st.button("🔍 Analyze Options")

    if analyze_options_button and 'selected_setup' in locals():
        # Extract details from selected setup
        symbol, tf, pattern = selected_setup.split()
        setup_row = st.session_state.detailed_df.iloc[0] # Simplified
        
        analyzer = OptionsAnalyzer(st.session_state.polygon_manager.client)
        with st.spinner("Analyzing options..."):
            recommendation = analyzer.analyze_setup_for_options(
                symbol=setup_row['Symbol'],
                entry_price=setup_row['Entry'],
                stop_price=setup_row['Stop'],
                target_r1=setup_row['T1'],
                target_r2=setup_row['T2'],
                expectancy_r=setup_row['Expectancy'],
                win_rate=setup_row['Win%'] / 100,
                side='long' if 'u' in setup_row['Pattern'] else 'short'
            )
            st.session_state.options_recommendation = recommendation

    if st.session_state.options_recommendation:
        analyzer = OptionsAnalyzer(st.session_state.polygon_manager.client)
        st.markdown(analyzer.format_recommendation_for_display(st.session_state.options_recommendation))

# =============================================================================
# TAB 5: SETTINGS
# =============================================================================
with tab5:
    st.header("Settings & Cache Management")
    st.subheader("Cache Statistics")

    if st.button("Refresh Cache Stats"):
        st.session_state.cache_stats = st.session_state.polygon_manager.get_cache_stats()

    if 'cache_stats' in st.session_state and st.session_state.cache_stats is not None:
        st.dataframe(st.session_state.cache_stats)
    
    st.subheader("Cache Actions")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔄 Refresh Stale Cache"):
            # Placeholder for selective refresh
            st.toast("Refreshing stale items...")
    with col2:
        if st.button("🗑️ Clear All Cache", type="primary"):
            st.session_state.polygon_manager.clear_cache()
            st.toast("All cache cleared!")
            # Clear stats view
            if 'cache_stats' in st.session_state: del st.session_state.cache_stats