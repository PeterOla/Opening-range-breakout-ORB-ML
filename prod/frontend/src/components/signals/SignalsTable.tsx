'use client'

import useSWR from 'swr'
import { CheckCircle, Clock, XCircle, ArrowUpRight, ArrowDownRight } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Signal {
  id: number
  timestamp: string
  ticker: string
  side: string
  confidence: number | null
  entry_price: number
  status: string
  filled_price: number | null
  rejection_reason: string | null
}

const statusIcons: Record<string, React.ReactNode> = {
  FILLED: <CheckCircle className="h-4 w-4 text-success" />,
  PENDING: <Clock className="h-4 w-4 text-warning" />,
  REJECTED: <XCircle className="h-4 w-4 text-destructive" />,
}

export function SignalsTable() {
  const { data: signals, isLoading, error } = useSWR<Signal[]>(
    '/api/signals',
    fetcher,
    { refreshInterval: 5000 }
  )
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-secondary rounded"></div>
          ))}
        </div>
      </div>
    )
  }
  
  if (error || !signals) {
    return (
      <div className="bg-destructive/20 border border-destructive rounded-lg p-4 text-center">
        Failed to load signals
      </div>
    )
  }
  
  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border text-left text-sm text-muted-foreground">
            <th className="px-4 py-3 font-medium">Time</th>
            <th className="px-4 py-3 font-medium">Ticker</th>
            <th className="px-4 py-3 font-medium">Side</th>
            <th className="px-4 py-3 font-medium text-right">Confidence</th>
            <th className="px-4 py-3 font-medium text-right">Entry Price</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium text-right">Fill Price</th>
          </tr>
        </thead>
        <tbody>
          {signals.length === 0 ? (
            <tr>
              <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                No signals yet
              </td>
            </tr>
          ) : (
            signals.map((signal) => (
              <tr 
                key={signal.id}
                className="border-b border-border hover:bg-secondary/50 transition-colors"
              >
                <td className="px-4 py-3 text-sm">
                  {new Date(signal.timestamp).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                  })}
                </td>
                <td className="px-4 py-3 font-medium">{signal.ticker}</td>
                <td className="px-4 py-3">
                  <span className={`
                    inline-flex items-center gap-1 text-sm font-medium
                    ${signal.side === 'LONG' ? 'text-success' : 'text-destructive'}
                  `}>
                    {signal.side === 'LONG' ? (
                      <ArrowUpRight className="h-4 w-4" />
                    ) : (
                      <ArrowDownRight className="h-4 w-4" />
                    )}
                    {signal.side}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {signal.confidence ? `${(signal.confidence * 100).toFixed(0)}%` : '-'}
                </td>
                <td className="px-4 py-3 text-right">
                  ${signal.entry_price.toFixed(2)}
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5">
                    {statusIcons[signal.status]}
                    <span className="text-sm">{signal.status}</span>
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {signal.filled_price ? `$${signal.filled_price.toFixed(2)}` : '-'}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
