'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { ArrowUpRight, ArrowDownRight, X, Clock, CheckCircle, Loader2 } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

type StatusFilter = 'all' | 'PENDING' | 'OPEN' | 'CLOSED'

interface Trade {
  id: number
  timestamp: string
  ticker: string
  side: string
  shares: number
  entry_price: number
  exit_price: number | null
  stop_price: number | null
  pnl: number | null
  status: string
  alpaca_order_id: string | null
}

export function PositionsTable() {
  const [filter, setFilter] = useState<StatusFilter>('all')
  
  const { data: trades, error, isLoading, mutate } = useSWR<Trade[]>(
    '/api/trades/today',
    fetcher,
    { refreshInterval: 5000 }
  )
  
  const closePosition = async (ticker: string) => {
    if (!confirm(`Close position in ${ticker}?`)) return
    
    try {
      await fetch(`/api/positions/${ticker}/close`, { method: 'POST' })
      mutate()
    } catch (err) {
      console.error('Failed to close position:', err)
    }
  }
  
  const filteredTrades = trades?.filter(t => 
    filter === 'all' || t.status === filter
  ) || []
  
  const pendingCount = trades?.filter(t => t.status === 'PENDING').length || 0
  const openCount = trades?.filter(t => t.status === 'OPEN').length || 0
  const closedCount = trades?.filter(t => t.status === 'CLOSED').length || 0
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Positions</h2>
        <div className="animate-pulse space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 bg-secondary rounded"></div>
          ))}
        </div>
      </div>
    )
  }
  
  if (error) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Positions</h2>
        <p className="text-destructive">Failed to load positions</p>
      </div>
    )
  }
  
  return (
    <div className="bg-card rounded-lg border border-border">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">
            Positions ({trades?.length || 0})
          </h2>
        </div>
        
        {/* Filter Tabs */}
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => setFilter('all')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              filter === 'all' 
                ? 'bg-primary text-primary-foreground' 
                : 'bg-secondary hover:bg-secondary/80'
            }`}
          >
            All ({trades?.length || 0})
          </button>
          <button
            onClick={() => setFilter('PENDING')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
              filter === 'PENDING' 
                ? 'bg-warning text-warning-foreground' 
                : 'bg-secondary hover:bg-secondary/80'
            }`}
          >
            <Loader2 className="h-3 w-3" />
            Pending ({pendingCount})
          </button>
          <button
            onClick={() => setFilter('OPEN')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
              filter === 'OPEN' 
                ? 'bg-blue-600 text-white' 
                : 'bg-secondary hover:bg-secondary/80'
            }`}
          >
            <Clock className="h-3 w-3" />
            Open ({openCount})
          </button>
          <button
            onClick={() => setFilter('CLOSED')}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors flex items-center gap-1 ${
              filter === 'CLOSED' 
                ? 'bg-success text-success-foreground' 
                : 'bg-secondary hover:bg-secondary/80'
            }`}
          >
            <CheckCircle className="h-3 w-3" />
            Closed ({closedCount})
          </button>
        </div>
      </div>
      
      {filteredTrades.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          No {filter === 'all' ? '' : filter.toLowerCase()} positions today
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-sm text-muted-foreground">
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Ticker</th>
                <th className="px-4 py-3 font-medium">Side</th>
                <th className="px-4 py-3 font-medium text-right">Shares</th>
                <th className="px-4 py-3 font-medium text-right">Entry</th>
                <th className="px-4 py-3 font-medium text-right">Stop</th>
                <th className="px-4 py-3 font-medium text-right">Exit</th>
                <th className="px-4 py-3 font-medium text-right">P&L</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((trade) => {
                const pnl = trade.pnl || 0
                const isPositive = pnl >= 0
                const isOpen = trade.status === 'OPEN'
                
                return (
                  <tr 
                    key={trade.id} 
                    className="border-b border-border hover:bg-secondary/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      {trade.status === 'PENDING' ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-warning/20 text-warning">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          PENDING
                        </span>
                      ) : isOpen ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-blue-500/20 text-blue-400">
                          <Clock className="h-3 w-3" />
                          OPEN
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-success/20 text-success">
                          <CheckCircle className="h-3 w-3" />
                          CLOSED
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-medium">{trade.ticker}</td>
                    <td className="px-4 py-3">
                      <span className={`
                        inline-flex items-center gap-1 text-sm font-medium
                        ${trade.side === 'LONG' ? 'text-success' : 'text-destructive'}
                      `}>
                        {trade.side === 'LONG' ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : (
                          <ArrowDownRight className="h-4 w-4" />
                        )}
                        {trade.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">{trade.shares}</td>
                    <td className="px-4 py-3 text-right">
                      ${trade.entry_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground">
                      {trade.stop_price ? `$${trade.stop_price.toFixed(2)}` : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '-'}
                    </td>
                    <td className={`px-4 py-3 text-right font-medium ${
                      trade.pnl === null ? 'text-muted-foreground' :
                      isPositive ? 'text-success' : 'text-destructive'
                    }`}>
                      {trade.pnl !== null ? (
                        <>
                          {isPositive ? '+' : ''}${pnl.toFixed(2)}
                        </>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {isOpen && (
                        <button
                          onClick={() => closePosition(trade.ticker)}
                          className="p-1.5 rounded hover:bg-destructive/20 text-destructive transition-colors"
                          title="Close position"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
