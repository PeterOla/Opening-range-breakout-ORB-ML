import { Navbar } from '@/components/layout/Navbar'
import { AccountSummary } from '@/components/dashboard/AccountSummary'
import { PositionsTable } from '@/components/dashboard/PositionsTable'
import { TodayPerformance } from '@/components/dashboard/TodayPerformance'
import { PnLChart } from '@/components/dashboard/PnLChart'

export default function DashboardPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6 space-y-6">
        {/* Account Summary Bar */}
        <AccountSummary />
        
        {/* Main Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Positions Table - spans 2 columns */}
          <div className="lg:col-span-2">
            <PositionsTable />
          </div>
          
          {/* Today's Performance */}
          <div className="lg:col-span-1">
            <TodayPerformance />
          </div>
        </div>
        
        {/* P&L Chart */}
        <PnLChart />
      </main>
    </div>
  )
}
