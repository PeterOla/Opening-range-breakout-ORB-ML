# Ross Cameron's Day Trading Strategy (End-to-End)

## 1. Foundation: Risk Management
- **Profit-to-loss ratio target**: Always aim for at least 2:1
- **Max loss defined before entry**: Stop is set at the low of the pullback
- **Cut losses quickly**: Never hold and hope; exit when the trade invalidates
- **Scalability**: Position size can be scaled up or down, but risk is always based on entry vs. stop

## 2. Stock Selection Criteria
Ross filters the entire market daily using scanners. His five criteria:

- **Relative volume**: At least 5× the 50-day average
- **Pre-market gain**: Stock up ≥2% before the open (ideally 10%+)
- **Price range**: Between $2–$20 for higher percentage moves
- **Float**: Under 10 million shares (low supply = high volatility) (use AlphaVantage API)
- **Catalyst**: A clear news event (earnings, FDA approval, trial results, IPO, etc.)

## 3. Entry & Exit Strategy
- **Pattern used**: Bull flag candlestick pattern
- **Entry**: First candle to make a new high after a pullback
- **Stop**: Low of the pullback
- **Profit target**: Retest of high of day (ensures ≥2:1 ratio)
- **Execution**: Wait patiently for setups; average hold time is 2–3 minutes

## 4. Position Management
Adjust size based on market conditions:

- **Hot market** → increase share size, be more aggressive
- **Cold market** → reduce size, trade cautiously
- **Consistency**: Stick to the plan; avoid emotional trades (FOMO, frustration)
- **Scaling**: Start small (e.g., 100 shares) and scale up as confidence and account size grow

## 5. Daily Routine
- **Morning prep**: Check scanners for stocks meeting all five criteria
- **Focus list**: Narrow down to 3–5 stocks
- **Execution**: Trade only the best setups; avoid sideways, high-float, or non-news stocks
- **Duration**: Often trades for 30–60 minutes in the morning, then stops once goals are hit

## 6. Performance Metrics
- **Accuracy**: ~71% win rate
- **Average winner**: $1,800
- **Average loser**: $761
- **Consistency**: 76 consecutive green days; only 7 red days in 9 months
- **Scaling**: From $100–$200/day early on to $20,000/day average gains

## 7. Psychological Discipline
- **Avoid emotional hijack**: Don't let fear, anger, or FOMO override the plan
- **Positive feedback loop**: High-quality stocks → better accuracy → stronger profit/loss ratio → consistency → confidence → larger size → higher profits
- **Simulator practice**: Beginners should train in a simulator before risking real money

## 🚀 End-to-End Flow
1. **Scan market** → Apply 5 criteria
2. **Identify catalyst stock** → Confirm volume, price, float
3. **Wait for bull flag setup** → Entry = first candle to make new high
4. **Define stop & target** → Ensure ≥2:1 ratio
5. **Size position appropriately** → Adjust for market conditions
6. **Execute trade** → Hold 2–3 minutes, cut losses fast
7. **Review performance** → Track accuracy, profit/loss ratio, consistency
8. **Repeat daily routine** → Build confidence, scale gradually
