'use client'

import useSWR from 'swr'
import { Trophy, Target, TrendingUp } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Trade {
  id: number
  ticker: string
  side: string
  pnl: number | null
  status: string
}

export function TodayPerformance() {
  const { data: trades, isLoading } = useSWR<Trade[]>(
    '/api/trades/today',
    fetcher,
    { refreshInterval: 10000 }
  )
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Today&apos;s Performance</h2>
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-secondary rounded w-24"></div>
          <div className="h-6 bg-secondary rounded w-full"></div>
          <div className="h-6 bg-secondary rounded w-full"></div>
        </div>
      </div>
    )
  }
  
  const closedTrades = trades?.filter(t => t.status === 'CLOSED') || []
  const totalPnl = closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0)
  const winningTrades = closedTrades.filter(t => t.pnl && t.pnl > 0)
  const winRate = closedTrades.length > 0 
    ? (winningTrades.length / closedTrades.length * 100)
    : 0
  
  const isPositive = totalPnl >= 0
  
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h2 className="text-lg font-semibold mb-4">Today&apos;s Performance</h2>
      
      <div className="space-y-4">
        {/* Total P&L */}
        <div className="text-center py-4">
          <p className="text-muted-foreground text-sm mb-1">Total P&L</p>
          <p className={`text-3xl font-bold ${isPositive ? 'text-success' : 'text-destructive'}`}>
            {isPositive ? '+' : ''}${totalPnl.toFixed(2)}
          </p>
        </div>
        
        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-secondary rounded-lg p-3 text-center">
            <div className="flex items-center justify-center gap-1 text-muted-foreground text-sm mb-1">
              <Target className="h-4 w-4" />
              Trades
            </div>
            <p className="text-xl font-bold">{closedTrades.length}</p>
          </div>
          
          <div className="bg-secondary rounded-lg p-3 text-center">
            <div className="flex items-center justify-center gap-1 text-muted-foreground text-sm mb-1">
              <Trophy className="h-4 w-4" />
              Win Rate
            </div>
            <p className={`text-xl font-bold ${winRate >= 50 ? 'text-success' : 'text-destructive'}`}>
              {winRate.toFixed(0)}%
            </p>
          </div>
        </div>
        
        {/* Recent Trades */}
        {closedTrades.length > 0 && (
          <div>
            <p className="text-sm text-muted-foreground mb-2">Recent Trades</p>
            <div className="space-y-2">
              {closedTrades.slice(0, 5).map((trade) => (
                <div 
                  key={trade.id}
                  className="flex items-center justify-between text-sm py-1"
                >
                  <span className="font-medium">{trade.ticker}</span>
                  <span className={`
                    ${(trade.pnl || 0) >= 0 ? 'text-success' : 'text-destructive'}
                  `}>
                    {(trade.pnl || 0) >= 0 ? '+' : ''}${(trade.pnl || 0).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
