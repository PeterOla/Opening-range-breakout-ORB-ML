import { Navbar } from '@/components/layout/Navbar'
import { LogsViewer } from '@/components/logs/LogsViewer'

export default function LogsPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6">System Logs</h1>
        <LogsViewer />
      </main>
    </div>
  )
}
