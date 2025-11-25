import { Navbar } from '@/components/layout/Navbar'
import { SignalsTable } from '@/components/signals/SignalsTable'

export default function SignalsPage() {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      
      <main className="flex-1 container mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6">Signal Monitor</h1>
        <SignalsTable />
      </main>
    </div>
  )
}
