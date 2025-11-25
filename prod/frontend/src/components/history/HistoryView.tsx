'use client'

import useSWR from 'swr'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts'
import { Download } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Metrics {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  sharpe_ratio: number
  max_drawdown: number
}

interface Trade {
  id: number
  timestamp: string
  ticker: string
  side: string
  entry_price: number
  exit_price: number | null
  shares: number
  pnl: number | null
  status: string
  duration: number | null
}

export function HistoryView() {
  const { data: metrics } = useSWR<Metrics>('/api/metrics?days=30', fetcher)
  const { data: trades } = useSWR<Trade[]>('/api/trades?limit=100', fetcher)
  
  const exportCSV = () => {
    if (!trades) return
    
    const headers = ['Date', 'Ticker', 'Side', 'Entry', 'Exit', 'Shares', 'P&L', 'Duration (min)']
    const rows = trades.map(t => [
      new Date(t.timestamp).toISOString(),
      t.ticker,
      t.side,
      t.entry_price,
      t.exit_price || '',
      t.shares,
      t.pnl || '',
      t.duration || ''
    ])
    
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trades_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }
  
  // Build equity curve from trades
  const equityCurve = trades?.reduce((acc: { date: string; equity: number }[], trade) => {
    const lastEquity = acc.length > 0 ? acc[acc.length - 1].equity : 0
    if (trade.pnl && trade.status === 'CLOSED') {
      acc.push({
        date: new Date(trade.timestamp).toLocaleDateString(),
        equity: lastEquity + trade.pnl
      })
    }
    return acc
  }, []) || []
  
  return (
    <div className="space-y-6">
      {/* Metrics Grid */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {[
            { label: 'Total Trades', value: metrics.total_trades },
            { label: 'Win Rate', value: `${metrics.win_rate.toFixed(1)}%`, positive: metrics.win_rate >= 50 },
            { label: 'Total P&L', value: `$${metrics.total_pnl.toFixed(2)}`, positive: metrics.total_pnl >= 0 },
            { label: 'Avg Win', value: `$${metrics.avg_win.toFixed(2)}`, positive: true },
            { label: 'Avg Loss', value: `$${metrics.avg_loss.toFixed(2)}`, positive: false },
            { label: 'Sharpe', value: metrics.sharpe_ratio.toFixed(2), positive: metrics.sharpe_ratio >= 1 },
          ].map((m) => (
            <div key={m.label} className="bg-card rounded-lg border border-border p-4">
              <p className="text-sm text-muted-foreground">{m.label}</p>
              <p className={`text-xl font-bold ${
                m.positive === undefined ? '' : m.positive ? 'text-success' : 'text-destructive'
              }`}>
                {m.value}
              </p>
            </div>
          ))}
        </div>
      )}
      
      {/* Equity Curve */}
      <div className="bg-card rounded-lg border border-border p-4">
        <h3 className="text-lg font-semibold mb-4">Cumulative P&L</h3>
        {equityCurve.length > 0 ? (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={equityCurve}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(215 28% 20%)" />
                <XAxis dataKey="date" stroke="hsl(215 20% 65%)" fontSize={12} />
                <YAxis stroke="hsl(215 20% 65%)" fontSize={12} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(222 47% 14%)',
                    border: '1px solid hsl(215 28% 20%)',
                    borderRadius: '8px'
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="hsl(217 91% 60%)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="h-64 flex items-center justify-center text-muted-foreground">
            No trade history yet
          </div>
        )}
      </div>
      
      {/* Trade Log */}
      <div className="bg-card rounded-lg border border-border">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold">Trade Log</h3>
          <button
            onClick={exportCSV}
            className="flex items-center gap-2 px-3 py-1.5 bg-secondary rounded-lg text-sm hover:bg-secondary/80 transition-colors"
          >
            <Download className="h-4 w-4" />
            Export CSV
          </button>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-sm text-muted-foreground">
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Ticker</th>
                <th className="px-4 py-3 font-medium">Side</th>
                <th className="px-4 py-3 font-medium text-right">Entry</th>
                <th className="px-4 py-3 font-medium text-right">Exit</th>
                <th className="px-4 py-3 font-medium text-right">Shares</th>
                <th className="px-4 py-3 font-medium text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {(!trades || trades.length === 0) ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                    No trades yet
                  </td>
                </tr>
              ) : (
                trades.filter(t => t.status === 'CLOSED').map((trade) => (
                  <tr 
                    key={trade.id}
                    className="border-b border-border hover:bg-secondary/50 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm">
                      {new Date(trade.timestamp).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 font-medium">{trade.ticker}</td>
                    <td className={`px-4 py-3 ${trade.side === 'LONG' ? 'text-success' : 'text-destructive'}`}>
                      {trade.side}
                    </td>
                    <td className="px-4 py-3 text-right">${trade.entry_price.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right">
                      {trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">{trade.shares}</td>
                    <td className={`px-4 py-3 text-right font-medium ${
                      (trade.pnl || 0) >= 0 ? 'text-success' : 'text-destructive'
                    }`}>
                      {trade.pnl ? `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}` : '-'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
