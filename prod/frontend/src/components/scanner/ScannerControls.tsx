'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { RefreshCw, Database, Calendar, Play, Loader2, CheckCircle, XCircle, Clock } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface SyncResult {
  status: string
  days_processed?: number
  bars_synced?: number
  unique_symbols?: number
  metrics_updated?: number
  total_fetched?: number
  inserted?: number
  updated?: number
  error?: string
}

interface ScheduledJob {
  id: string
  name: string
  next_run: string | null
  trigger: string
}

type SyncStatus = 'idle' | 'loading' | 'success' | 'error'

export function ScannerControls() {
  const [tickerSyncStatus, setTickerSyncStatus] = useState<SyncStatus>('idle')
  const [dailySyncStatus, setDailySyncStatus] = useState<SyncStatus>('idle')
  const [scanStatus, setScanStatus] = useState<SyncStatus>('idle')
  
  const [tickerResult, setTickerResult] = useState<SyncResult | null>(null)
  const [dailyResult, setDailyResult] = useState<SyncResult | null>(null)
  const [scanResult, setScanResult] = useState<any>(null)
  
  const [lookbackDays, setLookbackDays] = useState(14)
  
  // Fetch scheduler status
  const { data: schedulerData } = useSWR<{ status: string; jobs: ScheduledJob[] }>(
    '/api/system/scheduler',
    fetcher,
    { refreshInterval: 60000 }
  )
  
  // Find the nightly sync job
  const nightlySyncJob = schedulerData?.jobs?.find(j => j.id === 'nightly_data_sync')
  const nextSyncTime = nightlySyncJob?.next_run 
    ? new Date(nightlySyncJob.next_run).toLocaleString()
    : null
  
  // Sync ticker universe from Polygon
  const syncTickers = async () => {
    setTickerSyncStatus('loading')
    setTickerResult(null)
    
    try {
      const res = await fetch('/api/scanner/sync-tickers', { method: 'POST' })
      const data = await res.json()
      
      setTickerResult(data)
      setTickerSyncStatus(data.status === 'success' ? 'success' : 'error')
    } catch (err) {
      setTickerSyncStatus('error')
      setTickerResult({ status: 'error', error: String(err) })
    }
  }
  
  // Sync daily bars (14-day data)
  const syncDailyBars = async () => {
    setDailySyncStatus('loading')
    setDailyResult(null)
    
    try {
      const res = await fetch(`/api/scanner/sync-daily?lookback_days=${lookbackDays}`, { 
        method: 'POST' 
      })
      const data = await res.json()
      
      setDailyResult(data)
      setDailySyncStatus(data.status === 'success' ? 'success' : 'error')
    } catch (err) {
      setDailySyncStatus('error')
      setDailyResult({ status: 'error', error: String(err) })
    }
  }
  
  // Run ORB scanner
  const runScanner = async () => {
    setScanStatus('loading')
    setScanResult(null)
    
    try {
      const res = await fetch('/api/scanner/run')
      const data = await res.json()
      
      setScanResult(data)
      setScanStatus(data.status === 'success' ? 'success' : 'error')
    } catch (err) {
      setScanStatus('error')
      setScanResult({ status: 'error', error: String(err) })
    }
  }
  
  const StatusIcon = ({ status }: { status: SyncStatus }) => {
    switch (status) {
      case 'loading':
        return <Loader2 className="h-4 w-4 animate-spin" />
      case 'success':
        return <CheckCircle className="h-4 w-4 text-success" />
      case 'error':
        return <XCircle className="h-4 w-4 text-destructive" />
      default:
        return null
    }
  }
  
  return (
    <div className="bg-card rounded-lg border border-border">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Data Sync & Scanner</h2>
            <p className="text-sm text-muted-foreground">
              Step 1: Sync tickers → Step 2: Fetch daily data → Step 3: Run scanner
            </p>
          </div>
          {nextSyncTime && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground bg-secondary/50 px-3 py-1.5 rounded-md">
              <Clock className="h-4 w-4" />
              <span>Auto-sync: {nextSyncTime}</span>
            </div>
          )}
        </div>
      </div>
      
      <div className="p-4 space-y-4">
        {/* Step 1: Sync Tickers */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-secondary/30 rounded-lg">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-blue-500" />
              <span className="font-medium">1. Sync Ticker Universe</span>
              <StatusIcon status={tickerSyncStatus} />
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Fetch all NYSE/NASDAQ stocks from Polygon (~2-5 min, run once)
            </p>
            {tickerResult && tickerSyncStatus === 'success' && (
              <p className="text-xs text-success mt-1">
                ✓ {tickerResult.total_fetched?.toLocaleString()} tickers fetched, 
                {tickerResult.inserted?.toLocaleString()} new, 
                {tickerResult.updated?.toLocaleString()} updated
              </p>
            )}
            {tickerResult?.error && (
              <p className="text-xs text-destructive mt-1">
                Error: {tickerResult.error}
              </p>
            )}
          </div>
          <button
            onClick={syncTickers}
            disabled={tickerSyncStatus === 'loading'}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md flex items-center gap-2 transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${tickerSyncStatus === 'loading' ? 'animate-spin' : ''}`} />
            Sync Tickers
          </button>
        </div>
        
        {/* Step 2: Sync Daily Bars */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-secondary/30 rounded-lg">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-green-500" />
              <span className="font-medium">2. Fetch Daily Data</span>
              <StatusIcon status={dailySyncStatus} />
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Fetch {lookbackDays}-day OHLCV for all stocks, compute ATR(14) & avg volume
            </p>
            {dailyResult && dailySyncStatus === 'success' && (
              <p className="text-xs text-success mt-1">
                ✓ {dailyResult.days_processed} days processed, 
                {dailyResult.bars_synced?.toLocaleString()} bars synced, 
                {dailyResult.metrics_updated?.toLocaleString()} symbols with metrics
              </p>
            )}
            {dailyResult?.error && (
              <p className="text-xs text-destructive mt-1">
                Error: {dailyResult.error}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <select
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value))}
              className="px-2 py-1.5 bg-secondary border border-border rounded text-sm"
              title="Lookback days for daily data sync"
              aria-label="Lookback days"
            >
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={21}>21 days</option>
              <option value={30}>30 days</option>
            </select>
            <button
              onClick={syncDailyBars}
              disabled={dailySyncStatus === 'loading'}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md flex items-center gap-2 transition-colors"
            >
              <RefreshCw className={`h-4 w-4 ${dailySyncStatus === 'loading' ? 'animate-spin' : ''}`} />
              Fetch Data
            </button>
          </div>
        </div>
        
        {/* Step 3: Run Scanner */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-secondary/30 rounded-lg">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Play className="h-4 w-4 text-purple-500" />
              <span className="font-medium">3. Run ORB Scanner</span>
              <StatusIcon status={scanStatus} />
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Scan for ORB breakout candidates (requires daily data + market open)
            </p>
            {scanResult && scanStatus === 'success' && (
              <p className="text-xs text-success mt-1">
                ✓ {scanResult.count || scanResult.candidates_top_n} candidates found
              </p>
            )}
            {scanResult?.error && (
              <p className="text-xs text-destructive mt-1">
                Error: {scanResult.error}
              </p>
            )}
          </div>
          <button
            onClick={runScanner}
            disabled={scanStatus === 'loading'}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md flex items-center gap-2 transition-colors"
          >
            <Play className={`h-4 w-4 ${scanStatus === 'loading' ? 'animate-pulse' : ''}`} />
            Run Scan
          </button>
        </div>
      </div>
    </div>
  )
}
