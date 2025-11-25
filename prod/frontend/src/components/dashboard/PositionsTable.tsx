'use client'

import useSWR from 'swr'
import { ArrowUpRight, ArrowDownRight, X } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Position {
  ticker: string
  side: string
  shares: number
  entry_price: number
  current_price: number
  pnl: number
  pnl_pct: number
}

export function PositionsTable() {
  const { data: positions, error, isLoading, mutate } = useSWR<Position[]>(
    '/api/positions',
    fetcher,
    { refreshInterval: 2000 }
  )
  
  const closePosition = async (ticker: string) => {
    if (!confirm(`Close position in ${ticker}?`)) return
    
    try {
      await fetch(`/api/positions/${ticker}/close`, { method: 'POST' })
      mutate() // Refresh positions
    } catch (err) {
      console.error('Failed to close position:', err)
    }
  }
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Open Positions</h2>
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
        <h2 className="text-lg font-semibold mb-4">Open Positions</h2>
        <p className="text-destructive">Failed to load positions</p>
      </div>
    )
  }
  
  return (
    <div className="bg-card rounded-lg border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          Open Positions ({positions?.length || 0})
        </h2>
      </div>
      
      {(!positions || positions.length === 0) ? (
        <div className="p-8 text-center text-muted-foreground">
          No open positions
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-sm text-muted-foreground">
                <th className="px-4 py-3 font-medium">Ticker</th>
                <th className="px-4 py-3 font-medium">Side</th>
                <th className="px-4 py-3 font-medium text-right">Shares</th>
                <th className="px-4 py-3 font-medium text-right">Entry</th>
                <th className="px-4 py-3 font-medium text-right">Current</th>
                <th className="px-4 py-3 font-medium text-right">P&L</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                const isPositive = pos.pnl >= 0
                return (
                  <tr 
                    key={pos.ticker} 
                    className="border-b border-border hover:bg-secondary/50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium">{pos.ticker}</td>
                    <td className="px-4 py-3">
                      <span className={`
                        inline-flex items-center gap-1 text-sm font-medium
                        ${pos.side === 'LONG' ? 'text-success' : 'text-destructive'}
                      `}>
                        {pos.side === 'LONG' ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : (
                          <ArrowDownRight className="h-4 w-4" />
                        )}
                        {pos.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">{pos.shares}</td>
                    <td className="px-4 py-3 text-right">
                      ${pos.entry_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      ${pos.current_price.toFixed(2)}
                    </td>
                    <td className={`px-4 py-3 text-right font-medium ${isPositive ? 'text-success' : 'text-destructive'}`}>
                      {isPositive ? '+' : ''}${pos.pnl.toFixed(2)}
                      <span className="text-xs ml-1">
                        ({isPositive ? '+' : ''}{pos.pnl_pct.toFixed(1)}%)
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => closePosition(pos.ticker)}
                        className="p-1.5 rounded hover:bg-destructive/20 text-destructive transition-colors"
                        title="Close position"
                      >
                        <X className="h-4 w-4" />
                      </button>
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
