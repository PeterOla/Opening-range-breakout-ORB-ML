"""
Analytics API endpoints for historical backtest analysis.

Provides endpoints for:
- Performance metrics (weekly, monthly, yearly, all-time)
- Drawdown analysis
- Win/loss streaks
- Equity curve data
- Summary statistics
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import date, datetime, timedelta
from typing import Optional, Literal
from pydantic import BaseModel
from sqlalchemy import text
from db.database import engine

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ============ RESPONSE MODELS ============

class PeriodPerformance(BaseModel):
    period: str  # e.g., "2024-W01", "2024-01", "2024"
    total_trades: int
    trades_entered: int
    winners: int
    losers: int
    win_rate: float
    total_pnl_pct: float
    total_pnl_dollars: float  # 1x
    total_pnl_leveraged: float  # 2x
    best_day_pnl: Optional[float]
    worst_day_pnl: Optional[float]
    trading_days: int


class DrawdownMetrics(BaseModel):
    current_drawdown_pct: float
    max_drawdown_pct: float
    max_drawdown_start: Optional[str]
    max_drawdown_end: Optional[str]
    drawdown_days: int  # Days in current drawdown
    recovery_days: Optional[int]  # Days to recover from max DD


class StreakMetrics(BaseModel):
    current_win_streak: int
    max_win_streak: int
    max_win_streak_pnl: float
    current_loss_streak: int
    max_loss_streak: int
    max_loss_streak_pnl: float


class SummaryStats(BaseModel):
    # Overall performance
    total_trading_days: int
    total_trades: int
    trades_entered: int
    win_rate: float
    total_pnl_pct: float
    total_pnl_dollars: float
    total_pnl_leveraged: float
    
    # Averages
    avg_winner_pct: float
    avg_loser_pct: float
    avg_trade_pnl: float
    profit_factor: float
    
    # Best/Worst
    best_trade_pct: float
    best_trade_ticker: str
    best_trade_date: str
    worst_trade_pct: float
    worst_trade_ticker: str
    worst_trade_date: str
    best_day_pnl: float
    best_day_date: str
    worst_day_pnl: float
    worst_day_date: str
    
    # Risk metrics
    max_drawdown_pct: float
    sharpe_ratio: Optional[float]
    win_loss_ratio: float


class EquityCurvePoint(BaseModel):
    date: str
    equity: float
    daily_pnl: float
    cumulative_pnl: float
    drawdown_pct: float


# ============ HELPER FUNCTIONS ============

def get_date_range(
    start: Optional[str], 
    end: Optional[str], 
    period: Optional[str]
) -> tuple[date, date]:
    """Parse date range from parameters."""
    end_date = date.today() if not end else datetime.strptime(end, "%Y-%m-%d").date()
    
    if start:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
    elif period:
        if period == "1m":
            start_date = end_date - timedelta(days=30)
        elif period == "3m":
            start_date = end_date - timedelta(days=90)
        elif period == "6m":
            start_date = end_date - timedelta(days=180)
        elif period == "1y":
            start_date = end_date - timedelta(days=365)
        elif period == "ytd":
            start_date = date(end_date.year, 1, 1)
        elif period == "all":
            start_date = date(2021, 1, 1)
        else:
            start_date = date(2021, 1, 1)
    else:
        start_date = date(2021, 1, 1)
    
    return start_date, end_date


# ============ ENDPOINTS ============

@router.get("/performance")
def get_performance(
    granularity: Literal["daily", "weekly", "monthly", "yearly"] = "monthly",
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    period: Optional[str] = Query(None, description="Preset period: 1m, 3m, 6m, 1y, ytd, all"),
    backtest_run_id: Optional[int] = Query(None, description="Specific backtest run ID"),
) -> list[PeriodPerformance]:
    """
    Get performance metrics aggregated by period.
    
    Returns P&L, win rate, and trade counts for each period.
    """
    start_date, end_date = get_date_range(start, end, period)
    
    # Build GROUP BY clause based on granularity
    if granularity == "daily":
        period_expr = "DATE(trade_date)"
    elif granularity == "weekly":
        period_expr = "TO_CHAR(trade_date, 'IYYY-\"W\"IW')"
    elif granularity == "monthly":
        period_expr = "TO_CHAR(trade_date, 'YYYY-MM')"
    else:  # yearly
        period_expr = "TO_CHAR(trade_date, 'YYYY')"
    
    # Build filter for backtest_run_id
    run_filter = "backtest_run_id IS NULL" if backtest_run_id is None else f"backtest_run_id = {backtest_run_id}"
    
    query = f"""
        SELECT 
            {period_expr} as period,
            COUNT(*) as total_trades,
            SUM(CASE WHEN exit_reason != 'NO_ENTRY' THEN 1 ELSE 0 END) as trades_entered,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as winners,
            SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losers,
            SUM(COALESCE(pnl_pct, 0)) as total_pnl_pct,
            SUM(COALESCE(base_dollar_pnl, 0)) as total_pnl_dollars,
            SUM(COALESCE(dollar_pnl, 0)) as total_pnl_leveraged,
            MAX(base_dollar_pnl) as best_day_pnl,
            MIN(base_dollar_pnl) as worst_day_pnl,
            COUNT(DISTINCT trade_date) as trading_days
        FROM simulated_trades
        WHERE trade_date >= :start 
          AND trade_date <= :end
          AND {run_filter}
        GROUP BY {period_expr}
        ORDER BY {period_expr}
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {"start": start_date, "end": end_date})
        rows = result.fetchall()
    
    return [
        PeriodPerformance(
            period=row[0],
            total_trades=row[1],
            trades_entered=row[2] or 0,
            winners=row[3] or 0,
            losers=row[4] or 0,
            win_rate=round((row[3] or 0) / max(1, row[2] or 1) * 100, 1),
            total_pnl_pct=round(row[5] or 0, 2),
            total_pnl_dollars=round(row[6] or 0, 2),
            total_pnl_leveraged=round(row[7] or 0, 2),
            best_day_pnl=round(row[8], 2) if row[8] else None,
            worst_day_pnl=round(row[9], 2) if row[9] else None,
            trading_days=row[10] or 0,
        )
        for row in rows
    ]


@router.get("/drawdown")
def get_drawdown(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    backtest_run_id: Optional[int] = None,
) -> DrawdownMetrics:
    """
    Get drawdown analysis.
    
    Returns current drawdown, max drawdown, and streak info.
    """
    start_date, end_date = get_date_range(start, end, period)
    run_filter = "backtest_run_id IS NULL" if backtest_run_id is None else f"backtest_run_id = {backtest_run_id}"
    
    # Get daily P&L for equity curve
    query = f"""
        SELECT 
            trade_date::date,
            SUM(COALESCE(base_dollar_pnl, 0)) as daily_pnl
        FROM simulated_trades
        WHERE trade_date >= :start 
          AND trade_date <= :end
          AND {run_filter}
          AND exit_reason != 'NO_ENTRY'
        GROUP BY trade_date::date
        ORDER BY trade_date::date
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {"start": start_date, "end": end_date})
        rows = result.fetchall()
    
    if not rows:
        return DrawdownMetrics(
            current_drawdown_pct=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_start=None,
            max_drawdown_end=None,
            drawdown_days=0,
            recovery_days=None,
        )
    
    # Calculate drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_start = None
    max_dd_end = None
    current_dd_start = None
    
    for row in rows:
        cumulative += row[1]
        if cumulative > peak:
            peak = cumulative
            current_dd_start = None
        
        dd = (peak - cumulative) / max(peak, 1000) * 100 if peak > 0 else 0
        
        if dd > 0 and current_dd_start is None:
            current_dd_start = row[0]
        
        if dd > max_dd:
            max_dd = dd
            max_dd_start = current_dd_start
            max_dd_end = row[0]
    
    current_dd = (peak - cumulative) / max(peak, 1000) * 100 if peak > 0 else 0
    dd_days = (date.today() - current_dd_start).days if current_dd_start else 0
    
    return DrawdownMetrics(
        current_drawdown_pct=round(current_dd, 2),
        max_drawdown_pct=round(max_dd, 2),
        max_drawdown_start=str(max_dd_start) if max_dd_start else None,
        max_drawdown_end=str(max_dd_end) if max_dd_end else None,
        drawdown_days=dd_days,
        recovery_days=None,  # TODO: Calculate recovery
    )


@router.get("/streaks")
def get_streaks(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    backtest_run_id: Optional[int] = None,
) -> StreakMetrics:
    """
    Get win/loss streak analysis.
    
    Streaks are computed at the daily level (winning vs losing days).
    """
    start_date, end_date = get_date_range(start, end, period)
    run_filter = "backtest_run_id IS NULL" if backtest_run_id is None else f"backtest_run_id = {backtest_run_id}"
    
    # Get daily P&L
    query = f"""
        SELECT 
            trade_date::date,
            SUM(COALESCE(base_dollar_pnl, 0)) as daily_pnl
        FROM simulated_trades
        WHERE trade_date >= :start 
          AND trade_date <= :end
          AND {run_filter}
          AND exit_reason != 'NO_ENTRY'
        GROUP BY trade_date::date
        ORDER BY trade_date::date
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {"start": start_date, "end": end_date})
        rows = result.fetchall()
    
    if not rows:
        return StreakMetrics(
            current_win_streak=0, max_win_streak=0, max_win_streak_pnl=0.0,
            current_loss_streak=0, max_loss_streak=0, max_loss_streak_pnl=0.0,
        )
    
    # Calculate streaks
    current_win = 0
    current_loss = 0
    max_win = 0
    max_loss = 0
    max_win_pnl = 0.0
    max_loss_pnl = 0.0
    current_win_pnl = 0.0
    current_loss_pnl = 0.0
    
    for row in rows:
        pnl = row[1]
        if pnl > 0:
            current_win += 1
            current_win_pnl += pnl
            if current_win > max_win:
                max_win = current_win
                max_win_pnl = current_win_pnl
            current_loss = 0
            current_loss_pnl = 0.0
        elif pnl < 0:
            current_loss += 1
            current_loss_pnl += pnl
            if current_loss > max_loss:
                max_loss = current_loss
                max_loss_pnl = current_loss_pnl
            current_win = 0
            current_win_pnl = 0.0
    
    return StreakMetrics(
        current_win_streak=current_win,
        max_win_streak=max_win,
        max_win_streak_pnl=round(max_win_pnl, 2),
        current_loss_streak=current_loss,
        max_loss_streak=max_loss,
        max_loss_streak_pnl=round(max_loss_pnl, 2),
    )


@router.get("/summary")
def get_summary(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    backtest_run_id: Optional[int] = None,
) -> SummaryStats:
    """
    Get comprehensive summary statistics.
    """
    start_date, end_date = get_date_range(start, end, period)
    run_filter = "backtest_run_id IS NULL" if backtest_run_id is None else f"backtest_run_id = {backtest_run_id}"
    
    query = f"""
        WITH trades AS (
            SELECT 
                trade_date,
                ticker,
                pnl_pct,
                base_dollar_pnl,
                dollar_pnl,
                exit_reason
            FROM simulated_trades
            WHERE trade_date >= :start 
              AND trade_date <= :end
              AND {run_filter}
        ),
        entered AS (
            SELECT * FROM trades WHERE exit_reason != 'NO_ENTRY'
        ),
        daily_pnl AS (
            SELECT 
                trade_date::date,
                SUM(base_dollar_pnl) as day_pnl
            FROM entered
            GROUP BY trade_date::date
        )
        SELECT 
            (SELECT COUNT(DISTINCT trade_date) FROM trades) as trading_days,
            (SELECT COUNT(*) FROM trades) as total_trades,
            (SELECT COUNT(*) FROM entered) as trades_entered,
            (SELECT COUNT(*) FROM entered WHERE pnl_pct > 0) as winners,
            (SELECT COUNT(*) FROM entered WHERE pnl_pct < 0) as losers,
            (SELECT SUM(pnl_pct) FROM entered) as total_pnl_pct,
            (SELECT SUM(base_dollar_pnl) FROM entered) as total_pnl_dollars,
            (SELECT SUM(dollar_pnl) FROM entered) as total_pnl_leveraged,
            (SELECT AVG(pnl_pct) FROM entered WHERE pnl_pct > 0) as avg_winner_pct,
            (SELECT AVG(pnl_pct) FROM entered WHERE pnl_pct < 0) as avg_loser_pct,
            (SELECT AVG(base_dollar_pnl) FROM entered) as avg_trade_pnl,
            (SELECT SUM(base_dollar_pnl) FROM entered WHERE pnl_pct > 0) as gross_profit,
            (SELECT ABS(SUM(base_dollar_pnl)) FROM entered WHERE pnl_pct < 0) as gross_loss,
            (SELECT MAX(pnl_pct) FROM entered) as best_trade_pct,
            (SELECT ticker FROM entered ORDER BY pnl_pct DESC LIMIT 1) as best_trade_ticker,
            (SELECT trade_date FROM entered ORDER BY pnl_pct DESC LIMIT 1) as best_trade_date,
            (SELECT MIN(pnl_pct) FROM entered) as worst_trade_pct,
            (SELECT ticker FROM entered ORDER BY pnl_pct ASC LIMIT 1) as worst_trade_ticker,
            (SELECT trade_date FROM entered ORDER BY pnl_pct ASC LIMIT 1) as worst_trade_date,
            (SELECT MAX(day_pnl) FROM daily_pnl) as best_day_pnl,
            (SELECT trade_date FROM daily_pnl ORDER BY day_pnl DESC LIMIT 1) as best_day_date,
            (SELECT MIN(day_pnl) FROM daily_pnl) as worst_day_pnl,
            (SELECT trade_date FROM daily_pnl ORDER BY day_pnl ASC LIMIT 1) as worst_day_date
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {"start": start_date, "end": end_date})
        row = result.fetchone()
    
    if not row or row[0] == 0:
        raise HTTPException(status_code=404, detail="No trade data found for the specified period")
    
    winners = row[3] or 0
    losers = row[4] or 0
    total_entered = row[2] or 1
    gross_profit = row[11] or 0
    gross_loss = row[12] or 1
    avg_winner = row[8] or 0
    avg_loser = abs(row[9]) if row[9] else 1
    
    return SummaryStats(
        total_trading_days=row[0],
        total_trades=row[1],
        trades_entered=row[2] or 0,
        win_rate=round(winners / max(1, total_entered) * 100, 1),
        total_pnl_pct=round(row[5] or 0, 2),
        total_pnl_dollars=round(row[6] or 0, 2),
        total_pnl_leveraged=round(row[7] or 0, 2),
        avg_winner_pct=round(row[8] or 0, 2),
        avg_loser_pct=round(row[9] or 0, 2),
        avg_trade_pnl=round(row[10] or 0, 2),
        profit_factor=round(gross_profit / max(1, gross_loss), 2),
        best_trade_pct=round(row[13] or 0, 2),
        best_trade_ticker=row[14] or "",
        best_trade_date=str(row[15]) if row[15] else "",
        worst_trade_pct=round(row[16] or 0, 2),
        worst_trade_ticker=row[17] or "",
        worst_trade_date=str(row[18]) if row[18] else "",
        best_day_pnl=round(row[19] or 0, 2),
        best_day_date=str(row[20]) if row[20] else "",
        worst_day_pnl=round(row[21] or 0, 2),
        worst_day_date=str(row[22]) if row[22] else "",
        max_drawdown_pct=0.0,  # TODO: Calculate from drawdown endpoint
        sharpe_ratio=None,  # TODO: Calculate
        win_loss_ratio=round(avg_winner / max(0.01, avg_loser), 2),
    )


@router.get("/equity-curve")
def get_equity_curve(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
    backtest_run_id: Optional[int] = None,
    starting_capital: float = Query(1000.0),
) -> list[EquityCurvePoint]:
    """
    Get equity curve data for charting.
    
    Returns daily equity values and drawdown.
    """
    start_date, end_date = get_date_range(start, end, period)
    run_filter = "backtest_run_id IS NULL" if backtest_run_id is None else f"backtest_run_id = {backtest_run_id}"
    
    query = f"""
        SELECT 
            trade_date::date as date,
            SUM(COALESCE(base_dollar_pnl, 0)) as daily_pnl
        FROM simulated_trades
        WHERE trade_date >= :start 
          AND trade_date <= :end
          AND {run_filter}
          AND exit_reason != 'NO_ENTRY'
        GROUP BY trade_date::date
        ORDER BY trade_date::date
    """
    
    with engine.connect() as conn:
        result = conn.execute(text(query), {"start": start_date, "end": end_date})
        rows = result.fetchall()
    
    curve = []
    cumulative = 0.0
    peak = starting_capital
    
    for row in rows:
        cumulative += row[1]
        equity = starting_capital + cumulative
        
        if equity > peak:
            peak = equity
        
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        
        curve.append(EquityCurvePoint(
            date=str(row[0]),
            equity=round(equity, 2),
            daily_pnl=round(row[1], 2),
            cumulative_pnl=round(cumulative, 2),
            drawdown_pct=round(dd, 2),
        ))
    
    return curve
