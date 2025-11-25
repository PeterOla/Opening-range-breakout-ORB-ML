'use client'

import { useMemo } from 'react'
import useSWR from 'swr'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Trade {
  id: number
  timestamp: string
  pnl: number | null
  status: string
}

export function PnLChart() {
  const { data: trades, isLoading } = useSWR<Trade[]>(
    '/api/trades/today',
    fetcher,
    { refreshInterval: 10000 }
  )
  
  // Calculate cumulative P&L
  const chartData = useMemo(() => {
    if (!trades) return []
    
    const closedTrades = trades
      .filter(t => t.status === 'CLOSED' && t.pnl !== null)
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
    
    let cumulative = 0
    return closedTrades.map((trade) => {
      cumulative += trade.pnl || 0
      return {
        time: new Date(trade.timestamp).toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit'
        }),
        pnl: cumulative,
        tradePnl: trade.pnl
      }
    })
  }, [trades])
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Intraday P&L</h2>
        <div className="h-64 animate-pulse bg-secondary rounded"></div>
      </div>
    )
  }
  
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h2 className="text-lg font-semibold mb-4">Intraday P&L</h2>
      
      {chartData.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-muted-foreground">
          No trades today
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(215 28% 20%)" />
              <XAxis 
                dataKey="time" 
                stroke="hsl(215 20% 65%)"
                fontSize={12}
              />
              <YAxis 
                stroke="hsl(215 20% 65%)"
                fontSize={12}
                tickFormatter={(value) => `$${value}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'hsl(222 47% 14%)',
                  border: '1px solid hsl(215 28% 20%)',
                  borderRadius: '8px'
                }}
                labelStyle={{ color: 'hsl(210 40% 98%)' }}
                formatter={(value: number) => [`$${value.toFixed(2)}`, 'Cumulative P&L']}
              />
              <ReferenceLine y={0} stroke="hsl(215 20% 65%)" strokeDasharray="3 3" />
              <Line
                type="monotone"
                dataKey="pnl"
                stroke="hsl(217 91% 60%)"
                strokeWidth={2}
                dot={{
                  fill: 'hsl(217 91% 60%)',
                  strokeWidth: 0,
                  r: 4
                }}
                activeDot={{
                  r: 6,
                  fill: 'hsl(217 91% 60%)'
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
