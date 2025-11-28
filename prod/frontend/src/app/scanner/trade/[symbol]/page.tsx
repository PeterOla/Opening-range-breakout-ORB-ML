'use client'

import { useParams, useSearchParams, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import useSWR from 'swr'
import { 
  ArrowLeft, 
  ArrowUpRight, 
  ArrowDownRight,
  TrendingUp,
  TrendingDown,
  Clock,
  Target,
  AlertCircle,
  DollarSign,
  Percent,
  Activity
} from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface TradeData {
  symbol: string
  rank: number
  direction: number
  direction_label: string
  or_high: number
  or_low: number
  or_open?: number
  or_close?: number
  atr: number
  rvol: number
  entry_price: number
  stop_price: number
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

declare global {
  interface Window {
    TradingView: any
  }
}

export default function TradePage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const containerRef = useRef<HTMLDivElement>(null)
  const [widgetReady, setWidgetReady] = useState(false)
  
  const symbol = params.symbol as string
  const date = searchParams.get('date') || new Date().toISOString().split('T')[0]
  
  // Fetch trade data - use the correct endpoint format
  const { data, error, isLoading } = useSWR<{ candidates: TradeData[] }>(
    `/api/scanner/historical/${date}`,
    fetcher
  )
  
  // Debug logging
  console.log('Trade page data:', { symbol, date, data, error, isLoading })
  
  const trade = data?.candidates?.find(c => c.symbol === symbol)
  console.log('Found trade:', trade)
  
  // Load TradingView widget
  useEffect(() => {
    if (!containerRef.current || !symbol) return
    
    // Load TradingView script
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/tv.js'
    script.async = true
    script.onload = () => {
      if (window.TradingView && containerRef.current) {
        new window.TradingView.widget({
          autosize: true,
          symbol: `NASDAQ:${symbol}`,
          interval: '5',
          timezone: 'America/New_York',
          theme: 'dark',
          style: '1',
          locale: 'en',
          toolbar_bg: '#1a1a2e',
          enable_publishing: false,
          allow_symbol_change: true,
          container_id: containerRef.current.id,
          hide_side_toolbar: false,
          studies: ['Volume@tv-basicstudies'],
          save_image: false,
          withdateranges: true,
        })
        setWidgetReady(true)
      }
    }
    document.head.appendChild(script)
    
    return () => {
      // Cleanup
      if (script.parentNode) {
        script.parentNode.removeChild(script)
      }
    }
  }, [symbol])
  
  const formattedDate = new Date(date).toLocaleDateString('en-GB', { 
    weekday: 'long', 
    day: 'numeric', 
    month: 'long', 
    year: 'numeric' 
  })
  
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button 
                onClick={() => router.back()}
                className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
              >
                <ArrowLeft className="h-5 w-5" />
                <span>Back to Scanner</span>
              </button>
              <div className="h-6 w-px bg-border" />
              <div>
                <h1 className="text-2xl font-bold flex items-center gap-2">
                  {symbol}
                  {trade && (
                    <span className={`text-sm px-2 py-0.5 rounded ${
                      trade.direction === 1 
                        ? 'bg-success/20 text-success' 
                        : 'bg-destructive/20 text-destructive'
                    }`}>
                      {trade.direction === 1 ? (
                        <span className="flex items-center gap-1">
                          <ArrowUpRight className="h-3 w-3" /> LONG
                        </span>
                      ) : (
                        <span className="flex items-center gap-1">
                          <ArrowDownRight className="h-3 w-3" /> SHORT
                        </span>
                      )}
                    </span>
                  )}
                </h1>
                <p className="text-sm text-muted-foreground">{formattedDate}</p>
              </div>
            </div>
            
            {trade && trade.entered && (
              <div className={`text-right px-4 py-2 rounded-lg ${
                trade.is_winner 
                  ? 'bg-success/10 border border-success/30' 
                  : 'bg-destructive/10 border border-destructive/30'
              }`}>
                <div className={`text-2xl font-bold ${
                  trade.is_winner ? 'text-success' : 'text-destructive'
                }`}>
                  {(trade.pnl_pct || 0) > 0 ? '+' : ''}{trade.pnl_pct}%
                </div>
                <div className="text-sm text-muted-foreground">
                  {(trade.base_dollar_pnl || 0) > 0 ? '+' : ''}${(trade.base_dollar_pnl || 0).toFixed(2)} (1x)
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      
      <div className="container mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* TradingView Chart */}
          <div className="lg:col-span-3">
            <div className="bg-card rounded-lg border border-border overflow-hidden">
              <div 
                id="tradingview_chart"
                ref={containerRef}
                className="h-[600px]"
              />
            </div>
          </div>
          
          {/* Trade Details Sidebar */}
          <div className="space-y-4">
            {isLoading ? (
              <div className="bg-card rounded-lg border border-border p-6 text-center">
                <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full mx-auto mb-2" />
                <p className="text-muted-foreground">Loading trade data...</p>
              </div>
            ) : error ? (
              <div className="bg-card rounded-lg border border-destructive/30 p-6 text-center">
                <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-2" />
                <p className="text-destructive">Failed to load trade data</p>
              </div>
            ) : !trade ? (
              <div className="bg-card rounded-lg border border-border p-6 text-center">
                <AlertCircle className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                <p className="text-muted-foreground">Trade not found for this date</p>
              </div>
            ) : (
              <>
                {/* Opening Range Card */}
                <div className="bg-card rounded-lg border border-border p-4">
                  <h3 className="font-semibold mb-3 flex items-center gap-2">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                    Opening Range (9:30-9:35)
                  </h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">High</span>
                      <span className="font-medium text-success">${trade.or_high?.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Low</span>
                      <span className="font-medium text-destructive">${trade.or_low?.toFixed(2)}</span>
                    </div>
                    {trade.or_open && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Open</span>
                        <span className="font-medium">${trade.or_open?.toFixed(2)}</span>
                      </div>
                    )}
                    {trade.or_close && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Close</span>
                        <span className="font-medium">${trade.or_close?.toFixed(2)}</span>
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Trade Levels Card */}
                <div className="bg-card rounded-lg border border-border p-4">
                  <h3 className="font-semibold mb-3 flex items-center gap-2">
                    <Target className="h-4 w-4 text-muted-foreground" />
                    Trade Levels
                  </h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Entry</span>
                      <span className="font-medium text-blue-400">${trade.entry_price?.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Stop</span>
                      <span className="font-medium text-destructive">${trade.stop_price?.toFixed(2)}</span>
                    </div>
                    {trade.exit_price && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Exit</span>
                        <span className="font-medium">${trade.exit_price?.toFixed(2)}</span>
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Execution Card */}
                <div className="bg-card rounded-lg border border-border p-4">
                  <h3 className="font-semibold mb-3 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-muted-foreground" />
                    Execution
                  </h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Status</span>
                      <span className={`font-medium ${
                        trade.entered 
                          ? trade.exit_reason === 'STOP_LOSS' 
                            ? 'text-destructive' 
                            : 'text-blue-400'
                          : 'text-muted-foreground'
                      }`}>
                        {trade.entered 
                          ? trade.exit_reason === 'STOP_LOSS' ? 'Stopped' : 'EOD Exit'
                          : 'No Entry'
                        }
                      </span>
                    </div>
                    {trade.entry_time && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Entry Time</span>
                        <span className="font-medium">{trade.entry_time}</span>
                      </div>
                    )}
                    {trade.exit_time && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Exit Time</span>
                        <span className="font-medium">{trade.exit_time}</span>
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Metrics Card */}
                <div className="bg-card rounded-lg border border-border p-4">
                  <h3 className="font-semibold mb-3 flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-muted-foreground" />
                    Metrics
                  </h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Rank</span>
                      <span className="font-medium">#{trade.rank}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">RVOL</span>
                      <span className="font-medium text-orange-400">{(trade.rvol * 100).toFixed(0)}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">ATR</span>
                      <span className="font-medium">${trade.atr?.toFixed(2)}</span>
                    </div>
                    {trade.day_change_pct !== undefined && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Day Change</span>
                        <span className={`font-medium ${
                          trade.day_change_pct > 0 ? 'text-success' : 'text-destructive'
                        }`}>
                          {trade.day_change_pct > 0 ? '+' : ''}{trade.day_change_pct}%
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Leverage</span>
                      <span className="font-medium">{trade.leverage?.toFixed(1)}x</span>
                    </div>
                  </div>
                </div>
                
                {/* P&L Card (if entered) */}
                {trade.entered && (
                  <div className={`rounded-lg border p-4 ${
                    trade.is_winner 
                      ? 'bg-success/10 border-success/30' 
                      : 'bg-destructive/10 border-destructive/30'
                  }`}>
                    <h3 className="font-semibold mb-3 flex items-center gap-2">
                      <DollarSign className="h-4 w-4" />
                      Profit & Loss
                    </h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">P&L %</span>
                        <span className={`font-bold ${
                          trade.is_winner ? 'text-success' : 'text-destructive'
                        }`}>
                          {(trade.pnl_pct || 0) > 0 ? '+' : ''}{trade.pnl_pct}%
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">$ P&L (1x)</span>
                        <span className={`font-bold ${
                          trade.is_winner ? 'text-success' : 'text-destructive'
                        }`}>
                          {(trade.base_dollar_pnl || 0) > 0 ? '+' : ''}${(trade.base_dollar_pnl || 0).toFixed(2)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">$ P&L ({trade.leverage}x)</span>
                        <span className={`font-bold ${
                          trade.is_winner ? 'text-success' : 'text-destructive'
                        }`}>
                          {(trade.dollar_pnl || 0) > 0 ? '+' : ''}${(trade.dollar_pnl || 0).toFixed(2)}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
