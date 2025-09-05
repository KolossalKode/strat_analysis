# strat_app_v1_2025-09-01.py

import streamlit as st
import json
import pandas as pd
from datetime import date, datetime
import os
import numpy as np
import plotly.graph_objects as go
import time
import warnings
import tempfile

try:
    from dotenv import load_dotenv
except ImportError:
    # Make dotenv optional. If not installed, user can enter API key manually.
    load_dotenv = None
import zipfile
import io

# Analyzer imports
try:
    from setup_analyzer.engine import RiskModel, summarize_setups, to_machine_json
    from setup_analyzer.io import load_detailed, coerce_dtypes, detect_horizons
except Exception:
    # Allow the app to run even if analyzer is not available; UI will guard usage
    RiskModel = None
    summarize_setups = None
    to_machine_json = None
    load_detailed = None
    coerce_dtypes = None
    detect_horizons = None

from alpha_vantage.timeseries import TimeSeries

# Load environment variables from .env file at the start
if load_dotenv:
    load_dotenv()
# ==============================================================================
# SCRIPT CONFIGURATION & HELPER FUNCTIONS (Largely unchanged from original)
# ==============================================================================

# Suppress warnings for a cleaner UI
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
pd.options.mode.chained_assignment = None

# --- Constants ---
SYMBOLS_LIST = ['SPY', 'QQQ', 'XLC', 'XLY', 'XLP', 'XLE', 'XLF', 'XLV',
                'XLI', 'XLB', 'XLRE', 'XLK', 'XLU', 'MSFT', 'TSLA', 'GLD']
PERFORMANCE_LOOKAHEAD = 10
MIN_HIGHER_TFS_FOR_FTFC = 3
SLEEP_BETWEEN_SYMBOLS = 1

TIMEFRAMES_API = {
    'TIME_SERIES_INTRADAY': ['15min', '60min'],
    'TIME_SERIES_DAILY_ADJUSTED': 'Daily',
    'TIME_SERIES_WEEKLY_ADJUSTED': 'Weekly',
    'TIME_SERIES_MONTHLY_ADJUSTED': 'Monthly'
}
TIMEFRAME_ORDER = ['15min', '60min', 'Daily', 'Weekly', 'Monthly', 'Quarterly', 'Yearly']

REVERSAL_PATTERNS_STRAT = {
    ("3", "1", "2u"): "3-1-2u", ("3", "1", "2d"): "3-1-2d",
    ("2u", "1", "2d"): "2u-1-2d", ("2d", "1", "2u"): "2d-1-2u",
    ("2u", "2d"): "2u-2d", ("2d", "2u"): "2d-2u",
}

# Note: All functions from the original script are included here.
# To keep this response clean, I've collapsed them. The full, runnable
# code will have all functions (get_data, label_candlesticks, etc.) defined here.
# The only change is replacing print() with status_ui.write() for UI feedback.

# <editor-fold desc="Core Analysis Functions from Original Script">
def get_data(symbol, function, interval, ts_client, status_ui):
    max_retries = 3
    retry_delay = 10
    for attempt in range(max_retries):
        try:
            tf_name = interval or function.split('TIME_SERIES_')[-1].replace('_ADJUSTED', '')
            status_ui.write(f"   Attempt {attempt+1}/{max_retries}: Fetching {tf_name} for {symbol}...")
            
            if function == 'TIME_SERIES_INTRADAY':
                df, _ = ts_client.get_intraday(symbol=symbol, interval=interval, outputsize='full', extended_hours=False)
            elif function == 'TIME_SERIES_DAILY_ADJUSTED':
                df, _ = ts_client.get_daily_adjusted(symbol=symbol, outputsize='full')
            elif function == 'TIME_SERIES_WEEKLY_ADJUSTED':
                df, _ = ts_client.get_weekly_adjusted(symbol=symbol)
            elif function == 'TIME_SERIES_MONTHLY_ADJUSTED':
                df, _ = ts_client.get_monthly_adjusted(symbol=symbol)
            else:
                status_ui.write(f"Warning: Unknown function '{function}'.")
                return None

            if df is not None and not df.empty:
                df.columns = [c.split('. ')[-1].replace(' ', '_') if '.' in c else c.replace(' ', '_') for c in df.columns]
                df.index = pd.to_datetime(df.index, errors='coerce')
                df = df[pd.notna(df.index)]
                df = df.iloc[::-1]
                for col in ['open', 'high', 'low', 'close', 'adjusted_close', 'volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
                if df.empty: return None
                status_ui.write(f"   OK: Fetched/cleaned {len(df)} rows for {symbol} - {tf_name}.")
                return df
            else:
                time.sleep(1)
                return None
        except ValueError as ve:
            status_ui.write(f"   ERROR (ValueError): {ve}")
            if "rate limit" in str(ve): time.sleep(retry_delay * (2**attempt))
            else: return None
        except Exception as e:
            status_ui.write(f"   ERROR (Unexpected): {type(e).__name__} - {e}")
            if attempt == max_retries - 1: return None
            else: time.sleep(retry_delay * (2**attempt))
    status_ui.write(f"   Failed fetch for {symbol} - {tf_name} after retries.")
    return None

def label_candlesticks(df):
    if df is None or df.empty: return df
    if not isinstance(df.index, pd.DatetimeIndex): df['label'] = 'N/A'; return df
    if not df.index.is_monotonic_increasing: df = df.sort_index()
    prev_high = df['high'].shift(1); prev_low = df['low'].shift(1)
    is_inside = (df['high'] <= prev_high) & (df['low'] >= prev_low)
    is_up = (df['high'] > prev_high) & (df['low'] >= prev_low)
    is_down = (df['high'] <= prev_high) & (df['low'] < prev_low)
    is_outside = (df['high'] > prev_high) & (df['low'] < prev_low)
    df['label'] = 'N/A'
    df.loc[is_inside, 'label'] = '1'
    df.loc[is_up, 'label'] = '2u'
    df.loc[is_down, 'label'] = '2d'
    df.loc[is_outside, 'label'] = '3'
    if not df.empty: df.iloc[0, df.columns.get_loc('label')] = 'N/A'
    return df

def resample_data(df, freq='QE'):
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex): return None
    agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    try:
        df_resampled = df.resample(freq).agg(agg_dict).dropna(how='all')
        return label_candlesticks(df_resampled)
    except Exception:
        return None

def analyze_historical_ftfc_reversals(symbol_data, symbol, timeframe_order, status_ui, lookahead=10, min_higher_tfs=3):
    status_ui.write(f"   Analyzing {symbol} for FTFC Reversals...")
    historical_reversals = []
    
    # --- Precompute aligned labels ---
    aligned_labels_cache = {}
    available_tfs_info = [{'name': tf, 'index': df.index, 'labels': df['label']} 
                          for tf in timeframe_order if (df := symbol_data.get(tf)) is not None and 'label' in df.columns]
    
    if not available_tfs_info: return pd.DataFrame()

    all_indices = pd.concat([pd.Series(index=info['index']) for info in available_tfs_info]).index.unique()
    base_aligned_df = pd.DataFrame(index=all_indices.sort_values())

    for tf_info in available_tfs_info:
        temp_aligned = pd.merge_asof(base_aligned_df, tf_info['labels'].rename(f'label_{tf_info["name"]}'),
                                      left_index=True, right_index=True, direction='backward', tolerance=pd.Timedelta('30 days'))
        aligned_labels_cache[tf_info["name"]] = temp_aligned[f'label_{tf_info["name"]}']

    available_tfs_with_labels = sorted([tf for tf in timeframe_order if tf in aligned_labels_cache], key=lambda x: timeframe_order.index(x))

    for i, smaller_tf in enumerate(available_tfs_with_labels):
        smaller_df = symbol_data.get(smaller_tf)
        if smaller_df is None or smaller_df.empty: continue
        
        higher_tfs = available_tfs_with_labels[i + 1 : i + 1 + min_higher_tfs]
        if len(higher_tfs) < min_higher_tfs: continue

        labels_df = pd.DataFrame({'smaller_label': aligned_labels_cache[smaller_tf].reindex(smaller_df.index)})
        for k, htf in enumerate(higher_tfs):
            labels_df[f'higher_label_{k}'] = aligned_labels_cache[htf].reindex(smaller_df.index)
        
        labels_df.dropna(inplace=True)
        if labels_df.empty: continue

        htf_2u_trend = (labels_df['higher_label_0'] == '2u')
        htf_2d_trend = (labels_df['higher_label_0'] == '2d')
        for k in range(1, min_higher_tfs):
            htf_2u_trend &= (labels_df[f'higher_label_{k}'] == '2u')
            htf_2d_trend &= (labels_df[f'higher_label_{k}'] == '2d')
        
        smaller_tf_rev_vs_2u = labels_df['smaller_label'].isin(['2d', '1', '3'])
        smaller_tf_rev_vs_2d = labels_df['smaller_label'].isin(['2u', '1', '3'])
        
        reversal_indices = labels_df.index[(htf_2u_trend & smaller_tf_rev_vs_2u) | (htf_2d_trend & smaller_tf_rev_vs_2d)]
        if reversal_indices.empty: continue
        status_ui.write(f"         Found {len(reversal_indices)} potential reversals for {symbol} on {smaller_tf}.")

        for reversal_time in reversal_indices:
            try:
                reversal_iloc = smaller_df.index.get_loc(reversal_time)
                if reversal_iloc + 1 + lookahead > len(smaller_df): continue
                
                trend = '2u' if htf_2u_trend.loc[reversal_time] else '2d'
                reversal_label = labels_df.loc[reversal_time, 'smaller_label']
                
                strat_pattern_found = "N/A"
                if reversal_iloc >= 2:
                    label_seq_3 = tuple(smaller_df['label'].iloc[reversal_iloc-2 : reversal_iloc+1])
                    strat_pattern_found = REVERSAL_PATTERNS_STRAT.get(label_seq_3, "N/A")
                if strat_pattern_found == "N/A" and reversal_iloc >= 1:
                    label_seq_2 = tuple(smaller_df['label'].iloc[reversal_iloc-1 : reversal_iloc+1])
                    strat_pattern_found = REVERSAL_PATTERNS_STRAT.get(label_seq_2, "N/A")

                reversal_candle = smaller_df.iloc[reversal_iloc]
                future_candles = smaller_df.iloc[reversal_iloc + 1 : reversal_iloc + 1 + lookahead]
                entry_price = reversal_candle['close']
                if pd.isna(entry_price) or entry_price == 0: continue

                perf_data = {'Symbol': symbol, 'Reversal Time': reversal_time, 'Reversal Timeframe': smaller_tf,
                             'FTFC Trigger Label': reversal_label, 'Strat Pattern': strat_pattern_found,
                             'Higher TF Trend': trend, 'Entry Price': entry_price, 'Higher TFs Used': ", ".join(higher_tfs)}
                
                for k in range(1, lookahead + 1):
                    if k - 1 < len(future_candles):
                        future_close = future_candles.iloc[k - 1]['close']
                        perc_move = (future_close - entry_price) / entry_price * 100
                        perf_data[f'Fwd_{k}_PercMoveFromEntry'] = perc_move
                
                historical_reversals.append(perf_data)
            except Exception:
                continue

    return pd.DataFrame(historical_reversals) if historical_reversals else pd.DataFrame()

def aggregate_performance_results(historical_df, status_ui):
    if historical_df is None or historical_df.empty:
        status_ui.write("   No historical data to aggregate.")
        return pd.DataFrame()
    status_ui.write("   Aggregating performance results...")
    
    perc_move_cols = [col for col in historical_df.columns if col.endswith('_PercMoveFromEntry')]
    grouping_keys = ['Symbol', 'Reversal Timeframe', 'Higher TF Trend', 'Strat Pattern', 'FTFC Trigger Label']
    
    try:
        grouped = historical_df.groupby(grouping_keys)
        summary = grouped[perc_move_cols].mean()
        summary['Count'] = grouped.size()
        summary.columns = [f'Avg_{col}' if col != 'Count' else col for col in summary.columns]
        status_ui.write(f"   Aggregation complete. Summary has {len(summary)} rows.")
        return summary.reset_index()
    except Exception as e:
        status_ui.write(f"   Error during aggregation: {e}")
        return pd.DataFrame()

def build_and_save_chart_to_memory(df, symbol, timeframe):
    if df is None or df.empty: return None
    try:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
        label_y = np.where(df['label'].isin(['2d']), df['low'] * 0.998, df['high'] * 1.002)
        fig.add_trace(go.Scatter(x=df.index, y=label_y, text=df['label'], mode='text', name='Strat Labels', showlegend=False))
        fig.update_layout(title=f"{symbol} - {timeframe}", xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception:
        return None
# </editor-fold>

# ==============================================================================
# MAIN ANALYSIS WORKFLOW (ADAPTED FOR STREAMLIT)
# ==============================================================================

def run_analysis(symbols, api_key, status_ui):
    """
    Main execution function adapted for Streamlit.
    Loops through symbols, performs analysis, and returns results.
    """
    start_time = datetime.now()
    status_ui.write(f"--- Analysis Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    try:
        ts_client = TimeSeries(key=api_key, output_format='pandas')
        status_ui.write("OK: Alpha Vantage client initialized.")
    except Exception as e:
        st.error(f"ERROR: Failed to initialize Alpha Vantage client. Check API Key. Details: {e}")
        return None, None, None

    all_historical_reversals_list = []
    chart_files = {} # Dict to store HTML content: {(symbol, tf): html_string}
    processed_symbols_count = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        for i, symbol in enumerate(symbols):
            progress_bar.progress((i + 1) / len(symbols), text=f"Processing {symbol}...")
            status_ui.write(f"\n--- Processing Symbol: {symbol} ---")
            symbol_data = {}
            
            # 1. Fetch Data
            for function, intervals_or_name in TIMEFRAMES_API.items():
                if isinstance(intervals_or_name, list):
                    for tf in intervals_or_name:
                        df = get_data(symbol, function, tf, ts_client, status_ui)
                        if df is not None: symbol_data[tf] = df
                else:
                    df = get_data(symbol, function, None, ts_client, status_ui)
                    if df is not None: symbol_data[intervals_or_name] = df
            
            if not symbol_data or 'Monthly' not in symbol_data:
                status_ui.write(f"Warning: Insufficient data for {symbol}. Skipping.")
                time.sleep(SLEEP_BETWEEN_SYMBOLS)
                continue
            
            # 2. Resample & 3. Label
            status_ui.write(f" Phase 2 & 3: Resampling & Labeling for {symbol}")
            monthly_data = symbol_data['Monthly']
            quarterly_data = resample_data(monthly_data, 'QE')
            if quarterly_data is not None and not quarterly_data.empty:
                symbol_data['Quarterly'] = quarterly_data
            yearly_data = resample_data(monthly_data, 'YE')
            if yearly_data is not None and not yearly_data.empty:
                symbol_data['Yearly'] = yearly_data
            
            for tf, df in symbol_data.items():
                symbol_data[tf] = label_candlesticks(df)
            
            # 4. Generate Charts (in memory)
            status_ui.write(f" Phase 4: Generating Charts for {symbol}")
            for tf, df in symbol_data.items():
                html_content = build_and_save_chart_to_memory(df, symbol, tf)
                if html_content:
                    chart_files[(symbol, tf)] = html_content

            # 5. Analyze FTFC
            status_ui.write(f" Phase 5: Analyzing FTFC Reversals for {symbol}")
            symbol_reversals_df = analyze_historical_ftfc_reversals(symbol_data, symbol, TIMEFRAME_ORDER, status_ui)
            
            if not symbol_reversals_df.empty:
                all_historical_reversals_list.append(symbol_reversals_df)
                processed_symbols_count += 1
                status_ui.write(f"   Finished analysis for {symbol}. Found {len(symbol_reversals_df)} reversals.")
            else:
                status_ui.write(f"   No reversals found for {symbol}.")
            
            time.sleep(SLEEP_BETWEEN_SYMBOLS)

    # 7. Combine & 8. Aggregate Results
    if not all_historical_reversals_list:
        st.warning("No historical reversals found across any of the selected symbols.")
        return None, None, None
        
    status_ui.write("\n--- Combining and Aggregating All Results ---")
    combined_df = pd.concat(all_historical_reversals_list, ignore_index=True)
    summary_df = aggregate_performance_results(combined_df, status_ui)
    
    end_time = datetime.now()
    status_ui.write(f"\n--- Analysis Complete: {end_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    status_ui.write(f"Total execution time: {end_time - start_time}")
    
    return combined_df, summary_df, chart_files

def create_zip_for_download(detailed_df, summary_df, chart_files):
    """Creates a zip file in memory containing all results."""
    zip_buffer = io.BytesIO()
    today_str = date.today().strftime("%Y-%m-%d")

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        # 1. Add Excel files
        if detailed_df is not None and not detailed_df.empty:
            excel_buffer = io.BytesIO()
            detailed_df.to_excel(excel_buffer, index=False, engine='openpyxl')
            zip_file.writestr(f"{today_str}_FTFC_Performance_Detailed.xlsx", excel_buffer.getvalue())

        if summary_df is not None and not summary_df.empty:
            excel_buffer = io.BytesIO()
            summary_df.to_excel(excel_buffer, index=False, engine='openpyxl')
            zip_file.writestr(f"{today_str}_FTFC_Performance_Summary.xlsx", excel_buffer.getvalue())

        # 2. Add chart HTML files
        if chart_files:
            for (symbol, tf), html_content in chart_files.items():
                zip_file.writestr(f"charts/{symbol}/{symbol}_{tf}_Chart.html", html_content)
                
    return zip_buffer.getvalue()

# ==============================================================================
# STREAMLIT UI
# ==============================================================================

st.set_page_config(layout="wide", page_title="FTFC Reversal Analysis")

st.title("📈 The Strat: FTFC Reversal Analysis")
st.markdown("""
This application analyzes historical stock data to identify 'Full Timeframe Continuity' (FTFC) reversals based on 'The Strat' methodology.
Use the Scanner to produce a results ZIP, then open the Analyzer tab to rank setups and export JSON.
""")

# Session state (shared by tabs)
if 'analysis_complete' not in st.session_state:
    st.session_state.analysis_complete = False
if 'zip_data' not in st.session_state:
    st.session_state.zip_data = None
if 'summary_df' not in st.session_state:
    st.session_state.summary_df = None

# Tabs for Scanner and Analyzer
scanner_tab, analyzer_tab = st.tabs(["Scanner", "Analyzer"])

# --- Sidebar for Inputs ---
with scanner_tab:
    # --- Sidebar for Inputs ---
    with st.sidebar:
        st.header("⚙️ Scanner Configuration")
        selected_symbols = st.multiselect("Select Stock Symbols", options=SYMBOLS_LIST, default=['SPY', 'QQQ'])
        run_button = st.button("🚀 Run Analysis")

    # --- Main Area for Outputs ---
    if run_button:
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
        if not selected_symbols:
            st.error("❌ Please select at least one symbol to analyze.")
        else:
            st.session_state.analysis_complete = False
            st.session_state.zip_data = None
            st.session_state.summary_df = None

            st.subheader("📊 Analysis in Progress...")
            progress_bar = st.progress(0, text="Starting...")
            status_container = st.container(height=300, border=True)

            with st.spinner('Running... this may take several minutes depending on the number of symbols.'):
                detailed_df, summary_df, charts = run_analysis(selected_symbols, api_key, status_container)

                if detailed_df is not None:
                    st.session_state.analysis_complete = True
                    st.session_state.summary_df = summary_df
                    st.session_state.zip_data = create_zip_for_download(detailed_df, summary_df, charts)
                    progress_bar.progress(1.0, text="Analysis Complete!")
                    st.success("✅ Analysis complete! Results are ready for download.")
                else:
                    progress_bar.progress(1.0, text="Analysis Finished with No Results.")
                    st.warning("Analysis finished, but no valid reversal data was generated.")

    if st.session_state.analysis_complete:
        st.subheader("📈 Performance Summary")
        st.dataframe(st.session_state.summary_df)

        st.download_button(
           label="📥 Download Results (.zip)",
           data=st.session_state.zip_data,
           file_name=f"{date.today().strftime('%Y-%m-%d')}_Strat_Analysis_Results.zip",
           mime="application/zip",
        )

with analyzer_tab:
    st.header("🔍 Setup Analyzer")

    if summarize_setups is None:
        st.info("Analyzer module is not available. Please ensure the 'setup_analyzer' package exists in this project.")
    else:
        # Source selection
        src_choice = st.radio("Select Input Source", ["Use current run's ZIP", "Upload ZIP/Excel/CSV"], index=0)

        detailed_df = None
        load_error = None

        if src_choice == "Use current run's ZIP":
            if st.session_state.get('zip_data'):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tf:
                        tf.write(st.session_state.zip_data)
                        tmp_zip_path = tf.name
                    detailed_df = load_detailed(tmp_zip_path)
                    detailed_df = coerce_dtypes(detailed_df)
                except Exception as e:
                    load_error = str(e)
                finally:
                    try:
                        os.remove(tmp_zip_path)
                    except Exception:
                        pass
            else:
                st.warning("No ZIP available from the Scanner yet. Run an analysis first or upload a file.")
        else:
            uploaded = st.file_uploader("Upload results ZIP/Excel/CSV", type=["zip", "xlsx", "csv"], accept_multiple_files=False)
            if uploaded is not None:
                try:
                    suffix = '.zip' if uploaded.name.lower().endswith('.zip') else ('.xlsx' if uploaded.name.lower().endswith('.xlsx') else '.csv')
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
                        tf.write(uploaded.read())
                        tmp_path = tf.name
                    detailed_df = load_detailed(tmp_path)
                    detailed_df = coerce_dtypes(detailed_df)
                except Exception as e:
                    load_error = str(e)
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

        if load_error:
            st.error(f"Failed to load input: {load_error}")

        # If we have data, show controls and run analyzer
        if detailed_df is not None and not detailed_df.empty:
            st.success(f"Loaded {len(detailed_df):,} detailed records.")

            # Parameter form
            with st.form("analyzer_form"):
                # Symbol filter
                symbol_options = sorted(detailed_df['Symbol'].dropna().unique().tolist()) if 'Symbol' in detailed_df.columns else []
                selected_symbols = st.multiselect(
                    "Filter by symbol(s)", options=symbol_options, default=symbol_options,
                    help="Choose one or more symbols to include in the analysis"
                ) if symbol_options else []

                # Group-by options from columns (common defaults first)
                default_group = ["Reversal Timeframe", "Strat Pattern"]
                available_cols = list(detailed_df.columns)
                # Ensure defaults exist
                group_defaults = [c for c in default_group if c in available_cols] or available_cols[:2]
                group_by = st.multiselect("Group setups by", options=available_cols, default=group_defaults)

                # Horizons
                detected = detect_horizons(detailed_df)
                horizons_text = st.text_input("Forward bar horizons (comma-separated)", value=",".join(str(x) for x in detected))
                horizons = sorted({int(x.strip()) for x in horizons_text.split(',') if x.strip().isdigit()})

                # Other knobs
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    top_n = st.number_input("Top N", min_value=1, max_value=100, value=10, step=1)
                with col2:
                    lookback_weeks = st.number_input("Lookback (weeks)", min_value=1, max_value=520, value=52, step=1)
                with col3:
                    min_samples = st.number_input("Min samples", min_value=1, max_value=1000, value=10, step=1)
                with col4:
                    side = st.selectbox("Side", options=["long", "short", "auto"], index=0)

                submitted = st.form_submit_button("Run Analyzer")

            if submitted:
                with st.spinner("Analyzing setups..."):
                    try:
                        # Apply symbol filter if provided
                        df_input = detailed_df
                        if selected_symbols:
                            df_input = df_input[df_input['Symbol'].isin(selected_symbols)]

                        risk = RiskModel()
                        summary = summarize_setups(
                            df_input,
                            group_by=group_by,
                            horizons=horizons,
                            lookback_weeks=int(lookback_weeks),
                            side=side,
                            min_samples=int(min_samples),
                            risk=risk,
                        )

                        if summary.empty:
                            st.warning("No setups met the criteria. Try lowering 'Min samples' or adjusting horizons.")
                        else:
                            st.subheader("🏆 Top Ranked Setups")
                            cols_show = group_by + ["sample_count", "frequency_per_week", "win_rate", "expectancy_R"]
                            top_summary = summary.head(int(top_n))
                            st.dataframe(top_summary[cols_show], use_container_width=True)

                            # Full summary table
                            with st.expander("Show full summary table", expanded=True):
                                st.dataframe(summary, use_container_width=True)

                            # Downloads
                            payload = to_machine_json(summary, group_by=group_by, horizons=horizons, risk=risk)
                            json_bytes = json.dumps(payload, indent=2).encode("utf-8")
                            st.download_button(
                                label="📥 Download Insights (JSON)",
                                data=json_bytes,
                                file_name=f"{date.today().strftime('%Y-%m-%d')}_setup_insights.json",
                                mime="application/json",
                            )

                            csv_bytes = top_summary.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="📥 Download Top-N (CSV)",
                                data=csv_bytes,
                                file_name=f"{date.today().strftime('%Y-%m-%d')}_top_setups.csv",
                                mime="text/csv",
                            )
                    except Exception as e:
                        st.error(f"Analyzer failed: {e}")
