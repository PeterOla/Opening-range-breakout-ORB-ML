'use client'

import useSWR from 'swr'
import { Wallet, TrendingUp, TrendingDown, DollarSign } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Account {
  equity: number
  cash: number
  buying_power: number
  day_pnl: number
  day_pnl_pct: number
  paper_mode: boolean
}

export function AccountSummary() {
  const { data, error, isLoading } = useSWR<Account>('/api/account', fetcher, {
    refreshInterval: 5000 // Refresh every 5 seconds
  })
  
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-card rounded-lg p-4 animate-pulse">
            <div className="h-4 bg-secondary rounded w-20 mb-2"></div>
            <div className="h-6 bg-secondary rounded w-24"></div>
          </div>
        ))}
      </div>
    )
  }
  
  if (error || !data) {
    return (
      <div className="bg-destructive/20 border border-destructive rounded-lg p-4 text-center">
        Failed to load account data
      </div>
    )
  }
  
  const isPositive = data.day_pnl >= 0
  
  const stats = [
    {
      label: 'Equity',
      value: `$${data.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      icon: Wallet,
      color: 'text-primary'
    },
    {
      label: 'Buying Power',
      value: `$${data.buying_power.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      icon: DollarSign,
      color: 'text-muted-foreground'
    },
    {
      label: 'Day P&L',
      value: `${isPositive ? '+' : ''}$${data.day_pnl.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      icon: isPositive ? TrendingUp : TrendingDown,
      color: isPositive ? 'text-success' : 'text-destructive'
    },
    {
      label: 'Day Return',
      value: `${isPositive ? '+' : ''}${data.day_pnl_pct.toFixed(2)}%`,
      icon: isPositive ? TrendingUp : TrendingDown,
      color: isPositive ? 'text-success' : 'text-destructive'
    }
  ]
  
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <div key={stat.label} className="bg-card rounded-lg p-4 border border-border">
          <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
            <stat.icon className={`h-4 w-4 ${stat.color}`} />
            {stat.label}
          </div>
          <div className={`text-xl font-bold ${stat.color}`}>
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  )
}
