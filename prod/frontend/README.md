# Frontend Setup

## Install & Run

```bash
cd prod/frontend
npm install
npm run dev
```

Open http://localhost:3000

## Environment Setup

```bash
cp .env.local.example .env.local
# Edit with your backend URL
```

## Pages

- `/` — Live trading dashboard (positions, P&L, charts)
- `/signals` — Signal monitor (active + historical signals)
- `/history` — Historical performance (equity curve, metrics, trade log)
- `/logs` — System logs viewer

## Deployment

### Vercel (Free)

1. Push to GitHub
2. Import project in Vercel
3. Set environment variables:
   - `NEXT_PUBLIC_API_URL` — Your FastAPI backend URL
   - `NEXT_PUBLIC_WS_URL` — WebSocket URL

### Build for Production

```bash
npm run build
npm start
```

## Tech Stack

- Next.js 14 (App Router)
- React 18 + TypeScript
- TailwindCSS
- Recharts for charts
- SWR for data fetching
- Lucide React for icons
