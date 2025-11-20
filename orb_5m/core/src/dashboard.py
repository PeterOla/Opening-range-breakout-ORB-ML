"""Streamlit dashboard for ORB backtest results."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta
from plotly.subplots import make_subplots


# Page config
st.set_page_config(
    page_title="ORB Backtest Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark theme custom CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #1a1d2e;
        padding: 20px;
        border-radius: 8px;
        border-left: 4px solid #26a69a;
    }
    .profit { color: #26a69a; font-weight: bold; }
    .loss { color: #ef5350; font-weight: bold; }
    .stMetric { background-color: #1a1d2e; padding: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_data():
    """Load all backtest data."""
    base_dir = Path("results_combined_top20")
    
    data = {}
    
    # Load trades
    trades_path = base_dir / "all_trades.csv"
    if trades_path.exists():
        df = pd.read_csv(trades_path, parse_dates=['date', 'entry_time', 'exit_time'])
        data['trades'] = df
    
    # Load daily P&L
    daily_path = base_dir / "all_daily_pnl.csv"
    if daily_path.exists():
        df = pd.read_csv(daily_path, parse_dates=['date'])
        data['daily'] = df
    
    # Load summary stats
    summary_path = base_dir / "summary.txt"
    if summary_path.exists():
        with open(summary_path) as f:
            lines = f.readlines()
        
        stats = {}
        for line in lines:
            if ':' in line:
                key, val = line.strip().split(':', 1)
                key_clean = key.strip()
                val_clean = val.strip()
                try:
                    stats[key_clean] = float(val_clean)
                except:
                    stats[key_clean] = val_clean
        
        # Compute derived percentages for display
        if 'total_return' in stats:
            stats['total_return_pct'] = stats['total_return'] * 100
        if 'cagr' in stats:
            stats['cagr_pct'] = stats['cagr'] * 100
        if 'max_drawdown' in stats:
            stats['max_dd_pct'] = stats['max_drawdown'] * 100
        if 'hit_rate' in stats:
            stats['win_rate_pct'] = stats['hit_rate'] * 100
        if 'n_trades' in stats:
            stats['num_trades'] = int(stats['n_trades'])
        
        data['summary'] = stats
    
    # Load symbol leaderboard
    leaderboard_path = base_dir / "symbol_leaderboard.csv"
    if leaderboard_path.exists():
        data['leaderboard'] = pd.read_csv(leaderboard_path)
    
    # Load RVOL buckets
    rvol_path = base_dir / "rvol_bucket_analysis.csv"
    if rvol_path.exists():
        data['rvol_buckets'] = pd.read_csv(rvol_path)
    
    # Load Alpha/Beta
    ab_path = base_dir / "alpha_beta_spy.csv"
    if ab_path.exists():
        data['alpha_beta'] = pd.read_csv(ab_path).iloc[0].to_dict()
    
    return data


def plot_equity_curve(daily_df):
    """Create interactive equity curve with Plotly."""
    fig = go.Figure()
    
    # Equity line
    fig.add_trace(go.Scatter(
        x=daily_df['date'],
        y=daily_df['equity'],
        mode='lines',
        name='Equity',
        line=dict(color='#26a69a', width=2),
        fill='tozeroy',
        fillcolor='rgba(38, 166, 154, 0.1)'
    ))
    
    # Drawdown
    peak = daily_df['equity'].expanding().max()
    drawdown = (daily_df['equity'] - peak) / peak * 100
    
    fig.add_trace(go.Scatter(
        x=daily_df['date'],
        y=drawdown,
        mode='lines',
        name='Drawdown %',
        line=dict(color='#ef5350', width=1),
        yaxis='y2',
        fill='tonexty',
        fillcolor='rgba(239, 83, 80, 0.2)'
    ))
    
    fig.update_layout(
        title="Equity Curve & Drawdown",
        xaxis_title="Date",
        yaxis_title="Equity ($)",
        yaxis2=dict(title="Drawdown (%)", overlaying='y', side='right', showgrid=False),
        template='plotly_dark',
        hovermode='x unified',
        height=500
    )
    
    return fig


def load_intraday_data(symbol, date):
    """Load 1-minute intraday data for a specific symbol and date."""
    date_str = pd.to_datetime(date).strftime('%Y-%m-%d')
    
    # Try 1-min data first
    data_path = Path(f"data/processed/1min/{symbol}.parquet")
    
    if not data_path.exists():
        # Try 5-min data as fallback
        data_path = Path(f"data/processed/5min/{symbol}.parquet")
    
    if not data_path.exists():
        return None, None
    
    # Load data
    df = pd.read_parquet(data_path)
    df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
    
    # Filter to specific date
    df_day = df[df['timestamp'].dt.date == pd.to_datetime(date).date()].copy()
    
    if df_day.empty:
        return None, None
    
    # Determine timeframe from data
    time_diff = df_day['timestamp'].diff().min()
    timeframe = '1min' if time_diff <= pd.Timedelta('1min') else '5min'
    
    return df_day, timeframe


def plot_trade_chart(trade_row):
    """Create candlestick chart with trade markers."""
    # Load intraday data
    df_day, timeframe = load_intraday_data(trade_row['symbol'], trade_row['date'])
    
    if df_day is None or df_day.empty:
        st.warning(f"No intraday data found for {trade_row['symbol']} on {trade_row['date'].strftime('%Y-%m-%d')}")
        return None
    
    # Create candlestick chart
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=(f"{trade_row['symbol']} - {trade_row['date'].strftime('%Y-%m-%d')} ({timeframe})", 'Volume')
    )
    
    # Candlesticks
    fig.add_trace(
        go.Candlestick(
            x=df_day['timestamp'],
            open=df_day['open'],
            high=df_day['high'],
            low=df_day['low'],
            close=df_day['close'],
            name='Price',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        ),
        row=1, col=1
    )
    
    # Volume bars
    colors = ['#26a69a' if c >= o else '#ef5350' 
              for c, o in zip(df_day['close'], df_day['open'])]
    fig.add_trace(
        go.Bar(
            x=df_day['timestamp'],
            y=df_day['volume'],
            name='Volume',
            marker_color=colors,
            showlegend=False
        ),
        row=2, col=1
    )
    
    # Add horizontal lines for key levels
    # Opening range high/low
    if 'or_high' in trade_row and pd.notna(trade_row['or_high']):
        fig.add_hline(
            y=trade_row['or_high'],
            line_dash="dash",
            line_color="cyan",
            annotation_text="OR High",
            annotation_position="right",
            row=1, col=1
        )
    
    if 'or_low' in trade_row and pd.notna(trade_row['or_low']):
        fig.add_hline(
            y=trade_row['or_low'],
            line_dash="dash",
            line_color="cyan",
            annotation_text="OR Low",
            annotation_position="right",
            row=1, col=1
        )
    
    # Stop loss (calculate from ATR)
    if 'atr_14' in trade_row and pd.notna(trade_row['atr_14']):
        stop_distance = 0.10 * trade_row['atr_14']
        if trade_row['direction'] == 1:  # Long
            stop_price = trade_row['entry_price'] - stop_distance
        else:  # Short
            stop_price = trade_row['entry_price'] + stop_distance
        
        fig.add_hline(
            y=stop_price,
            line_dash="solid",
            line_color="red",
            line_width=2,
            annotation_text=f"Stop: ${stop_price:.2f}",
            annotation_position="right",
            row=1, col=1
        )
    
    # Mark opening range (first 5 minutes = first 5 bars if 1-min, first 1 bar if 5-min)
    or_end_time = df_day['timestamp'].iloc[0] + pd.Timedelta(minutes=5)
    or_bars = df_day[df_day['timestamp'] <= or_end_time]
    
    if not or_bars.empty:
        fig.add_vrect(
            x0=or_bars['timestamp'].iloc[0],
            x1=or_bars['timestamp'].iloc[-1],
            fillcolor="blue",
            opacity=0.1,
            layer="below",
            line_width=0,
            annotation_text="Opening Range",
            annotation_position="top left",
            row=1, col=1
        )
    
    # Mark entry time with arrow
    if 'entry_time' in trade_row and pd.notna(trade_row['entry_time']):
        # Convert to timezone-naive by converting to string then parsing
        entry_time_str = str(trade_row['entry_time']).split('+')[0].split('-05:00')[0].split('-04:00')[0]
        entry_time = pd.to_datetime(entry_time_str)
        
        fig.add_annotation(
            x=entry_time,
            y=trade_row['entry_price'],
            text="Entry",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.5,
            arrowwidth=2,
            arrowcolor="yellow",
            ax=0,
            ay=-40,
            bgcolor="rgba(255,255,0,0.8)",
            font=dict(color="black", size=10),
            row=1, col=1
        )
    
    # Mark exit time with arrow
    if 'exit_time' in trade_row and pd.notna(trade_row['exit_time']):
        # Convert to timezone-naive by converting to string then parsing
        exit_time_str = str(trade_row['exit_time']).split('+')[0].split('-05:00')[0].split('-04:00')[0]
        exit_time = pd.to_datetime(exit_time_str)
        
        fig.add_annotation(
            x=exit_time,
            y=trade_row['exit_price'],
            text="Exit",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.5,
            arrowwidth=2,
            arrowcolor="orange",
            ax=0,
            ay=-40,
            bgcolor="rgba(255,165,0,0.8)",
            font=dict(color="black", size=10),
            row=1, col=1
        )
    
    # Update layout
    fig.update_layout(
        template='plotly_dark',
        height=800,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        hovermode='x unified'
    )
    
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    
    return fig


def generate_tradingview_url(symbol, date, entry_time=None, exit_time=None, 
                              entry_price=None, exit_price=None,
                              or_high=None, or_low=None, stop_price=None):
    """Generate TradingView chart URL with trade details.
    
    Note: TradingView URLs don't support direct price level annotations via URL params.
    Users will see the chart and can manually add horizontal lines for verification.
    """
    # Format date for TradingView (Unix timestamp in seconds)
    trade_date = pd.to_datetime(date)
    # Set to market open (9:30 AM ET)
    chart_start = trade_date.replace(hour=9, minute=0, second=0)
    timestamp = int(chart_start.timestamp())
    
    # TradingView chart URL structure
    # - symbol: NASDAQ:AAPL format
    # - interval: 1 (1-min), 5 (5-min), 15, 60, D
    # - timestamp: Unix timestamp for chart center
    
    base_url = "https://www.tradingview.com/chart/"
    
    # Build URL with symbol and timeframe
    # Use 1-minute for detailed trade inspection
    url = f"{base_url}?symbol=NASDAQ:{symbol}&interval=1&timestamp={timestamp}"
    
    return url


def show_trade_detail(trade_row):
    """Display detailed trade information with chart."""
    st.markdown("### 🔍 Trade Details")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Entry Info**")
        st.write(f"Symbol: **{trade_row['symbol']}**")
        st.write(f"Date: {trade_row['date'].strftime('%Y-%m-%d')}")
        st.write(f"Direction: {'🟢 Long' if trade_row['direction'] == 1 else '🔴 Short'}")
        if 'entry_time' in trade_row and pd.notna(trade_row['entry_time']):
            st.write(f"Entry Time: {trade_row['entry_time']}")
        st.write(f"Entry Price: ${trade_row['entry_price']:.2f}")
    
    with col2:
        st.markdown("**Exit Info**")
        if 'exit_time' in trade_row and pd.notna(trade_row['exit_time']):
            st.write(f"Exit Time: {trade_row['exit_time']}")
        st.write(f"Exit Price: ${trade_row['exit_price']:.2f}")
        st.write(f"Shares: {int(trade_row['shares'])}")
        pnl = trade_row['net_pnl']
        pnl_color = "🟢" if pnl >= 0 else "🔴"
        st.write(f"Net P&L: {pnl_color} ${pnl:,.2f}")
    
    with col3:
        st.markdown("**Trade Context**")
        if 'or_high' in trade_row and pd.notna(trade_row['or_high']):
            st.write(f"OR High: ${trade_row['or_high']:.2f}")
        if 'or_low' in trade_row and pd.notna(trade_row['or_low']):
            st.write(f"OR Low: ${trade_row['or_low']:.2f}")
        if 'atr_14' in trade_row and pd.notna(trade_row['atr_14']):
            st.write(f"ATR(14): ${trade_row['atr_14']:.2f}")
        if 'or_rvol_14' in trade_row and pd.notna(trade_row['or_rvol_14']):
            st.write(f"RVOL: {trade_row['or_rvol_14']:.1f}x")
        if 'rvol_rank' in trade_row and pd.notna(trade_row['rvol_rank']):
            st.write(f"RVOL Rank: #{int(trade_row['rvol_rank'])}")
    
    st.markdown("---")
    
    # Interactive chart
    st.markdown("### 📊 Intraday Chart")
    chart = plot_trade_chart(trade_row)
    if chart:
        st.plotly_chart(chart, use_container_width=True)
    
    st.markdown("---")
    st.info("""
    **Chart Legend:**
    - **Blue shaded area**: Opening range (9:30-9:35 AM)
    - **Cyan dashed lines**: OR High/Low
    - **Yellow dotted line**: Entry price
    - **Orange dotted line**: Exit price
    - **Red solid line**: Stop loss (10% ATR)
    - **Yellow/Orange vertical lines**: Entry/Exit times (if available)
    """)


def plot_daily_pnl_bars(daily_df, num_days=60):
    """Plot recent daily P&L as bars."""
    recent = daily_df.tail(num_days).copy()
    
    colors = ['#26a69a' if x >= 0 else '#ef5350' for x in recent['net_pnl']]
    
    fig = go.Figure(data=[
        go.Bar(
            x=recent['date'],
            y=recent['net_pnl'],
            marker_color=colors,
            name='Daily P&L'
        )
    ])
    
    fig.update_layout(
        title=f"Daily P&L (Last {num_days} Days)",
        xaxis_title="Date",
        yaxis_title="P&L ($)",
        template='plotly_dark',
        height=400,
        showlegend=False
    )
    
    return fig


def main():
    st.title("📈 ORB Backtest Dashboard")
    st.markdown("---")
    
    # Load data
    with st.spinner("Loading data..."):
        data = load_data()
    
    if not data:
        st.error("No data found in results_combined_top20/")
        return
    
    # Sidebar filters
    st.sidebar.header("Filters")
    
    # Equity scaler
    st.sidebar.header("Equity Scaler")
    st.sidebar.markdown("Scale results to your desired starting equity")
    
    if 'summary' in data:
        base_equity = data['summary'].get('initial_equity', 100000.0)
    else:
        base_equity = 100000.0
    
    st.sidebar.info(f"Base backtest equity: ${base_equity:,.0f}")
    
    target_equity = st.sidebar.number_input(
        "Your Starting Equity ($)",
        min_value=100.0,
        max_value=10_000_000.0,
        value=base_equity,
        step=1000.0,
        format="%.0f"
    )
    
    equity_multiplier = target_equity / base_equity
    st.sidebar.metric("Scale Factor", f"{equity_multiplier:.2f}x")
    
    if 'trades' in data:
        trades_df = data['trades']
        
        # Date range
        min_date = trades_df['date'].min()
        max_date = trades_df['date'].max()
        
        date_range = st.sidebar.date_input(
            "Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        
        # Symbol filter
        all_symbols = sorted([str(s) for s in trades_df['symbol'].dropna().unique()])
        selected_symbols = st.sidebar.multiselect(
            "Symbols",
            options=all_symbols,
            default=[]
        )
        
        # Direction filter
        direction_filter = st.sidebar.radio(
            "Direction",
            options=["All", "Long", "Short"],
            index=0
        )
        
        # Apply filters to trades
        filtered_trades = trades_df.copy()
        
        if len(date_range) == 2:
            start, end = date_range
            filtered_trades = filtered_trades[
                (filtered_trades['date'] >= pd.Timestamp(start)) & 
                (filtered_trades['date'] <= pd.Timestamp(end))
            ]
        
        if selected_symbols:
            filtered_trades = filtered_trades[filtered_trades['symbol'].isin(selected_symbols)]
        
        if direction_filter != "All":
            # Direction is stored as 1 (long) or -1 (short) in the CSV
            dir_val = 1 if direction_filter == "Long" else -1
            filtered_trades = filtered_trades[filtered_trades['direction'] == dir_val]
    
    # Main content tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Overview", "📈 Trades", "🔍 Audit", "💰 Equity", "🏆 Leaderboard", "🔬 Analysis"])
    
    with tab1:
        # Summary metrics
        st.header("Performance Summary")
        
        # Compute metrics from filtered trades
        if 'trades' in data and len(filtered_trades) > 0:
            df = filtered_trades
            
            # Scale P&L values by equity multiplier
            total_pnl = df['net_pnl'].sum() * equity_multiplier
            wins = (df['net_pnl'] > 0).sum()
            losses = (df['net_pnl'] <= 0).sum()
            win_rate = wins / len(df) if len(df) > 0 else 0
            
            avg_win = df[df['net_pnl'] > 0]['net_pnl'].mean() * equity_multiplier if wins > 0 else 0
            avg_loss = abs(df[df['net_pnl'] <= 0]['net_pnl'].mean()) * equity_multiplier if losses > 0 else 0
            profit_factor = (wins * avg_win) / (losses * avg_loss) if losses > 0 and avg_loss > 0 else 0
            
            # Compute equity curve from filtered trades with scaled initial equity
            df_sorted = df.sort_values('date').reset_index(drop=True)
            scaled_pnl = df_sorted['net_pnl'] * equity_multiplier
            equity_curve = target_equity + scaled_pnl.cumsum()
            total_return_pct = (equity_curve.iloc[-1] / target_equity - 1) * 100
            
            # Max drawdown
            peak = equity_curve.expanding().max()
            drawdown = (equity_curve - peak) / peak
            max_dd_pct = drawdown.min() * 100
            
            cols = st.columns(5)
            
            with cols[0]:
                st.metric("Total Return", f"{total_return_pct:.1f}%")
            with cols[1]:
                st.metric("Total P&L", f"${total_pnl:,.0f}")
            with cols[2]:
                st.metric("Total Trades", f"{len(df):,}")
            with cols[3]:
                st.metric("Max Drawdown", f"{max_dd_pct:.2f}%")
            with cols[4]:
                st.metric("Win Rate", f"{win_rate*100:.1f}%")
            
            st.markdown("---")
            
            cols2 = st.columns(5)
            with cols2[0]:
                st.metric("Profit Factor", f"{profit_factor:.2f}")
            with cols2[1]:
                st.metric("Avg Win", f"${avg_win:,.0f}")
            with cols2[2]:
                st.metric("Avg Loss", f"${avg_loss:,.0f}")
            with cols2[3]:
                if 'alpha_beta' in data:
                    alpha = data['alpha_beta'].get('alpha_pct', 0)
                    st.metric("Alpha vs SPY", f"{alpha:.1f}%")
            with cols2[4]:
                if 'alpha_beta' in data:
                    beta = data['alpha_beta'].get('beta', 0)
                    st.metric("Beta vs SPY", f"{beta:.2f}")
            
            st.markdown("---")
            
            # Kelly Criterion Analysis
            st.subheader("📊 Kelly Criterion Analysis")
            
            win_pnls = df[df['net_pnl'] > 0]['net_pnl']
            loss_pnls = df[df['net_pnl'] < 0]['net_pnl']
            
            if not win_pnls.empty and not loss_pnls.empty:
                avg_win_kelly = win_pnls.mean()
                avg_loss_kelly = -loss_pnls.mean()
                p = len(win_pnls) / len(df)
                R = avg_win_kelly / avg_loss_kelly if avg_loss_kelly > 0 else 0
                
                if R > 0:
                    kelly_f = p - (1 - p) / R
                    kelly_pct = kelly_f * 100
                    safe_pct = kelly_pct * 0.5
                    current_risk = 1.0  # 1% per trade
                    kelly_mult = current_risk / kelly_f if kelly_f > 0 else 0
                    
                    kelly_cols = st.columns(5)
                    with kelly_cols[0]:
                        st.metric("Kelly %", f"{kelly_pct:.2f}%", help="Optimal risk per trade according to Kelly criterion")
                    with kelly_cols[1]:
                        st.metric("Safe (1/2 Kelly)", f"{safe_pct:.2f}%", help="Conservative risk level (50% of Kelly)")
                    with kelly_cols[2]:
                        st.metric("Current Risk", f"{current_risk:.2f}%", help="Actual risk used in backtest")
                    with kelly_cols[3]:
                        kelly_usage = (current_risk / kelly_pct * 100) if kelly_pct > 0 else 0
                        st.metric("Kelly Usage", f"{kelly_usage:.0f}%", help="Current risk as % of optimal Kelly")
                    with kelly_cols[4]:
                        st.metric("Win/Loss Ratio", f"{R:.2f}x", help="Average win size / average loss size")
                    
                    if current_risk < safe_pct:
                        st.success(f"✅ **CONSERVATIVE**: Using {kelly_usage:.0f}% of Kelly - Very safe position sizing")
                    elif current_risk <= kelly_pct:
                        st.info(f"✅ **MODERATE**: Using {kelly_usage:.0f}% of Kelly - Between safe and full Kelly")
                    else:
                        st.warning(f"⚠️ **AGGRESSIVE**: Using {kelly_mult:.1f}x Kelly - Higher risk of ruin")
                    
                    # Risk scaling scenarios
                    st.markdown("---")
                    st.markdown("#### 💡 Risk Scaling Scenarios")
                    st.caption("Estimated outcomes if using different risk levels (linear approximation)")
                    
                    scenarios_data = {
                        "Risk Level": [
                            f"{current_risk:.2f}% (Current)",
                            f"{safe_pct:.2f}% (Safe Kelly)",
                            f"{kelly_pct:.2f}% (Full Kelly)",
                            f"{kelly_pct*2:.2f}% (Danger Kelly)"
                        ],
                        "Kelly Fraction": ["14%", "50%", "100%", "200%"],
                        "Est. 5yr Return": [
                            f"${equity_curve.iloc[-1]:,.0f}",
                            f"${equity_curve.iloc[-1] * (safe_pct/current_risk):,.0f}",
                            f"${equity_curve.iloc[-1] * (kelly_pct/current_risk):,.0f}",
                            f"${equity_curve.iloc[-1] * (kelly_pct*2/current_risk):,.0f}"
                        ],
                        "Risk Assessment": [
                            "✅ Very Safe",
                            "✅ Conservative", 
                            "⚠️ Optimal Growth",
                            "🔴 High Risk"
                        ]
                    }
                    
                    scenarios_df = pd.DataFrame(scenarios_data)
                    st.dataframe(scenarios_df, use_container_width=True, hide_index=True)
                    
                    st.info("**Note:** These are linear approximations. Actual results with higher leverage would include:\n"
                           "- Exponentially higher drawdowns\n"
                           "- Increased position concentration risk\n"
                           "- Higher probability of margin calls or stop-outs\n"
                           "- Greater psychological stress during losing streaks")
            
        elif 'summary' in data:
            # Fallback to combined summary if no trades
            cols = st.columns(5)
            summary = data['summary']
            
            with cols[0]:
                st.metric("Total Return", f"{summary.get('total_return_pct', 0):.1f}%")
            with cols[1]:
                st.metric("CAGR", f"{summary.get('cagr_pct', 0):.1f}%")
            with cols[2]:
                st.metric("Sharpe Ratio", f"{summary.get('sharpe_ratio', 0):.2f}")
            with cols[3]:
                st.metric("Max Drawdown", f"{summary.get('max_dd_pct', 0):.2f}%")
            with cols[4]:
                st.metric("Win Rate", f"{summary.get('win_rate_pct', 0):.1f}%")
            
            st.markdown("---")
            
            cols2 = st.columns(4)
            with cols2[0]:
                st.metric("Total Trades", f"{int(summary.get('num_trades', 0)):,}")
            with cols2[1]:
                st.metric("Profit Factor", f"{summary.get('profit_factor', 0):.2f}")
            with cols2[2]:
                if 'alpha_beta' in data:
                    alpha = data['alpha_beta'].get('alpha_pct', 0)
                    st.metric("Alpha vs SPY", f"{alpha:.1f}%")
            with cols2[3]:
                if 'alpha_beta' in data:
                    beta = data['alpha_beta'].get('beta', 0)
                    st.metric("Beta vs SPY", f"{beta:.2f}")
        
        # Equity curve from filtered trades
        if 'trades' in data and len(filtered_trades) > 0:
            st.markdown("---")
            
            # Build equity curve from filtered trades with scaling
            df_sorted = filtered_trades.sort_values('date').reset_index(drop=True)
            scaled_cumulative_pnl = (df_sorted['net_pnl'] * equity_multiplier).cumsum()
            df_sorted['equity'] = target_equity + scaled_cumulative_pnl
            
            # Group by date for daily equity
            daily_equity = df_sorted.groupby('date').agg({
                'equity': 'last',
                'net_pnl': lambda x: (x * equity_multiplier).sum()
            }).reset_index()
            
            st.plotly_chart(plot_equity_curve(daily_equity), use_container_width=True)
            
            # Recent daily P&L
            st.markdown("---")
            st.plotly_chart(plot_daily_pnl_bars(daily_equity), use_container_width=True)
        elif 'daily' in data:
            # Fallback to combined daily if no filters
            st.markdown("---")
            st.plotly_chart(plot_equity_curve(data['daily']), use_container_width=True)
        
            st.markdown("---")
            st.plotly_chart(plot_daily_pnl_bars(data['daily']), use_container_width=True)
    
    with tab2:
        st.header("Trade Log")
        
        if 'trades' in data:
            df = filtered_trades.copy()
            
            # Display stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Filtered Trades", f"{len(df):,}")
            with col2:
                total_pnl = df['net_pnl'].sum()
                st.metric("Total P&L", f"${total_pnl:,.0f}", 
                         delta=None,
                         delta_color="normal" if total_pnl >= 0 else "inverse")
            with col3:
                wins = (df['net_pnl'] > 0).sum()
                wr = wins / len(df) * 100 if len(df) > 0 else 0
                st.metric("Win Rate", f"{wr:.1f}%")
            with col4:
                if 'r_mult' in df.columns:
                    avg_r = df['r_mult'].mean()
                    st.metric("Avg R", f"{avg_r:.2f}")
                else:
                    st.metric("Avg R", "N/A")
            
            st.markdown("---")
            
            # Trade selection for detailed view
            st.subheader("🔍 Select Trade to Inspect")
            
            # Create trade labels for selection
            df_with_labels = df.copy()
            df_with_labels['trade_label'] = df_with_labels.apply(
                lambda row: f"{row['date'].strftime('%Y-%m-%d')} | {row['symbol']} | "
                           f"{'LONG' if row['direction'] == 1 else 'SHORT'} | "
                           f"${row['net_pnl']:.0f}",
                axis=1
            )
            
            # Sort by date descending (most recent first)
            df_with_labels = df_with_labels.sort_values('date', ascending=False).reset_index(drop=True)
            
            # Selection dropdown
            selected_label = st.selectbox(
                "Choose a trade to view on TradingView:",
                options=df_with_labels['trade_label'].tolist(),
                index=0 if len(df_with_labels) > 0 else None
            )
            
            if selected_label:
                # Get selected trade
                selected_idx = df_with_labels[df_with_labels['trade_label'] == selected_label].index[0]
                selected_trade = df_with_labels.iloc[selected_idx]
                
                # Show trade details
                show_trade_detail(selected_trade)
            
            st.markdown("---")
            st.subheader("📋 All Trades")
            
            # Format and display full trade list
            display_df = df.copy()
            display_df['net_pnl'] = display_df['net_pnl'].apply(lambda x: f"${x:,.2f}")
            
            # Select columns that exist
            display_cols = ['date', 'symbol', 'direction', 'entry_price', 
                          'exit_price', 'shares', 'net_pnl']
            if 'r_mult' in display_df.columns:
                display_df['r_mult'] = display_df['r_mult'].apply(lambda x: f"{x:.2f}R")
                display_cols.append('r_mult')
            
            st.dataframe(
                display_df[display_cols],
                use_container_width=True,
                height=600
            )
    
    with tab3:
        st.header("🔍 Trade Audit")
        
        if 'trades' in data:
            trades = data['trades']
            
            st.markdown("### Batch Audit by Date")
            st.info("Review trades systematically by date and RVOL rank")
            
            # Get unique dates sorted descending
            available_dates = sorted(trades['date'].unique(), reverse=True)
            
            # Date selector
            selected_audit_date = st.selectbox(
                "Select Date to Audit",
                options=available_dates,
                format_func=lambda x: pd.to_datetime(x).strftime('%Y-%m-%d (%A)')
            )
            
            # Filter trades for selected date
            date_trades = trades[trades['date'] == selected_audit_date].copy()
            
            # Show date summary
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Trades", len(date_trades))
            with col2:
                total_pnl = date_trades['net_pnl'].sum()
                st.metric("Day P&L", f"${total_pnl:,.2f}", 
                         delta=f"{(total_pnl/1000)*100:.2f}%" if total_pnl != 0 else None)
            with col3:
                winners = (date_trades['net_pnl'] > 0).sum()
                st.metric("Winners", f"{winners}/{len(date_trades)}")
            with col4:
                if 'rvol_rank' in date_trades.columns:
                    top_50 = (date_trades['rvol_rank'] <= 50).sum()
                    st.metric("Top 50 RVOL", top_50)
            
            st.markdown("---")
            
            # RVOL filter
            rvol_filter = st.selectbox(
                "Filter by RVOL Rank",
                options=["All Trades", "Top 50", "Top 20", "Top 10", "51-100", ">100"],
                index=1  # Default to Top 50
            )
            
            # Apply RVOL filter
            if rvol_filter == "Top 50":
                filtered_audit = date_trades[date_trades['rvol_rank'] <= 50]
            elif rvol_filter == "Top 20":
                filtered_audit = date_trades[date_trades['rvol_rank'] <= 20]
            elif rvol_filter == "Top 10":
                filtered_audit = date_trades[date_trades['rvol_rank'] <= 10]
            elif rvol_filter == "51-100":
                filtered_audit = date_trades[(date_trades['rvol_rank'] > 50) & (date_trades['rvol_rank'] <= 100)]
            elif rvol_filter == ">100":
                filtered_audit = date_trades[date_trades['rvol_rank'] > 100]
            else:
                filtered_audit = date_trades
            
            st.markdown(f"### {rvol_filter}: {len(filtered_audit)} trades")
            
            # Sort by RVOL rank
            filtered_audit = filtered_audit.sort_values('rvol_rank')
            
            # Display table with key audit columns
            audit_cols = ['symbol', 'direction', 'rvol_rank', 'or_rvol_14', 
                         'entry_time', 'entry_price', 'exit_time', 'exit_price', 
                         'net_pnl', 'or_high', 'or_low', 'atr_14']
            
            # Format the display
            display_audit = filtered_audit[audit_cols].copy()
            display_audit['direction'] = display_audit['direction'].map({1: '🟢 Long', -1: '🔴 Short'})
            display_audit['net_pnl'] = display_audit['net_pnl'].apply(lambda x: f"${x:,.2f}")
            display_audit['entry_price'] = display_audit['entry_price'].apply(lambda x: f"${x:.2f}")
            display_audit['exit_price'] = display_audit['exit_price'].apply(lambda x: f"${x:.2f}")
            display_audit['or_high'] = display_audit['or_high'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "-")
            display_audit['or_low'] = display_audit['or_low'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "-")
            display_audit['atr_14'] = display_audit['atr_14'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "-")
            display_audit['or_rvol_14'] = display_audit['or_rvol_14'].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "-")
            display_audit['entry_time'] = display_audit['entry_time'].apply(lambda x: pd.to_datetime(x).strftime('%H:%M') if pd.notna(x) else "-")
            display_audit['exit_time'] = display_audit['exit_time'].apply(lambda x: pd.to_datetime(x).strftime('%H:%M') if pd.notna(x) else "-")
            
            # Rename columns for display
            display_audit.columns = ['Symbol', 'Dir', 'RVOL Rank', 'RVOL', 
                                 'Entry Time', 'Entry $', 'Exit Time', 'Exit $',
                                 'P&L', 'OR High', 'OR Low', 'ATR']
            
            st.dataframe(display_audit, use_container_width=True, height=600)
            
            # Quick inspection
            st.markdown("---")
            st.markdown("### Quick Inspect")
            
            # Select trade for quick chart view
            if len(filtered_audit) > 0:
                selected_idx = st.selectbox(
                    "Select trade to inspect",
                    options=range(len(filtered_audit)),
                    format_func=lambda i: f"{filtered_audit.iloc[i]['symbol']} - Rank #{int(filtered_audit.iloc[i]['rvol_rank'])} - ${filtered_audit.iloc[i]['net_pnl']:.2f}"
                )
                
                if st.button("Show Chart", key="audit_chart"):
                    selected_audit_trade = filtered_audit.iloc[selected_idx]
                    show_trade_detail(selected_audit_trade)
        
        else:
            st.warning("No trade data available")
    
    with tab4:
        st.header("💰 Equity Curve Inspection")
        
        if 'trades' in data:
            trades = data['trades'].copy()
            
            st.markdown("### Trade-by-Trade Equity Movement")
            st.info("Linear view of equity progression per trade")
            
            # Sort by date and entry time to get chronological order
            trades['datetime'] = pd.to_datetime(trades['entry_time'], utc=True).dt.tz_localize(None)
            trades = trades.sort_values('datetime').reset_index(drop=True)
            
            # Calculate cumulative equity
            trades['cumulative_pnl'] = trades['net_pnl'].cumsum()
            trades['equity'] = 1000 + trades['cumulative_pnl']  # Starting from $1000
            trades['trade_number'] = range(1, len(trades) + 1)
            
            # Navigation controls
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                # Trade range selector
                total_trades = len(trades)
                trade_range = st.slider(
                    "Trade Range",
                    min_value=1,
                    max_value=total_trades,
                    value=(1, min(100, total_trades)),
                    step=1
                )
            
            with col2:
                # Quick jump to periods
                period_options = {
                    "First 100": (1, min(100, total_trades)),
                    "Last 100": (max(1, total_trades - 99), total_trades),
                    "Middle": (total_trades // 2 - 50, total_trades // 2 + 50),
                    "All": (1, total_trades)
                }
                quick_jump = st.selectbox("Quick Jump", list(period_options.keys()), index=0)
            
            with col3:
                if st.button("Jump"):
                    trade_range = period_options[quick_jump]
                    st.rerun()
            
            # Filter to selected range
            start_idx = trade_range[0] - 1
            end_idx = trade_range[1]
            filtered_equity = trades.iloc[start_idx:end_idx].copy()
            
            # Summary metrics for range
            st.markdown("---")
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Trades in Range", len(filtered_equity))
            with col2:
                range_pnl = filtered_equity['net_pnl'].sum()
                st.metric("Range P&L", f"${range_pnl:,.2f}")
            with col3:
                start_eq = filtered_equity.iloc[0]['equity'] - filtered_equity.iloc[0]['net_pnl']
                end_eq = filtered_equity.iloc[-1]['equity']
                st.metric("Start Equity", f"${start_eq:,.2f}")
            with col4:
                st.metric("End Equity", f"${end_eq:,.2f}")
            with col5:
                equity_change = ((end_eq - start_eq) / start_eq) * 100
                st.metric("Change", f"{equity_change:.2f}%")
            
            st.markdown("---")
            
            # Equity curve chart
            fig = go.Figure()
            
            # Add equity line
            fig.add_trace(go.Scatter(
                x=filtered_equity['trade_number'],
                y=filtered_equity['equity'],
                mode='lines+markers',
                name='Equity',
                line=dict(color='#26a69a', width=2),
                marker=dict(size=4),
                hovertemplate='<b>Trade #%{x}</b><br>' +
                              'Equity: $%{y:,.2f}<br>' +
                              '<extra></extra>'
            ))
            
            # Add winning trades markers
            winners = filtered_equity[filtered_equity['net_pnl'] > 0]
            fig.add_trace(go.Scatter(
                x=winners['trade_number'],
                y=winners['equity'],
                mode='markers',
                name='Winners',
                marker=dict(color='green', size=8, symbol='triangle-up'),
                hovertemplate='<b>Trade #%{x}</b><br>' +
                              'Symbol: %{customdata[0]}<br>' +
                              'P&L: $%{customdata[1]:,.2f}<br>' +
                              'Equity: $%{y:,.2f}<br>' +
                              '<extra></extra>',
                customdata=winners[['symbol', 'net_pnl']].values
            ))
            
            # Add losing trades markers
            losers = filtered_equity[filtered_equity['net_pnl'] < 0]
            fig.add_trace(go.Scatter(
                x=losers['trade_number'],
                y=losers['equity'],
                mode='markers',
                name='Losers',
                marker=dict(color='red', size=8, symbol='triangle-down'),
                hovertemplate='<b>Trade #%{x}</b><br>' +
                              'Symbol: %{customdata[0]}<br>' +
                              'P&L: $%{customdata[1]:,.2f}<br>' +
                              'Equity: $%{y:,.2f}<br>' +
                              '<extra></extra>',
                customdata=losers[['symbol', 'net_pnl']].values
            ))
            
            fig.update_layout(
                title=f"Equity Curve: Trades {trade_range[0]} to {trade_range[1]}",
                xaxis_title="Trade Number",
                yaxis_title="Equity ($)",
                template='plotly_dark',
                height=500,
                hovermode='x unified',
                showlegend=True
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Trade detail table
            st.markdown("---")
            st.markdown("### Trade Details")
            
            # Format display
            display_equity = filtered_equity[['trade_number', 'datetime', 'symbol', 'direction', 
                                             'entry_price', 'exit_price', 'net_pnl', 
                                             'cumulative_pnl', 'equity', 'rvol_rank']].copy()
            
            display_equity['datetime'] = display_equity['datetime'].dt.strftime('%Y-%m-%d %H:%M')
            display_equity['direction'] = display_equity['direction'].map({1: '🟢 Long', -1: '🔴 Short'})
            display_equity['entry_price'] = display_equity['entry_price'].apply(lambda x: f"${x:.2f}")
            display_equity['exit_price'] = display_equity['exit_price'].apply(lambda x: f"${x:.2f}")
            display_equity['net_pnl'] = display_equity['net_pnl'].apply(lambda x: f"${x:,.2f}")
            display_equity['cumulative_pnl'] = display_equity['cumulative_pnl'].apply(lambda x: f"${x:,.2f}")
            display_equity['equity'] = display_equity['equity'].apply(lambda x: f"${x:,.2f}")
            
            display_equity.columns = ['Trade #', 'DateTime', 'Symbol', 'Dir', 
                                     'Entry', 'Exit', 'P&L', 'Cum P&L', 'Equity', 'RVOL Rank']
            
            st.dataframe(display_equity, use_container_width=True, height=400)
            
            # Quick inspect selected trade
            st.markdown("---")
            st.markdown("### Inspect Trade")
            
            trade_to_inspect = st.number_input(
                "Enter Trade Number to Inspect",
                min_value=int(filtered_equity['trade_number'].min()),
                max_value=int(filtered_equity['trade_number'].max()),
                value=int(filtered_equity['trade_number'].min())
            )
            
            if st.button("Show Trade Chart", key="equity_chart"):
                selected_eq_trade = trades[trades['trade_number'] == trade_to_inspect].iloc[0]
                show_trade_detail(selected_eq_trade)
        
        else:
            st.warning("No trade data available")
    
    with tab5:
        st.header("Symbol Leaderboard")
        
        if 'leaderboard' in data:
            df = data['leaderboard'].copy()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🏆 Top 10 Winners")
                top10 = df.head(10).copy()
                top10['total_pnl'] = top10['total_pnl'].apply(lambda x: f"${x:,.0f}")
                top10['win_rate'] = top10['win_rate'].apply(lambda x: f"{x*100:.1f}%")
                st.dataframe(top10[['symbol', 'total_pnl', 'n_trades', 'win_rate']], 
                            use_container_width=True, height=400)
            
            with col2:
                st.subheader("📉 Bottom 10 Losers")
                bottom10 = df.tail(10).copy()
                bottom10['total_pnl'] = bottom10['total_pnl'].apply(lambda x: f"${x:,.0f}")
                bottom10['win_rate'] = bottom10['win_rate'].apply(lambda x: f"{x*100:.1f}%")
                st.dataframe(bottom10[['symbol', 'total_pnl', 'n_trades', 'win_rate']], 
                            use_container_width=True, height=400)
        
        # RVOL bucket analysis
        if 'rvol_buckets' in data:
            st.markdown("---")
            st.subheader("RVOL Bucket Performance")
            
            df = data['rvol_buckets'].copy()
            df['total_pnl'] = df['total_pnl'].apply(lambda x: f"${x:,.0f}")
            df['avg_pnl'] = df['avg_pnl'].apply(lambda x: f"${x:,.0f}")
            df['win_rate'] = df['win_rate'].apply(lambda x: f"{x:.1f}%")
            
            st.dataframe(df, use_container_width=True)
    
    with tab6:
        st.header("Detailed Analysis")
        
        if 'daily' in data:
            daily_df = data['daily']
            
            # Monthly returns heatmap
            st.subheader("Monthly Returns Heatmap")
            
            monthly = daily_df.copy()
            monthly['year'] = monthly['date'].dt.year
            monthly['month'] = monthly['date'].dt.month
            
            monthly_pnl = monthly.groupby(['year', 'month'])['net_pnl'].sum().reset_index()
            pivot = monthly_pnl.pivot(index='year', columns='month', values='net_pnl')
            
            fig = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
                y=pivot.index,
                colorscale='RdYlGn',
                text=pivot.values,
                texttemplate='%{text:,.0f}',
                textfont={"size": 10},
                hovertemplate='Year: %{y}<br>Month: %{x}<br>P&L: $%{z:,.0f}<extra></extra>'
            ))
            
            fig.update_layout(
                title="Monthly P&L Heatmap",
                xaxis_title="Month",
                yaxis_title="Year",
                template='plotly_dark',
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        # Distribution of R-multiples
        if 'trades' in data and 'r_mult' in trades_df.columns:
            st.markdown("---")
            st.subheader("R-Multiple Distribution")
            
            fig = go.Figure(data=[
                go.Histogram(
                    x=trades_df['r_mult'],
                    nbinsx=50,
                    marker_color='#26a69a',
                    opacity=0.75
                )
            ])
            
            fig.update_layout(
                title="Distribution of R-Multiples",
                xaxis_title="R-Multiple",
                yaxis_title="Frequency",
                template='plotly_dark',
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
