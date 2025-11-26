'use client'

import useSWR from 'swr'
import { Database, Activity, TrendingUp, Filter } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface TickerStats {
  total: number
  active: number
  delisted: number
  nyse: number
  nasdaq: number
  meets_all_filters: number
}

interface HealthData {
  status: string
  database: {
    daily_bars_count: number
    symbols_count: number
    latest_bar_date: string | null
    todays_or_count: number
  }
}

export function UniverseStats() {
  const { data: statsData } = useSWR<{ stats: TickerStats }>(
    '/api/scanner/ticker-stats',
    fetcher,
    { refreshInterval: 30000 }
  )
  
  const { data: healthData } = useSWR<HealthData>(
    '/api/scanner/health',
    fetcher,
    { refreshInterval: 30000 }
  )
  
  const stats = statsData?.stats
  const health = healthData
  
  const cards = [
    {
      title: 'Total Tickers',
      value: stats?.total?.toLocaleString() ?? '—',
      subtitle: `${stats?.active?.toLocaleString() ?? '0'} active`,
      icon: Database,
      colour: 'text-blue-500',
    },
    {
      title: 'Daily Bars',
      value: health?.database?.daily_bars_count?.toLocaleString() ?? '—',
      subtitle: health?.database?.latest_bar_date 
        ? `Latest: ${new Date(health.database.latest_bar_date).toLocaleDateString()}`
        : 'No data',
      icon: Activity,
      colour: 'text-green-500',
    },
    {
      title: 'Symbols with Data',
      value: health?.database?.symbols_count?.toLocaleString() ?? '—',
      subtitle: 'With daily bars',
      icon: TrendingUp,
      colour: 'text-purple-500',
    },
    {
      title: 'Pass All Filters',
      value: stats?.meets_all_filters?.toLocaleString() ?? '—',
      subtitle: 'Price ≥$5, Vol ≥1M, ATR ≥$0.50',
      icon: Filter,
      colour: 'text-orange-500',
    },
  ]
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => (
        <div key={card.title} className="bg-card rounded-lg border border-border p-4">
          <div className="flex items-center gap-3 mb-2">
            <card.icon className={`h-5 w-5 ${card.colour}`} />
            <span className="text-sm font-medium text-muted-foreground">
              {card.title}
            </span>
          </div>
          <div className="text-2xl font-bold">{card.value}</div>
          <div className="text-xs text-muted-foreground mt-1">{card.subtitle}</div>
        </div>
      ))}
    </div>
  )
}
