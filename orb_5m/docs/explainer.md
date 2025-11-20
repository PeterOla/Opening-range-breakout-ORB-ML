# ORB Strategy — Plain English Explainer (ADHD-friendly)

Short version: We trade early breakouts only when a stock is clearly “in play,” use a tight, fixed stop (based on ATR), and exit by end of day.

## What this is
- A simple day-trading strategy called Opening Range Breakout (ORB).
- Uses the first 5 minutes to set a range (high/low).
- Enters ONLY in the direction of the first 5-minute candle.
- Focuses on “Stocks in Play” (unusually active stocks) using Relative Volume.

## 30‑second cheat sheet
- Time window: 9:30–9:35 ET defines the opening range.
- Direction filter:
  - First 5-min candle up (close > open): only look for long above the range high.
  - First 5-min candle down (close < open): only look for short below the range low.
  - Doji (open = close): skip.
- Entry: Stop order at the 5-min high (long) or 5-min low (short) in the allowed direction.
- Stop loss: 10% of 14‑day ATR from your entry.
- Exit: Close at end of day if not stopped.
- Position sizing: Risk ~1% of your account per trade; max leverage 4x.
- Trade only: Top 20 stocks by opening-range Relative Volume (≥ 1.0 / 100%).
- Fees (for backtests): $0.0035 per share (typical baseline).

## What is “Relative Volume” (RVOL)?
- It compares today’s volume to typical volume.
- Here we care about the first 5 minutes only.
- Simple idea: If the first 5 minutes traded way more shares than usual → the stock is likely “in play.”
- We only trade if RVOL ≥ 1.0 (100%) and prioritize the top 20 by RVOL.
  - Opening‑range RVOL formula (plain): first 5‑min volume today ÷ average of the first 5‑min volumes over the last 14 trading days.
    - RVOL = 1.0 means “normal” activity; > 1.0 means unusually active.

## Why this might work
- Early big volume often means strong interest (news, earnings, catalysts).
- The opening range can signal the day’s imbalance (demand vs. supply).
- Tight stop based on ATR keeps losses small while letting winners run intraday.

## What you need
- Data: 1-minute OHLCV bars for precise stop detection (now available); 5-minute bars also available as fallback.
- Software: Backtesting code (Python/MATLAB/etc.).
- Broker (for live): Able to place stop orders and close by end of day.

## Study scope and key results (from the paper)
- Scope: ~7,000 US stocks from 2016–2023 (NYSE + Nasdaq), intraday 1‑min data.
- Data quality: survivorship‑bias‑free (includes delisted names); intraday data unadjusted for splits/dividends.
- Costs: $0.0035/share commission modeled.
- Base 5‑min ORB (no RVOL filter):
  - Total return ≈ 29%, Sharpe ≈ 0.48, MDD ≈ 13%.
- 5‑min ORB + Stocks in Play (top 20 by opening‑range RVOL ≥ 1.0):
  - Total return ≈ 1,637%, Sharpe ≈ 2.81, Alpha ≈ 36%/yr, Beta ≈ 0.
- Benchmark S&P 500 (buy & hold) same period: ≈ 198% total.
- Other time frames (15/30/60 min) were weaker than 5‑min; a COMBO of all time frames also performed well but below 5‑min alone.

## Safety first (non-negotiables)
- Use a fixed stop (10% of 14D ATR) on every trade.
- Risk ~1% per trade; respect 4x leverage cap.
- Avoid illiquid stocks (price ≥ $5, 14D avg volume ≥ 1M shares, ATR ≥ $0.50).
- Expect losing days; edge plays out over many trades.

## Quick example (numbers kept simple)
- First 5-min candle is green; high = $100, low = $98.
- Allowed direction: long only.
- Entry: Buy stop at $100 (if price breaks above).
- ATR(14) = $5 → stop = 10% of $5 = $0.50.
- If filled at $100 → stop at $99.50; exit by market close if stop not hit.

## Daily checklist
- [ ] Market is open and stable (no halts on your tickers).
- [ ] Universe filter: price ≥ $5, 14D avg vol ≥ 1M, ATR ≥ $0.50.
- [ ] Compute 5-min opening range for each candidate.
- [ ] Compute opening-range RVOL; keep RVOL ≥ 1.0.
- [ ] Select top 20 by RVOL.
- [ ] Determine direction by first 5-min candle (up = long only, down = short only, doji = skip).
- [ ] Place stop orders at range high/low in allowed direction.
- [ ] Set stop loss at 10% ATR from entry.
- [ ] Enforce position sizing (≈1% risk per trade) and 4x leverage cap.
- [ ] Flatten any open positions by 4:00 pm ET.

## Per‑trade checklist
- [ ] Direction matches the candle (no counter-trend entries).
- [ ] Entry stop level equals the 5-min high/low.
- [ ] Stop = 10% of 14D ATR from entry.
- [ ] Position size sized to ~1% risk.
- [ ] Commission modeled at $0.0035/share (for backtests).

## Glossary (very short)
- ORB: Opening Range Breakout.
- ATR: Average True Range (volatility measure); we use 14-day.
- RVOL: Relative Volume; how today’s volume compares to recent average.
- Doji: Candle with open ≈ close.

## Limitations to remember
- We have both 1-minute and 5-minute bars available for backtesting.
- 1-minute data: Matches the paper's precision for stop-loss detection and entry timing.
- 5-minute data: Faster to process but stop-loss hits are approximate (assume worst-case fill within the bar).
- Requires good intraday data quality (survivorship-bias-free, includes delistings).
- Fewer trades when markets are quiet.
- Slippage and halts can affect real results.
- Not financial advice; practice and risk control matter most.
  - Backtest results depend on data coverage/quality (e.g., delistings, unadjusted intraday) and fees; expect differences if your data/provider differs from the paper.
  - 5-minute bars have less precise entry/stop timing—may underestimate stopped trades or overestimate hold times vs 1-minute bars.