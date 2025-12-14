# FastAPI Backend

Production trading system backend with Alpaca integration.

## Setup

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your Alpaca credentials
```

Shares outstanding (free)
- Set `SEC_USER_AGENT` in `.env` (SEC requires a descriptive User-Agent with contact details).
- Example: `SEC_USER_AGENT="ORBResearch/1.0 your.email@example.com"`

3. **Run development server:**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

4. **Access API docs:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/positions` | GET | Get all open positions |
| `/api/positions/{ticker}` | GET | Get specific position |
| `/api/positions/{ticker}/close` | POST | Close position |
| `/api/account` | GET | Get account info |
| `/api/trades` | GET | Get trade history |
| `/api/signals` | GET | Get recent signals |
| `/api/metrics` | GET | Get performance metrics |
| `/api/kill-switch` | GET/POST | Kill switch status/toggle |
| `/api/logs` | GET | Get system logs |
| `/ws/live` | WS | Real-time updates stream |

## Deployment

### Render (Free Tier - Paper Trading)

1. Create `render.yaml` (already included)
2. Connect GitHub repo to Render
3. Auto-deploys on push to main

### Railway ($7/month - Live Trading)

```bash
railway login
railway init
railway up
```

### DigitalOcean ($6/month)

```bash
# SSH into droplet
git clone <repo>
cd prod/backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Use systemd service or Docker for production.
