'use client'

import useSWR from 'swr'
import { ArrowUpRight, ArrowDownRight, RefreshCw } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Candidate {
  symbol: string
  rank: number
  direction: number
  direction_label: string
  or_high: number
  or_low: number
  or_open: number
  or_close: number
  or_volume: number
  atr: number
  avg_volume: number
  rvol: number
  entry_price: number
  stop_price: number
}

interface CandidatesResponse {
  status: string
  timestamp: string
  count: number
  candidates: Candidate[]
}

export function CandidatesTable() {
  const { data, error, isLoading, mutate } = useSWR<CandidatesResponse>(
    '/api/scanner/today',
    fetcher,
    { refreshInterval: 60000 } // Refresh every minute
  )
  
  if (isLoading) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Today's Candidates</h2>
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-secondary rounded"></div>
          ))}
        </div>
      </div>
    )
  }
  
  if (error) {
    return (
      <div className="bg-card rounded-lg border border-border p-4">
        <h2 className="text-lg font-semibold mb-4">Today's Candidates</h2>
        <p className="text-destructive">Failed to load candidates</p>
      </div>
    )
  }
  
  const candidates = data?.candidates || []
  
  return (
    <div className="bg-card rounded-lg border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            Today's Candidates ({candidates.length})
          </h2>
          {data?.timestamp && (
            <p className="text-xs text-muted-foreground">
              Last scan: {new Date(data.timestamp).toLocaleTimeString()}
            </p>
          )}
        </div>
        <button
          onClick={() => mutate()}
          className="p-2 hover:bg-secondary rounded-md transition-colors"
          title="Refresh candidates"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      
      {candidates.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          <p>No candidates found.</p>
          <p className="text-sm mt-1">
            Run the scanner after 9:35 AM ET to find ORB candidates.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-sm text-muted-foreground">
                <th className="px-4 py-3 font-medium">Rank</th>
                <th className="px-4 py-3 font-medium">Symbol</th>
                <th className="px-4 py-3 font-medium">Direction</th>
                <th className="px-4 py-3 font-medium text-right">OR High</th>
                <th className="px-4 py-3 font-medium text-right">OR Low</th>
                <th className="px-4 py-3 font-medium text-right">OR Vol</th>
                <th className="px-4 py-3 font-medium text-right">RVOL</th>
                <th className="px-4 py-3 font-medium text-right">ATR(14)</th>
                <th className="px-4 py-3 font-medium text-right">Entry</th>
                <th className="px-4 py-3 font-medium text-right">Stop</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => {
                const isLong = c.direction === 1
                return (
                  <tr 
                    key={c.symbol} 
                    className="border-b border-border hover:bg-secondary/50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-muted-foreground">
                      #{c.rank}
                    </td>
                    <td className="px-4 py-3 font-bold">{c.symbol}</td>
                    <td className="px-4 py-3">
                      <span className={`
                        inline-flex items-center gap-1 text-sm font-medium
                        ${isLong ? 'text-success' : 'text-destructive'}
                      `}>
                        {isLong ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : (
                          <ArrowDownRight className="h-4 w-4" />
                        )}
                        {c.direction_label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      ${c.or_high?.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      ${c.or_low?.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {(c.or_volume / 1000).toFixed(0)}K
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-orange-500">
                      {(c.rvol * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-3 text-right">
                      ${c.atr?.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-blue-500">
                      ${c.entry_price?.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-destructive">
                      ${c.stop_price?.toFixed(2)}
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
