'use client'

import { useState, useEffect } from 'react'
import { Power } from 'lucide-react'

export function KillSwitch() {
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(false)
  
  // Fetch initial state
  useEffect(() => {
    fetch('/api/kill-switch')
      .then(res => res.json())
      .then(data => setEnabled(data.enabled))
      .catch(console.error)
  }, [])
  
  const toggle = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/kill-switch?enable=${!enabled}`, {
        method: 'POST'
      })
      const data = await res.json()
      setEnabled(data.enabled)
    } catch (err) {
      console.error('Failed to toggle kill switch:', err)
    } finally {
      setLoading(false)
    }
  }
  
  return (
    <button
      onClick={toggle}
      disabled={loading}
      className={`
        flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm
        transition-all
        ${enabled 
          ? 'bg-destructive text-white animate-pulse' 
          : 'bg-success text-white hover:opacity-90'
        }
        ${loading ? 'opacity-50 cursor-not-allowed' : ''}
      `}
    >
      <Power className="h-4 w-4" />
      {enabled ? 'STOPPED' : 'LIVE'}
    </button>
  )
}
