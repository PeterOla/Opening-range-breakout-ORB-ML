import { Navbar } from '@/components/layout/Navbar'
import { ScannerControls, UniverseStats, Top20Results } from '@/components/scanner'

export default function ScannerPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6 space-y-6">
        {/* Page Header */}
        <div>
          <h1 className="text-2xl font-bold">ORB Scanner</h1>
          <p className="text-muted-foreground">
            Top 20 Opening Range Breakout candidates ranked by RVOL
          </p>
        </div>
        
        {/* Top 20 Results - Time-aware display */}
        <Top20Results />
        
        {/* Collapsible: Data Controls */}
        <details className="bg-card rounded-lg border border-border">
          <summary className="px-4 py-3 cursor-pointer font-medium hover:bg-secondary/50 transition-colors">
            📊 Data Sync & Universe Stats
          </summary>
          <div className="p-4 space-y-6 border-t border-border">
            {/* Universe Stats */}
            <UniverseStats />
            
            {/* Scanner Controls */}
            <ScannerControls />
          </div>
        </details>
      </main>
    </div>
  )
}
