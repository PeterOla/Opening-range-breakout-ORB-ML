import { Navbar } from '@/components/layout/Navbar'
import { ScannerControls, UniverseStats, CandidatesTable } from '@/components/scanner'

export default function ScannerPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6 space-y-6">
        {/* Page Header */}
        <div>
          <h1 className="text-2xl font-bold">Stock Scanner</h1>
          <p className="text-muted-foreground">
            Sync ticker universe, fetch daily data, and run ORB scans
          </p>
        </div>
        
        {/* Universe Stats */}
        <UniverseStats />
        
        {/* Scanner Controls */}
        <ScannerControls />
        
        {/* Candidates Table */}
        <CandidatesTable />
      </main>
    </div>
  )
}
