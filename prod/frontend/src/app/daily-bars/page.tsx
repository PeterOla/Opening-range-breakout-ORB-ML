'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import { Navbar } from '@/components/layout/Navbar'
import { Search, ChevronLeft, ChevronRight, Loader2, Calendar, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface DailyBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  atr_14?: number
  avg_volume_14?: number
}

interface TickerWithBars {
  symbol: string
  name: string
  exchange: string
  price: number | null
  atr_14: number | null
  avg_volume_14: number | null
  latest_date: string | null
  meets_filters: boolean
}

interface TickerDetail {
  status: string
  ticker: {
    symbol: string
    name: string
    exchange: string
  }
  metrics: {
    price: number | null
    atr_14: number | null
    avg_volume_14: number | null
    latest_date: string | null
  }
  price_history: DailyBar[]
}

export default function DailyBarsPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const perPage = 30
  
  // Build query string
  const queryParams = new URLSearchParams()
  queryParams.set('page', page.toString())
  queryParams.set('per_page', perPage.toString())
  if (search) queryParams.set('search', search)
  
  const { data: listData, isLoading: listLoading } = useSWR<{
    status: string
    page: number
    total: number
    total_pages: number
    tickers: TickerWithBars[]
  }>(
    `/api/scanner/tickers/list?${queryParams.toString()}`,
    fetcher
  )
  
  const { data: detailData, isLoading: detailLoading } = useSWR<TickerDetail>(
    selectedSymbol ? `/api/scanner/tickers/${selectedSymbol}` : null,
    fetcher
  )
  
  // Handle search with debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchInput])
  
  // Auto-select first ticker
  useEffect(() => {
    if (listData?.tickers?.length && !selectedSymbol) {
      setSelectedSymbol(listData.tickers[0].symbol)
    }
  }, [listData, selectedSymbol])
  
  const formatVolume = (vol: number | null | undefined) => {
    if (!vol) return '—'
    if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`
    if (vol >= 1_000) return `${(vol / 1_000).toFixed(0)}K`
    return vol.toLocaleString()
  }
  
  const formatPrice = (price: number | null | undefined) => {
    if (price === null || price === undefined) return '—'
    return `$${price.toFixed(2)}`
  }
  
  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    })
  }
  
  return (
    <div className="flex flex-col h-screen bg-background">
      <Navbar />
      
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel - Symbol List */}
        <div className="w-80 border-r border-border flex flex-col">
          {/* Search */}
          <div className="p-3 border-b border-border">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search symbol..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full pl-9 pr-4 py-2 rounded-lg border border-border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
          </div>
          
          {/* Symbol List */}
          <div className="flex-1 overflow-y-auto">
            {listLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="divide-y divide-border">
                {listData?.tickers?.map((ticker) => (
                  <button
                    key={ticker.symbol}
                    onClick={() => setSelectedSymbol(ticker.symbol)}
                    className={`w-full text-left px-4 py-3 hover:bg-muted/50 transition-colors ${
                      selectedSymbol === ticker.symbol ? 'bg-primary/10 border-l-2 border-primary' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-semibold">{ticker.symbol}</span>
                      <span className="font-mono text-sm">{formatPrice(ticker.price)}</span>
                    </div>
                    <div className="text-xs text-muted-foreground truncate mt-0.5">
                      {ticker.name || '—'}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                      <span>ATR: {ticker.atr_14 ? `$${ticker.atr_14.toFixed(2)}` : '—'}</span>
                      <span>Vol: {formatVolume(ticker.avg_volume_14)}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
          
          {/* Pagination */}
          {listData && listData.total_pages > 1 && (
            <div className="flex items-center justify-between px-4 py-2 border-t border-border text-sm">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1 rounded hover:bg-muted disabled:opacity-50"
                title="Previous page"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="text-muted-foreground">
                {page} / {listData.total_pages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(listData.total_pages, p + 1))}
                disabled={page === listData.total_pages}
                className="p-1 rounded hover:bg-muted disabled:opacity-50"
                title="Next page"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
        
        {/* Right Panel - Daily Bars Detail */}
        <div className="flex-1 overflow-y-auto">
          {!selectedSymbol ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              Select a symbol to view daily bars
            </div>
          ) : detailLoading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : detailData?.status === 'error' ? (
            <div className="flex items-center justify-center h-full text-destructive">
              Failed to load data
            </div>
          ) : (
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <h1 className="text-2xl font-bold">{detailData?.ticker?.symbol}</h1>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      detailData?.ticker?.exchange === 'XNYS' 
                        ? 'bg-blue-500/10 text-blue-500' 
                        : 'bg-green-500/10 text-green-500'
                    }`}>
                      {detailData?.ticker?.exchange === 'XNYS' ? 'NYSE' : 'NASDAQ'}
                    </span>
                  </div>
                  <p className="text-muted-foreground">{detailData?.ticker?.name}</p>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold font-mono">
                    {formatPrice(detailData?.metrics?.price)}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {detailData?.metrics?.latest_date ? formatDate(detailData.metrics.latest_date) : ''}
                  </div>
                </div>
              </div>
              
              {/* Metrics */}
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-card rounded-lg border border-border p-4">
                  <div className="text-sm text-muted-foreground mb-1">ATR(14)</div>
                  <div className="text-xl font-bold font-mono">
                    {detailData?.metrics?.atr_14 ? `$${detailData.metrics.atr_14.toFixed(2)}` : '—'}
                  </div>
                </div>
                <div className="bg-card rounded-lg border border-border p-4">
                  <div className="text-sm text-muted-foreground mb-1">Avg Volume(14)</div>
                  <div className="text-xl font-bold font-mono">
                    {formatVolume(detailData?.metrics?.avg_volume_14)}
                  </div>
                </div>
                <div className="bg-card rounded-lg border border-border p-4">
                  <div className="text-sm text-muted-foreground mb-1">Data Points</div>
                  <div className="text-xl font-bold font-mono">
                    {detailData?.price_history?.length ?? 0} days
                  </div>
                </div>
              </div>
              
              {/* Daily Bars Table */}
              <div className="bg-card rounded-lg border border-border overflow-hidden">
                <div className="px-4 py-3 border-b border-border flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <h2 className="font-semibold">Daily Bars</h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border bg-muted/50">
                        <th className="text-left py-2 px-4 font-medium">Date</th>
                        <th className="text-right py-2 px-4 font-medium">Open</th>
                        <th className="text-right py-2 px-4 font-medium">High</th>
                        <th className="text-right py-2 px-4 font-medium">Low</th>
                        <th className="text-right py-2 px-4 font-medium">Close</th>
                        <th className="text-right py-2 px-4 font-medium">Change</th>
                        <th className="text-right py-2 px-4 font-medium">Volume</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detailData?.price_history && [...detailData.price_history].reverse().map((bar, idx, arr) => {
                        const prevBar = arr[idx + 1]
                        const change = prevBar ? ((bar.close - prevBar.close) / prevBar.close) * 100 : 0
                        const isUp = bar.close >= bar.open
                        
                        return (
                          <tr key={bar.date} className="border-b border-border hover:bg-muted/30">
                            <td className="py-2 px-4 font-medium">{formatDate(bar.date)}</td>
                            <td className="py-2 px-4 text-right font-mono">${bar.open.toFixed(2)}</td>
                            <td className="py-2 px-4 text-right font-mono text-green-500">${bar.high.toFixed(2)}</td>
                            <td className="py-2 px-4 text-right font-mono text-red-500">${bar.low.toFixed(2)}</td>
                            <td className="py-2 px-4 text-right font-mono">${bar.close.toFixed(2)}</td>
                            <td className={`py-2 px-4 text-right font-mono ${change >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                              <div className="flex items-center justify-end gap-1">
                                {change >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                                {change.toFixed(2)}%
                              </div>
                            </td>
                            <td className="py-2 px-4 text-right font-mono">{formatVolume(bar.volume)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
