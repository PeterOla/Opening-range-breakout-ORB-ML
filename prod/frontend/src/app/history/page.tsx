import { Navbar } from '@/components/layout/Navbar'
import { HistoryView } from '@/components/history/HistoryView'

export default function HistoryPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6">Historical Performance</h1>
        <HistoryView />
      </main>
    </div>
  )
}
