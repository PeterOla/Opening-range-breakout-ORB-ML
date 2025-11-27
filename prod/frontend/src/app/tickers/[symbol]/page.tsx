'use client'

import { useEffect, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import Link from 'next/link'
import { Navbar } from '@/components/layout/Navbar'
import { ArrowLeft, Building2, TrendingUp, Activity, DollarSign, BarChart3, Check, X, Loader2 } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface TickerDetail {
  status: string
  ticker: {
    symbol: string
    name: string
    exchange: string
    type: string
    active: boolean
    cik: string | null
    currency: string
  }
  metrics: {
    price: number | null
    atr_14: number | null
    avg_volume_14: number | null
    latest_date: string | null
    meets_price_filter: boolean
    meets_volume_filter: boolean
    meets_atr_filter: boolean
  }
  price_history: Array<{
    date: string
    open: number
    high: number
    low: number
    close: number
    volume: number
  }>
}

// TradingView Widget Component
function TradingViewWidget({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  
  useEffect(() => {
    if (!containerRef.current) return
    
    // Clear previous widget
    containerRef.current.innerHTML = ''
    
    // Create widget container
    const widgetContainer = document.createElement('div')
    widgetContainer.className = 'tradingview-widget-container'
    widgetContainer.style.height = '100%'
    widgetContainer.style.width = '100%'
    
    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    widget.style.height = 'calc(100% - 32px)'
    widget.style.width = '100%'
    widgetContainer.appendChild(widget)
    
    containerRef.current.appendChild(widgetContainer)
    
    // Load TradingView script
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.type = 'text/javascript'
    script.async = true
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: symbol,
      interval: 'D',
      timezone: 'America/New_York',
      theme: 'dark',
      style: '1',
      locale: 'en',
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com'
    })
    
    widgetContainer.appendChild(script)
    
  }, [symbol])
  
  return <div ref={containerRef} className="h-full w-full" />
}

export default function TickerDetailPage() {
  const params = useParams()
  const router = useRouter()
  const symbol = (params.symbol as string)?.toUpperCase()
  
  const { data, isLoading, error } = useSWR<TickerDetail>(
    symbol ? `/api/scanner/tickers/${symbol}` : null,
    fetcher
  )
  
  const formatVolume = (vol: number | null) => {
    if (!vol) return '—'
    if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`
    if (vol >= 1_000) return `${(vol / 1_000).toFixed(0)}K`
    return vol.toLocaleString()
  }
  
  const formatPrice = (price: number | null) => {
    if (!price) return '—'
    return `$${price.toFixed(2)}`
  }
  
  if (isLoading) {
    return (
      <div className="flex flex-col min-h-screen bg-background">
        <Navbar />
        <main className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Loader2 className="h-8 w-8 animate-spin mx-auto text-muted-foreground" />
            <p className="mt-4 text-muted-foreground">Loading {symbol}...</p>
          </div>
        </main>
      </div>
    )
  }
  
  if (error || data?.status === 'error') {
    return (
      <div className="flex flex-col min-h-screen bg-background">
        <Navbar />
        <main className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-destructive text-lg">Ticker not found: {symbol}</p>
            <Link href="/tickers" className="text-primary hover:underline mt-4 inline-block">
              ← Back to Tickers
            </Link>
          </div>
        </main>
      </div>
    )
  }
  
  const ticker = data?.ticker
  const metrics = data?.metrics
  
  return (
    <div className="flex flex-col min-h-screen bg-background">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6 space-y-6">
        {/* Back button & Header */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.back()}
            className="p-2 rounded-lg hover:bg-muted transition-colors"
            title="Go back"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{ticker?.symbol}</h1>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                ticker?.exchange === 'XNYS' 
                  ? 'bg-blue-500/10 text-blue-500' 
                  : 'bg-green-500/10 text-green-500'
              }`}>
                {ticker?.exchange === 'XNYS' ? 'NYSE' : 'NASDAQ'}
              </span>
            </div>
            <p className="text-muted-foreground">{ticker?.name}</p>
          </div>
        </div>
        
        {/* Metrics Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
              <DollarSign className="h-4 w-4" />
              Price
            </div>
            <div className="text-2xl font-bold font-mono">
              {formatPrice(metrics?.price)}
            </div>
            <div className="flex items-center gap-1 text-xs mt-1">
              {metrics?.meets_price_filter ? (
                <><Check className="h-3 w-3 text-green-500" /> ≥ $5</>
              ) : (
                <><X className="h-3 w-3 text-red-500" /> &lt; $5</>
              )}
            </div>
          </div>
          
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
              <Activity className="h-4 w-4" />
              ATR(14)
            </div>
            <div className="text-2xl font-bold font-mono">
              {metrics?.atr_14 ? `$${metrics.atr_14.toFixed(2)}` : '—'}
            </div>
            <div className="flex items-center gap-1 text-xs mt-1">
              {metrics?.meets_atr_filter ? (
                <><Check className="h-3 w-3 text-green-500" /> ≥ $0.50</>
              ) : (
                <><X className="h-3 w-3 text-red-500" /> &lt; $0.50</>
              )}
            </div>
          </div>
          
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
              <BarChart3 className="h-4 w-4" />
              Avg Volume(14)
            </div>
            <div className="text-2xl font-bold font-mono">
              {formatVolume(metrics?.avg_volume_14)}
            </div>
            <div className="flex items-center gap-1 text-xs mt-1">
              {metrics?.meets_volume_filter ? (
                <><Check className="h-3 w-3 text-green-500" /> ≥ 1M</>
              ) : (
                <><X className="h-3 w-3 text-red-500" /> &lt; 1M</>
              )}
            </div>
          </div>
          
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
              <Building2 className="h-4 w-4" />
              Type
            </div>
            <div className="text-2xl font-bold">
              {ticker?.type === 'CS' ? 'Common Stock' : ticker?.type}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {ticker?.currency}
            </div>
          </div>
        </div>
        
        {/* TradingView Chart */}
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="font-semibold">Price Chart</h2>
          </div>
          <div className="h-[500px]">
            {ticker?.symbol && <TradingViewWidget symbol={ticker.symbol} />}
          </div>
        </div>
        
        {/* Price History Table */}
        {data?.price_history && data.price_history.length > 0 && (
          <div className="bg-card rounded-lg border border-border overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <h2 className="font-semibold">Recent Price History (Last 30 Days)</h2>
            </div>
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left py-2 px-4 font-medium">Date</th>
                    <th className="text-right py-2 px-4 font-medium">Open</th>
                    <th className="text-right py-2 px-4 font-medium">High</th>
                    <th className="text-right py-2 px-4 font-medium">Low</th>
                    <th className="text-right py-2 px-4 font-medium">Close</th>
                    <th className="text-right py-2 px-4 font-medium">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.price_history].reverse().map((bar) => (
                    <tr key={bar.date} className="border-b border-border hover:bg-muted/30">
                      <td className="py-2 px-4">{new Date(bar.date).toLocaleDateString()}</td>
                      <td className="py-2 px-4 text-right font-mono">${bar.open.toFixed(2)}</td>
                      <td className="py-2 px-4 text-right font-mono text-green-500">${bar.high.toFixed(2)}</td>
                      <td className="py-2 px-4 text-right font-mono text-red-500">${bar.low.toFixed(2)}</td>
                      <td className="py-2 px-4 text-right font-mono">${bar.close.toFixed(2)}</td>
                      <td className="py-2 px-4 text-right font-mono">{formatVolume(bar.volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
