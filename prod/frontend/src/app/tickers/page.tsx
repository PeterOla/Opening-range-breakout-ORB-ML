'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import Link from 'next/link'
import { Navbar } from '@/components/layout/Navbar'
import { Search, ChevronLeft, ChevronRight, ArrowUpDown, Check, X, Loader2 } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Ticker {
  symbol: string
  name: string
  exchange: string
  type: string
  price: number | null
  atr_14: number | null
  avg_volume_14: number | null
  latest_date: string | null
  meets_filters: boolean
}

interface TickerListResponse {
  status: string
  page: number
  per_page: number
  total: number
  total_pages: number
  tickers: Ticker[]
}

export default function TickersPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [exchange, setExchange] = useState<string>('')
  const [perPage] = useState(50)
  
  // Build query string
  const queryParams = new URLSearchParams()
  queryParams.set('page', page.toString())
  queryParams.set('per_page', perPage.toString())
  if (search) queryParams.set('search', search)
  if (exchange) queryParams.set('exchange', exchange)
  
  const { data, isLoading } = useSWR<TickerListResponse>(
    `/api/scanner/tickers/list?${queryParams.toString()}`,
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
  
  // Check for filter param
  useEffect(() => {
    const filter = searchParams.get('filter')
    if (filter === 'qualified') {
      // Could add a qualified-only filter here
    }
  }, [searchParams])
  
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
  
  return (
    <div className="flex flex-col min-h-screen bg-background">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">Ticker Universe</h1>
            <p className="text-muted-foreground">
              {data?.total?.toLocaleString() ?? '—'} active NYSE/NASDAQ stocks
            </p>
          </div>
          
          {/* Filters */}
          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search symbol or name..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-9 pr-4 py-2 w-64 rounded-lg border border-border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            
            {/* Exchange Filter */}
            <select
              value={exchange}
              onChange={(e) => { setExchange(e.target.value); setPage(1) }}
              className="px-3 py-2 rounded-lg border border-border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="">All Exchanges</option>
              <option value="XNYS">NYSE</option>
              <option value="XNAS">NASDAQ</option>
            </select>
          </div>
        </div>
        
        {/* Table */}
        <div className="bg-card rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="text-left py-3 px-4 font-medium">Symbol</th>
                  <th className="text-left py-3 px-4 font-medium">Name</th>
                  <th className="text-left py-3 px-4 font-medium">Exchange</th>
                  <th className="text-right py-3 px-4 font-medium">Price</th>
                  <th className="text-right py-3 px-4 font-medium">ATR(14)</th>
                  <th className="text-right py-3 px-4 font-medium">Avg Vol(14)</th>
                  <th className="text-center py-3 px-4 font-medium">Qualified</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center">
                      <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                      <p className="mt-2 text-muted-foreground">Loading tickers...</p>
                    </td>
                  </tr>
                ) : data?.tickers?.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-muted-foreground">
                      No tickers found
                    </td>
                  </tr>
                ) : (
                  data?.tickers?.map((ticker) => (
                    <tr 
                      key={ticker.symbol}
                      onClick={() => router.push(`/tickers/${ticker.symbol}`)}
                      className="border-b border-border hover:bg-muted/30 cursor-pointer transition-colors"
                    >
                      <td className="py-3 px-4 font-mono font-semibold text-primary">
                        {ticker.symbol}
                      </td>
                      <td className="py-3 px-4 text-muted-foreground truncate max-w-[200px]">
                        {ticker.name || '—'}
                      </td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          ticker.exchange === 'XNYS' 
                            ? 'bg-blue-500/10 text-blue-500' 
                            : 'bg-green-500/10 text-green-500'
                        }`}>
                          {ticker.exchange === 'XNYS' ? 'NYSE' : 'NASDAQ'}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono">
                        {formatPrice(ticker.price)}
                      </td>
                      <td className="py-3 px-4 text-right font-mono">
                        {ticker.atr_14 ? `$${ticker.atr_14.toFixed(2)}` : '—'}
                      </td>
                      <td className="py-3 px-4 text-right font-mono">
                        {formatVolume(ticker.avg_volume_14)}
                      </td>
                      <td className="py-3 px-4 text-center">
                        {ticker.meets_filters ? (
                          <Check className="h-4 w-4 text-green-500 mx-auto" />
                        ) : (
                          <X className="h-4 w-4 text-muted-foreground mx-auto" />
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          
          {/* Pagination */}
          {data && data.total_pages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-border">
              <div className="text-sm text-muted-foreground">
                Showing {((page - 1) * perPage) + 1} - {Math.min(page * perPage, data.total)} of {data.total.toLocaleString()}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-2 rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm">
                  Page {page} of {data.total_pages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                  disabled={page === data.total_pages}
                  className="p-2 rounded-lg hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
