'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { KillSwitch } from '@/components/controls/KillSwitch'
import { 
  LayoutDashboard, 
  Signal, 
  History, 
  FileText,
  Activity
} from 'lucide-react'

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/signals', label: 'Signals', icon: Signal },
  { href: '/history', label: 'History', icon: History },
  { href: '/logs', label: 'Logs', icon: FileText },
]

export function Navbar() {
  const pathname = usePathname()
  
  return (
    <nav className="bg-card border-b border-border">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <Activity className="h-6 w-6 text-primary" />
            <span className="text-lg font-bold">ORB Trading</span>
            <span className="text-xs bg-warning text-background px-2 py-0.5 rounded font-medium">
              PAPER
            </span>
          </div>
          
          {/* Nav Links */}
          <div className="flex items-center gap-1">
            {navItems.map((item) => {
              const isActive = pathname === item.href
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`
                    flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium
                    transition-colors
                    ${isActive 
                      ? 'bg-primary text-background' 
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                    }
                  `}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              )
            })}
          </div>
          
          {/* Kill Switch */}
          <KillSwitch />
        </div>
      </div>
    </nav>
  )
}
