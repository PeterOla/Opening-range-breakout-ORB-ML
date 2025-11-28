'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { 
  ArrowUpRight, 
  ArrowDownRight, 
  RefreshCw, 
  Clock, 
  TrendingUp, 
  TrendingDown,
  Calendar,
  Activity,
  Target,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Database,
  Download,
  Calculator,
  CheckCircle2,
} from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Candidate {
  symbol: string
  rank: number
  direction: number
  direction_label: string
  or_high: number
  or_low: number
  or_open?: number
  or_close?: number
  or_volume?: number
  atr: number
  avg_volume?: number
  rvol: number
  entry_price: number
  stop_price: number
  current_price?: number  // Live mode only
  unrealized_pnl?: number  // Live mode only
  unrealized_pnl_pct?: number  // Live mode only
  // Historical/Live P&L fields
  entered?: boolean
  entry_price_actual?: number
  entry_time?: string
  exit_price?: number
  exit_time?: string
  exit_reason?: string
  pnl_pct?: number
  dollar_pnl?: number
  base_dollar_pnl?: number
  leverage?: number
  is_winner?: boolean
  day_change_pct?: number
}

interface ModeResponse {
  status: string
  mode: 'live' | 'historical_today' | 'historical_previous' | 'premarket'
  target_date: string
  display_date: string
  description: string
  is_live: boolean
  show_pnl: boolean
  premarket?: boolean
  or_time?: string
  live_disabled_reason?: string
  upgrade_url?: string
}

interface HistoricalResponse {
  status: string
  date: string
  message?: string
  candidates: Candidate[]
  summary?: {
    total_candidates: number
    trades_entered: number
    winners: number
    losers: number
    win_rate: number
    total_pnl_pct: number
    avg_pnl_pct: number
    total_dollar_pnl: number
    base_dollar_pnl: number  // P&L at 1x leverage
    avg_leverage: number
  }
}

interface LiveResponse {
  status: string
  timestamp: string
  count: number
  candidates: Candidate[]
  summary?: {
    total_candidates: number
    trades_entered: number
    winners: number
    losers: number
    win_rate: number
    total_pnl_pct: number
    avg_pnl_pct: number
    total_dollar_pnl: number
    base_dollar_pnl: number
    avg_leverage: number
  }
}

interface ProgressState {
  step: number
  message: string
  percent: number
  detail: string
}

// Custom hook for streaming historical data with progress
function useStreamingHistorical(
  date: string | null,
  enabled: boolean
): {
  data: HistoricalResponse | null
  error: Error | null
  isLoading: boolean
  progress: ProgressState | null
  refetch: (forceRefresh?: boolean) => void
} {
  const [data, setData] = useState<HistoricalResponse | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState<ProgressState | null>(null)
  const [fetchKey, setFetchKey] = useState(0)
  const [forceRefresh, setForceRefresh] = useState(false)
  
  const refetch = useCallback((force: boolean = false) => {
    setData(null)
    setForceRefresh(force)
    setFetchKey(k => k + 1)
  }, [])
  
  useEffect(() => {
    if (!date || !enabled) {
      setData(null)
      setProgress(null)
      return
    }
    
    let cancelled = false
    setIsLoading(true)
    setError(null)
    setProgress({ step: 0, message: 'Connecting...', percent: 0, detail: '' })
    
    // Connect directly to backend for SSE to avoid Next.js proxy buffering
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    const forceParam = forceRefresh ? '?force_refresh=true' : ''
    const eventSource = new EventSource(`${backendUrl}/api/scanner/historical/${date}/stream${forceParam}`)
    
    // Reset force refresh flag after use
    setForceRefresh(false)
    
    eventSource.addEventListener('progress', (event) => {
      if (cancelled) return
      try {
        const progressData = JSON.parse(event.data)
        setProgress(progressData)
      } catch (e) {
        console.error('Failed to parse progress:', e)
      }
    })
    
    eventSource.addEventListener('result', (event) => {
      if (cancelled) return
      try {
        const resultData = JSON.parse(event.data)
        setData(resultData)
        setIsLoading(false)
        setProgress(null)
        eventSource.close()
      } catch (e) {
        console.error('Failed to parse result:', e)
        setError(new Error('Failed to parse result'))
        setIsLoading(false)
        eventSource.close()
      }
    })
    
    eventSource.addEventListener('error', (event) => {
      if (cancelled) return
      // Check if it's an actual error event with data
      const errorEvent = event as MessageEvent
      if (errorEvent.data) {
        try {
          const errorData = JSON.parse(errorEvent.data)
          setError(new Error(errorData.message || 'Unknown error'))
        } catch {
          setError(new Error('Connection failed'))
        }
      } else {
        // SSE connection error
        setError(new Error('Connection lost'))
      }
      setIsLoading(false)
      setProgress(null)
      eventSource.close()
    })
    
    eventSource.onerror = () => {
      if (cancelled) return
      // Only set error if we haven't received data
      if (!data) {
        setError(new Error('Connection failed'))
        setIsLoading(false)
        setProgress(null)
      }
      eventSource.close()
    }
    
    return () => {
      cancelled = true
      eventSource.close()
    }
  }, [date, enabled, fetchKey])
  
  return { data, error, isLoading, progress, refetch }
}

export function Top20Results() {
  const [customDate, setCustomDate] = useState<string | null>(null)
  
  // First, get the current mode
  const { data: modeData, error: modeError, isLoading: modeLoading } = useSWR<ModeResponse>(
    '/api/scanner/mode',
    fetcher,
    { refreshInterval: 60000 }
  )
  
  // Use custom date if set, otherwise use mode's target date
  const targetDate = customDate || modeData?.target_date
  
  // Determine mode flags
  const isLiveMode = modeData?.is_live && !customDate
  const isPremarketMode = modeData?.mode === 'premarket' && !customDate
  
  // Only use historical streaming when:
  // 1. Mode has loaded (modeData exists)
  // 2. Not in live mode
  // 3. Not in premarket mode
  // 4. Either using custom date or mode says use historical
  const useHistorical = Boolean(modeData && !isLiveMode && !isPremarketMode)
  
  // Use streaming for historical data (but not for live or premarket)
  const { 
    data: streamData, 
    error: streamError, 
    isLoading: streamLoading,
    progress,
    refetch: streamRefetch 
  } = useStreamingHistorical(
    useHistorical ? (targetDate || null) : null,
    useHistorical && !!targetDate
  )
  
  // Use SWR for live data
  const { 
    data: liveData, 
    error: liveError, 
    isLoading: liveLoading,
    mutate: liveMutate 
  } = useSWR<LiveResponse>(
    isLiveMode ? '/api/scanner/today/live' : null,
    fetcher,
    { refreshInterval: 10000 }  // Refresh every 10 seconds for live P&L
  )
  
  // Auto-run scanner if live mode returns empty candidates
  const [autoRunning, setAutoRunning] = useState(false)
  const [autoRunAttempted, setAutoRunAttempted] = useState(false)
  
  useEffect(() => {
    // Auto-run scanner if:
    // 1. We're in live mode
    // 2. Data loaded but has 0 candidates
    // 3. Haven't already attempted auto-run
    // 4. Not currently loading or running
    if (
      isLiveMode && 
      liveData && 
      liveData.candidates?.length === 0 && 
      !autoRunAttempted && 
      !autoRunning &&
      !liveLoading
    ) {
      setAutoRunning(true)
      setAutoRunAttempted(true)
      
      // Run the scanner to fetch fresh data
      fetch('/api/scanner/run')
        .then(res => res.json())
        .then(result => {
          if (result.status === 'success' && result.count > 0) {
            // Refresh the today endpoint to get saved data
            liveMutate()
          }
        })
        .catch(err => {
          console.error('Auto-run scanner failed:', err)
        })
        .finally(() => {
          setAutoRunning(false)
        })
    }
  }, [isLiveMode, liveData, autoRunAttempted, autoRunning, liveLoading, liveMutate])
  
  // Use SWR for pre-market data
  const {
    data: premarketData,
    error: premarketError,
    isLoading: premarketLoading,
    mutate: premarketMutate
  } = useSWR(
    isPremarketMode ? '/api/scanner/premarket' : null,
    fetcher,
    { refreshInterval: 30000 }
  )
  
  // Combine data sources
  const scanData = isLiveMode ? liveData : (isPremarketMode ? premarketData : streamData)
  const scanError = isLiveMode ? liveError : (isPremarketMode ? premarketError : streamError)
  const scanLoading = isLiveMode ? (liveLoading || autoRunning) : (isPremarketMode ? premarketLoading : streamLoading)
  
  // Regular refresh (uses cache)
  const mutate = useCallback(() => {
    if (isLiveMode) {
      liveMutate()
    } else if (isPremarketMode) {
      premarketMutate()
    } else {
      streamRefetch(false)
    }
  }, [isLiveMode, isPremarketMode, liveMutate, premarketMutate, streamRefetch])
  
  // Force refresh (bypasses cache)
  const forceRefresh = useCallback(() => {
    if (isLiveMode) {
      // For live mode, run the scanner again
      fetch('/api/scanner/run').then(() => liveMutate())
    } else if (isPremarketMode) {
      premarketMutate()
    } else {
      streamRefetch(true) // Pass true to force refresh
    }
  }, [isLiveMode, isPremarketMode, liveMutate, premarketMutate, streamRefetch])
  
  // Date navigation helpers
  const today = new Date().toISOString().split('T')[0]
  
  const navigateDate = (days: number) => {
    const current = customDate || modeData?.target_date || today
    const date = new Date(current)
    date.setDate(date.getDate() + days)
    // Skip weekends
    while (date.getDay() === 0 || date.getDay() === 6) {
      date.setDate(date.getDate() + (days > 0 ? 1 : -1))
    }
    const newDate = date.toISOString().split('T')[0]
    // Don't allow future dates
    if (newDate > today) {
      return
    }
    setCustomDate(newDate)
  }
  
  // Check if we can navigate forward (not into the future)
  const currentDisplayDate = customDate || modeData?.target_date || today
  const canNavigateForward = currentDisplayDate < today
  
  const resetToToday = () => {
    setCustomDate(null)
  }
  
  if (modeLoading) {
    return <LoadingState step="mode" progress={null} />
  }
  
  if (modeError) {
    return <ErrorState message="Failed to connect to backend server" onRetry={() => window.location.reload()} />
  }
  
  const mode = modeData!
  const candidates = scanData?.candidates || []
  // Get summary from either historical or live response
  const summary = (scanData as HistoricalResponse)?.summary || (liveData as LiveResponse)?.summary
  const scanStatus = (scanData as HistoricalResponse)?.status
  // Show P&L for historical mode OR when live mode has summary data
  const showPnl = customDate ? true : !!(mode.show_pnl || (isLiveMode && !!summary))
  const displayDate = customDate 
    ? new Date(customDate).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    : mode.display_date
  
  // Check if it's a holiday or no data scenario
  const isNoData = scanStatus === 'no_candidates' || scanStatus === 'no_universe'
  const errorMessage = (scanData as HistoricalResponse)?.message
  
  // Pre-market specific data
  const premarketInfo = isPremarketMode ? premarketData : null
  
  return (
    <div className="space-y-4">
      {/* Mode Banner */}
      <ModeBanner 
        mode={mode} 
        customDate={customDate}
        displayDate={displayDate}
        onRefresh={() => mutate()} 
        onForceRefresh={() => forceRefresh()}
        onPrevDay={() => navigateDate(-1)}
        onNextDay={() => navigateDate(1)}
        onReset={resetToToday}
        canNavigateForward={canNavigateForward}
      />
      
      {/* Pre-market countdown info */}
      {isPremarketMode && premarketInfo && (
        <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Clock className="h-6 w-6 text-orange-400" />
              <div>
                <h3 className="font-semibold text-orange-300">
                  ⏰ ORB Forms in {premarketInfo.time_until_or}
                </h3>
                <p className="text-sm text-orange-400/80">
                  {premarketInfo.universe_count} candidates in universe. Ranked by avg volume (RVOL available after 9:35 ET).
                </p>
              </div>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-orange-300">{premarketInfo.or_time}</div>
              <div className="text-xs text-orange-400/70">Opening Range End</div>
            </div>
          </div>
        </div>
      )}
      
      {/* Live disabled warning */}
      {mode.live_disabled_reason && !customDate && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
          <div className="flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-yellow-400" />
            <div>
              <p className="text-sm text-yellow-300">{mode.live_disabled_reason}</p>
              {mode.upgrade_url && (
                <a 
                  href={mode.upgrade_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-xs text-yellow-400 underline hover:text-yellow-300"
                >
                  Upgrade to Alpaca Algo Trader Plus →
                </a>
              )}
            </div>
          </div>
        </div>
      )}
      
      {/* P&L Summary (historical only) */}
      {showPnl && summary && (
        <PnLSummary summary={summary} />
      )}
      
      {/* Candidates Table */}
      <div className="bg-card rounded-lg border border-border">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">
              {isPremarketMode ? `Universe Candidates (${candidates.length})` : `Top 20 Candidates (${candidates.length})`}
            </h2>
            <p className="text-xs text-muted-foreground">
              {isPremarketMode ? 'Ranked by avg volume • RVOL pending' : displayDate}
            </p>
          </div>
          <button
            onClick={() => mutate()}
            className="p-2 hover:bg-secondary rounded-md transition-colors"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        
        {scanLoading ? (
          <LoadingState step="data" date={displayDate} progress={progress} />
        ) : scanError ? (
          <ErrorState 
            message={`Failed to fetch data: ${scanError.message || 'Unknown error'}`} 
            onRetry={() => mutate()}
          />
        ) : isNoData ? (
          <NoDataState 
            message={errorMessage || 'No data available'} 
            date={displayDate}
            onRetry={() => mutate()}
          />
        ) : candidates.length === 0 ? (
          <EmptyState mode={mode} onRetry={() => mutate()} />
        ) : isPremarketMode ? (
          <PremarketTableContent candidates={candidates} />
        ) : (
          <CandidatesTableContent 
            candidates={candidates} 
            showPnl={showPnl}
            targetDate={targetDate || new Date().toISOString().split('T')[0]}
          />
        )}
      </div>
    </div>
  )
}

function ModeBanner({ 
  mode, 
  customDate,
  displayDate,
  onRefresh,
  onForceRefresh,
  onPrevDay,
  onNextDay,
  onReset,
  canNavigateForward,
}: { 
  mode: ModeResponse
  customDate: string | null
  displayDate: string
  onRefresh: () => void
  onForceRefresh: () => void
  onPrevDay: () => void
  onNextDay: () => void
  onReset: () => void
  canNavigateForward: boolean
}) {
  const getBannerStyle = () => {
    if (customDate) return 'bg-purple-500/10 border-purple-500/30 text-purple-400'
    switch (mode.mode) {
      case 'live':
        return 'bg-green-500/10 border-green-500/30 text-green-400'
      case 'premarket':
        return 'bg-orange-500/10 border-orange-500/30 text-orange-400'
      case 'historical_today':
        return 'bg-blue-500/10 border-blue-500/30 text-blue-400'
      case 'historical_previous':
        return 'bg-amber-500/10 border-amber-500/30 text-amber-400'
      default:
        return 'bg-secondary'
    }
  }
  
  const getIcon = () => {
    if (customDate) return <Calendar className="h-5 w-5" />
    switch (mode.mode) {
      case 'live':
        return <Activity className="h-5 w-5" />
      case 'premarket':
        return <Clock className="h-5 w-5" />
      case 'historical_today':
        return <Target className="h-5 w-5" />
      case 'historical_previous':
        return <Calendar className="h-5 w-5" />
      default:
        return <Clock className="h-5 w-5" />
    }
  }
  
  const getModeLabel = () => {
    if (customDate) return '📜 Historical'
    if (mode.mode === 'live') return '🟢 LIVE'
    if (mode.mode === 'premarket') return '🌅 PRE-MARKET'
    return mode.mode.replace('_', ' ')
  }
  
  return (
    <div className={`rounded-lg border p-4 ${getBannerStyle()}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getIcon()}
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold capitalize">
                {getModeLabel()}
              </span>
              {mode.is_live && !customDate && (
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                </span>
              )}
            </div>
            <p className="text-sm opacity-80">
              {customDate ? 'Viewing historical data' : mode.description}
            </p>
          </div>
        </div>
        
        {/* Date Navigation */}
        <div className="flex items-center gap-2">
          <button
            onClick={onPrevDay}
            className="p-2 hover:bg-white/10 rounded-md transition-colors"
            title="Previous day"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          
          <div className="text-center min-w-[180px]">
            <div className="text-lg font-bold">{displayDate}</div>
            {customDate && (
              <button 
                onClick={onReset}
                className="text-xs underline opacity-70 hover:opacity-100"
              >
                Reset to today
              </button>
            )}
          </div>
          
          <button
            onClick={onNextDay}
            disabled={!canNavigateForward}
            className={`p-2 rounded-md transition-colors ${
              canNavigateForward 
                ? 'hover:bg-white/10' 
                : 'opacity-30 cursor-not-allowed'
            }`}
            title={canNavigateForward ? "Next day" : "Cannot go beyond today"}
          >
            <ChevronRight className="h-5 w-5" />
          </button>
          
          {/* Force Refresh Button */}
          <button
            onClick={onForceRefresh}
            className="p-2 hover:bg-white/10 rounded-md transition-colors ml-2"
            title="Force refresh (bypass cache)"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

function PnLSummary({ summary }: { summary: HistoricalResponse['summary'] }) {
  if (!summary) return null
  
  const isProfit = summary.total_pnl_pct >= 0
  
  // Use backend-calculated dollar P&L (capped at 2x leverage)
  const dollarPnl = summary.total_dollar_pnl || 0
  const baseDollarPnl = summary.base_dollar_pnl || 0  // P&L at 1x leverage
  const avgLeverage = summary.avg_leverage || 0
  
  // Estimate slippage cost: ~0.05% per trade (entry + exit)
  const slippagePct = 0.05
  const tradesEntered = summary.trades_entered
  
  // Slippage per trade ≈ 0.05% × avg position size
  // With avg leverage of ~2x on $1000 = $2000 position, 0.05% = $2 per trade
  const avgPositionSize = 1000 * avgLeverage
  const slippagePerTrade = (slippagePct / 100) * avgPositionSize * 2 // entry + exit
  const totalSlippage = tradesEntered * slippagePerTrade
  
  const netDollarPnl = dollarPnl - totalSlippage
  const netBasePnl = baseDollarPnl - (totalSlippage / avgLeverage)  // Slippage at 1x
  const netIsProfit = netDollarPnl >= 0
  
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
      <div className="bg-card rounded-lg border border-border p-4">
        <div className="text-sm text-muted-foreground">Trades Entered</div>
        <div className="text-2xl font-bold">
          {summary.trades_entered} / {summary.total_candidates}
        </div>
      </div>
      
      <div className="bg-card rounded-lg border border-border p-4">
        <div className="text-sm text-muted-foreground">Win Rate</div>
        <div className="text-2xl font-bold">
          {summary.win_rate}%
        </div>
      </div>
      
      <div className="bg-card rounded-lg border border-border p-4">
        <div className="text-sm text-muted-foreground">Winners</div>
        <div className="text-2xl font-bold text-success flex items-center gap-1">
          <TrendingUp className="h-5 w-5" />
          {summary.winners}
        </div>
      </div>
      
      <div className="bg-card rounded-lg border border-border p-4">
        <div className="text-sm text-muted-foreground">Losers</div>
        <div className="text-2xl font-bold text-destructive flex items-center gap-1">
          <TrendingDown className="h-5 w-5" />
          {summary.losers}
        </div>
      </div>
      
      <div className={`rounded-lg border p-4 ${
        isProfit 
          ? 'bg-success/10 border-success/30' 
          : 'bg-destructive/10 border-destructive/30'
      }`}>
        <div className="text-sm text-muted-foreground">Total P&L %</div>
        <div className={`text-2xl font-bold ${isProfit ? 'text-success' : 'text-destructive'}`}>
          {isProfit ? '+' : ''}{summary.total_pnl_pct}%
        </div>
        <div className="text-xs text-muted-foreground">
          Avg: {summary.avg_pnl_pct > 0 ? '+' : ''}{summary.avg_pnl_pct}%
        </div>
      </div>
      
      {/* Dollar P&L Card */}
      <div className={`rounded-lg border p-4 ${
        netIsProfit 
          ? 'bg-success/10 border-success/30' 
          : 'bg-destructive/10 border-destructive/30'
      }`}>
        <div className="text-sm text-muted-foreground">$1K @ 1% Risk</div>
        <div className={`text-2xl font-bold ${netIsProfit ? 'text-success' : 'text-destructive'}`}>
          {netBasePnl >= 0 ? '+' : ''}${netBasePnl.toFixed(2)}
        </div>
        <div className="text-xs text-muted-foreground">
          {netDollarPnl >= 0 ? '+' : ''}${netDollarPnl.toFixed(2)} @ {avgLeverage.toFixed(1)}x lev
        </div>
      </div>
    </div>
  )
}

function CandidatesTableContent({ 
  candidates, 
  showPnl,
  targetDate
}: { 
  candidates: Candidate[]
  showPnl: boolean
  targetDate: string
}) {
  const router = useRouter()
  
  const handleRowClick = (symbol: string) => {
    router.push(`/scanner/trade/${symbol}?date=${targetDate}`)
  }
  
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border text-left text-sm text-muted-foreground">
            <th className="px-4 py-3 font-medium">Rank</th>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium">Direction</th>
            <th className="px-4 py-3 font-medium text-right">RVOL</th>
            <th className="px-4 py-3 font-medium text-right">Entry</th>
            <th className="px-4 py-3 font-medium text-right">Stop</th>
            {showPnl && (
              <>
                <th className="px-4 py-3 font-medium text-center">Status</th>
                <th className="px-4 py-3 font-medium text-right">Exit</th>
                <th className="px-4 py-3 font-medium text-right">P&L %</th>
                <th className="px-4 py-3 font-medium text-right">P&L (1x)</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const isLong = c.direction === 1
            const entered = c.entered
            // For live mode, determine winner from unrealized P&L; for historical, use is_winner
            const isWinner = c.unrealized_pnl_pct !== undefined 
              ? c.unrealized_pnl_pct > 0 
              : c.is_winner
            const dayChange = c.day_change_pct
            
            return (
              <tr 
                key={c.symbol}
                onClick={() => handleRowClick(c.symbol)}
                className={`border-b border-border transition-colors cursor-pointer ${
                  showPnl 
                    ? entered 
                      ? isWinner 
                        ? 'bg-success/5 hover:bg-success/10' 
                        : 'bg-destructive/5 hover:bg-destructive/10'
                      : 'opacity-50 hover:bg-secondary/50'
                    : 'hover:bg-secondary/50'
                }`}
              >
                <td className="px-4 py-3 font-medium text-muted-foreground">
                  #{c.rank}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{c.symbol}</span>
                    {showPnl && dayChange !== null && dayChange !== undefined && (
                      <span className={`
                        inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium
                        ${dayChange > 0 
                          ? 'bg-success/20 text-success' 
                          : dayChange < 0 
                            ? 'bg-destructive/20 text-destructive' 
                            : 'bg-secondary text-muted-foreground'
                        }
                      `}>
                        {dayChange > 0 ? '+' : ''}{dayChange}%
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`
                    inline-flex items-center gap-1 text-sm font-medium
                    ${isLong ? 'text-success' : 'text-destructive'}
                  `}>
                    {isLong ? (
                      <ArrowUpRight className="h-4 w-4" />
                    ) : (
                      <ArrowDownRight className="h-4 w-4" />
                    )}
                    {c.direction_label}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-medium text-orange-500">
                  {(c.rvol * 100).toFixed(0)}%
                </td>
                <td className="px-4 py-3 text-right font-medium text-blue-500">
                  ${c.entry_price?.toFixed(2)}
                </td>
                <td className="px-4 py-3 text-right text-destructive">
                  ${c.stop_price?.toFixed(2)}
                </td>
                {showPnl && (
                  <>
                    <td className="px-4 py-3 text-center">
                      {entered ? (
                        c.current_price ? (
                          // Live mode - position is open
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-500/20 text-amber-400">
                            Open
                          </span>
                        ) : (
                          // Historical mode - show exit reason
                          <span className={`
                            inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium
                            ${c.exit_reason === 'STOP_LOSS' 
                              ? 'bg-destructive/20 text-destructive' 
                              : 'bg-blue-500/20 text-blue-400'
                            }
                          `}>
                            {c.exit_reason === 'STOP_LOSS' ? 'Stopped' : 'EOD'}
                          </span>
                        )
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          No Entry
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {entered ? (
                        <div>
                          <div className="font-medium">
                            ${(c.current_price ?? c.exit_price)?.toFixed(2)}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {c.current_price ? 'Live' : c.exit_time}
                          </div>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </td>
                    {/* P&L % Column */}
                    <td className={`px-4 py-3 text-right ${
                      !entered 
                        ? 'text-muted-foreground' 
                        : isWinner 
                          ? 'text-success' 
                          : 'text-destructive'
                    }`}>
                      {entered ? (() => {
                        const pnlPct = c.unrealized_pnl_pct ?? c.pnl_pct ?? 0
                        const isPositive = pnlPct > 0
                        return (
                          <span className="font-bold">
                            {isPositive ? '+' : ''}{pnlPct.toFixed(2)}%
                          </span>
                        )
                      })() : '-'}
                    </td>
                    {/* P&L (1x) $ Column */}
                    <td className={`px-4 py-3 text-right ${
                      !entered 
                        ? 'text-muted-foreground' 
                        : isWinner 
                          ? 'text-success' 
                          : 'text-destructive'
                    }`}>
                      {entered ? (() => {
                        const basePnl = c.base_dollar_pnl ?? 0  // 1x leverage
                        const leveragedPnl = c.unrealized_pnl ?? c.dollar_pnl ?? 0  // actual leverage
                        const leverage = c.leverage ?? 2.0
                        const isPositive = (c.unrealized_pnl_pct ?? c.pnl_pct ?? 0) > 0
                        return (
                          <div>
                            <div className="font-bold">
                              {isPositive ? '+' : ''}${basePnl.toFixed(2)}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {isPositive ? '+' : ''}${leveragedPnl.toFixed(2)} @ {leverage.toFixed(1)}x
                            </div>
                          </div>
                        )
                      })() : '-'}
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

interface PremarketCandidate {
  symbol: string
  rank: number
  atr: number
  avg_volume: number
  last_close: number
  rvol: number | null
  status: string
}

function PremarketTableContent({ candidates }: { candidates: PremarketCandidate[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border text-left text-sm text-muted-foreground">
            <th className="px-4 py-3 font-medium">Rank</th>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium text-right">Last Close</th>
            <th className="px-4 py-3 font-medium text-right">ATR</th>
            <th className="px-4 py-3 font-medium text-right">Avg Volume</th>
            <th className="px-4 py-3 font-medium text-center">RVOL</th>
            <th className="px-4 py-3 font-medium text-center">Status</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr 
              key={c.symbol} 
              className="border-b border-border hover:bg-secondary/50 transition-colors"
            >
              <td className="px-4 py-3 font-medium text-muted-foreground">
                #{c.rank}
              </td>
              <td className="px-4 py-3 font-bold">
                {c.symbol}
              </td>
              <td className="px-4 py-3 text-right font-medium">
                ${c.last_close?.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-right text-blue-400">
                ${c.atr?.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-right text-muted-foreground">
                {(c.avg_volume / 1_000_000).toFixed(1)}M
              </td>
              <td className="px-4 py-3 text-center">
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-500/20 text-orange-400">
                  <Clock className="h-3 w-3 mr-1" />
                  Pending
                </span>
              </td>
              <td className="px-4 py-3 text-center">
                <span className="text-xs text-muted-foreground">
                  Awaiting ORB
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LoadingState({ 
  step, 
  date,
  progress 
}: { 
  step: 'mode' | 'data'
  date?: string
  progress: ProgressState | null 
}) {
  const steps = [
    { id: 1, label: 'Checking database cache', icon: Database },
    { id: 2, label: 'Getting qualified universe', icon: Target },
    { id: 3, label: 'Fetching 5-min bars from Alpaca', icon: Download },
    { id: 4, label: 'Computing RVOL & ranking', icon: Calculator },
    { id: 5, label: 'Simulating trades', icon: TrendingUp },
    { id: 6, label: 'Saving to database', icon: Database },
  ]
  
  if (step === 'mode') {
    return (
      <div className="bg-card rounded-lg border border-border p-8">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground">Connecting to server...</p>
        </div>
      </div>
    )
  }
  
  const currentStep = progress?.step || 0
  const percent = progress?.percent || 0
  
  return (
    <div className="p-8">
      <div className="flex flex-col items-center gap-6">
        {/* Header with progress % */}
        <div className="text-center">
          <div className="flex items-center justify-center gap-3 mb-2">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="text-lg font-medium">Loading {date}</span>
          </div>
          <div className="text-3xl font-bold text-primary">{percent}%</div>
          {progress?.message && (
            <p className="text-sm text-muted-foreground mt-1">{progress.message}</p>
          )}
        </div>
        
        {/* Progress bar */}
        <div className="w-full max-w-md">
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div 
              className="h-full bg-primary transition-all duration-300 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
        
        {/* Steps list */}
        <div className="w-full max-w-md space-y-2">
          {steps.map((s) => {
            const isComplete = currentStep > s.id
            const isActive = currentStep === s.id
            const isPending = currentStep < s.id
            
            return (
              <div 
                key={s.id}
                className={`flex items-center gap-3 text-sm p-2 rounded-md transition-all ${
                  isActive ? 'bg-primary/10' : ''
                }`}
              >
                {isComplete ? (
                  <CheckCircle2 className="h-5 w-5 text-success flex-shrink-0" />
                ) : isActive ? (
                  <Loader2 className="h-5 w-5 text-primary animate-spin flex-shrink-0" />
                ) : (
                  <s.icon className={`h-5 w-5 flex-shrink-0 ${isPending ? 'text-muted-foreground/40' : 'text-muted-foreground'}`} />
                )}
                <span className={`flex-1 ${
                  isComplete ? 'text-success' : 
                  isActive ? 'text-foreground font-medium' : 
                  'text-muted-foreground/60'
                }`}>
                  {s.label}
                </span>
                {isActive && progress?.detail && (
                  <span className="text-xs text-muted-foreground">
                    {progress.detail}
                  </span>
                )}
              </div>
            )
          })}
        </div>
        
        {/* Footer note */}
        <p className="text-xs text-muted-foreground mt-2">
          {currentStep <= 1 
            ? 'Checking cache... cached data loads instantly!'
            : currentStep === 3 
              ? 'First load for a date takes ~30s (fetching from Alpaca)'
              : ''
          }
        </p>
      </div>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-8">
      <div className="flex flex-col items-center gap-4">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <div className="text-center">
          <p className="text-destructive font-medium">Something went wrong</p>
          <p className="text-sm text-muted-foreground mt-1">{message}</p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="flex items-center gap-2 px-4 py-2 bg-destructive/20 hover:bg-destructive/30 text-destructive rounded-md transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        )}
      </div>
    </div>
  )
}

function NoDataState({ 
  message, 
  date,
  onRetry 
}: { 
  message: string
  date: string
  onRetry?: () => void 
}) {
  // Check if it looks like a holiday (keywords in message)
  const isHoliday = message.toLowerCase().includes('holiday') || 
                    message.toLowerCase().includes('no candidates') ||
                    date.includes('Thursday') // Thanksgiving check
  
  return (
    <div className="p-8">
      <div className="flex flex-col items-center gap-4">
        <Calendar className="h-8 w-8 text-amber-500 opacity-70" />
        <div className="text-center">
          <p className="font-medium text-amber-500">No trading data</p>
          <p className="text-sm text-muted-foreground mt-1">{message}</p>
          {isHoliday && (
            <p className="text-xs text-muted-foreground mt-2">
              🦃 This appears to be a market holiday
            </p>
          )}
        </div>
        {!isHoliday && onRetry && (
          <button
            onClick={onRetry}
            className="flex items-center gap-2 px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 text-amber-500 rounded-md transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        )}
        <p className="text-xs text-muted-foreground mt-2">
          Use ← → to navigate to a different date
        </p>
      </div>
    </div>
  )
}

function EmptyState({ mode, onRetry }: { mode: ModeResponse; onRetry?: () => void }) {
  const [isRunning, setIsRunning] = useState(false)
  
  const handleRunScanner = async () => {
    setIsRunning(true)
    try {
      const res = await fetch('/api/scanner/run')
      const result = await res.json()
      if (result.status === 'success') {
        onRetry?.()
      }
    } catch (err) {
      console.error('Run scanner failed:', err)
    } finally {
      setIsRunning(false)
    }
  }
  
  return (
    <div className="p-8 text-center text-muted-foreground">
      <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
      {mode.is_live ? (
        <>
          <p>No candidates found for today.</p>
          <p className="text-sm mt-1">
            Click below to scan for ORB candidates now.
          </p>
          <button
            onClick={handleRunScanner}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 mt-4 mx-auto bg-primary hover:bg-primary/90 text-primary-foreground rounded-md transition-colors disabled:opacity-50"
          >
            {isRunning ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Running Scanner...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4" />
                Run Scanner
              </>
            )}
          </button>
        </>
      ) : (
        <>
          <p>No data available for {mode.display_date}.</p>
          <p className="text-sm mt-1">
            This may be a market holiday or the data hasn&apos;t been fetched yet.
          </p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-2 px-4 py-2 mt-4 mx-auto bg-secondary hover:bg-secondary/80 rounded-md transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Retry
            </button>
          )}
        </>
      )}
    </div>
  )
}
