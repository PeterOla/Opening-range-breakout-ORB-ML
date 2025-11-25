'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { AlertCircle, AlertTriangle, Info } from 'lucide-react'

const fetcher = (url: string) => fetch(url).then(res => res.json())

interface Log {
  id: number
  timestamp: string
  level: string
  component: string
  message: string
}

const levelIcons: Record<string, React.ReactNode> = {
  INFO: <Info className="h-4 w-4 text-primary" />,
  WARN: <AlertTriangle className="h-4 w-4 text-warning" />,
  ERROR: <AlertCircle className="h-4 w-4 text-destructive" />,
}

const levelColors: Record<string, string> = {
  INFO: 'text-primary',
  WARN: 'text-warning',
  ERROR: 'text-destructive',
}

export function LogsViewer() {
  const [levelFilter, setLevelFilter] = useState<string>('')
  const [componentFilter, setComponentFilter] = useState<string>('')
  
  const queryParams = new URLSearchParams()
  if (levelFilter) queryParams.set('level', levelFilter)
  if (componentFilter) queryParams.set('component', componentFilter)
  
  const { data: logs, isLoading } = useSWR<Log[]>(
    `/api/logs?${queryParams.toString()}`,
    fetcher,
    { refreshInterval: 3000 }
  )
  
  const components = [...new Set(logs?.map(l => l.component) || [])]
  
  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-4">
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="bg-secondary border border-border rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Levels</option>
          <option value="INFO">INFO</option>
          <option value="WARN">WARN</option>
          <option value="ERROR">ERROR</option>
        </select>
        
        <select
          value={componentFilter}
          onChange={(e) => setComponentFilter(e.target.value)}
          className="bg-secondary border border-border rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Components</option>
          {components.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
      
      {/* Logs */}
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        {isLoading ? (
          <div className="p-4 animate-pulse space-y-2">
            {[...Array(10)].map((_, i) => (
              <div key={i} className="h-6 bg-secondary rounded"></div>
            ))}
          </div>
        ) : (
          <div className="divide-y divide-border max-h-[600px] overflow-y-auto font-mono text-sm">
            {(!logs || logs.length === 0) ? (
              <div className="p-8 text-center text-muted-foreground">
                No logs found
              </div>
            ) : (
              logs.map((log) => (
                <div 
                  key={log.id}
                  className="px-4 py-2 hover:bg-secondary/50 transition-colors flex items-start gap-3"
                >
                  <span className="text-muted-foreground whitespace-nowrap">
                    {new Date(log.timestamp).toLocaleTimeString('en-US', {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit'
                    })}
                  </span>
                  <span className="flex items-center gap-1.5 w-16">
                    {levelIcons[log.level]}
                    <span className={levelColors[log.level]}>{log.level}</span>
                  </span>
                  <span className="text-muted-foreground w-24 truncate">
                    {log.component}
                  </span>
                  <span className="flex-1">{log.message}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
