# ORB Backtest vs Live Comparison Report

**Generated**: 2026-01-29  
**Report Purpose**: Compare live trading symbol selection with backtest predictions

---

## Summary

| Date | Backtest Top 5 | Live Watchlist | Match Rate | Notes |
|------|----------------|----------------|------------|-------|
| **2026-01-26** | DCOM, LE, STC, VWAV | LE, LRHC, VWAV, STC, DCOM | 4/5 (80%) | Live had LRHC (not in backtest) |
| **2026-01-27** | AVAV, BNAI, GABC, LPTH, MPWR | GABC, MPWR, BNAI | 3/5 (60%) | Backtest had AVAV, LPTH (not in live) |
| **2026-01-28** | AVAV, LE, LPTH, MPWR, NBHC | LPTH, NBHC, AVAV, BNAI, SLE | 3/5 (60%) | Mixed discrepancies |
| **2026-01-29** | *(pending - market open)* | VELO, CMPR, HAFC, ENVA, BFH | - | All 5 hit stop losses (-$33.73) |

---

## Aggregated Statistics (2026-01-26 to 2026-01-28)

- **Total symbols matched**: 10
- **Symbols only in live**: 3 (LRHC, BNAI, SLE)
- **Symbols only in backtest**: 4 (AVAV, LPTH, LE, MPWR)
- **Overall match rate**: ~59% (10/17 unique symbols across 3 days)

---

## Live Trading Outcomes

### 2026-01-29 (All Stops Hit)
| Symbol | Entry | Stop Reason | PNL |
|--------|-------|-------------|-----|
| VELO | $15.90 | Stop @ 15.28 | -$8.10 |
| CMPR | $81.47 | Stop @ 79.42 | -$6.16 |
| HAFC | $26.22 | Stop @ 25.86 | -$2.86 |
| ENVA | $163.46 | Stop @ 161.90 | -$1.56 |
| BFH | $73.40 | Stop @ 72.60 | -$2.39 |
| **Total** | | | **-$33.73** (incl. $10.89 fees) |

---

## Discrepancy Analysis

### Possible Causes of Selection Mismatch

1. **News/Sentiment Filtering** - Live pipeline filters by `positive_score >= 0.9`, which may exclude symbols that pass backtest filters
2. **Real-time vs Cached RVOL** - Live calculates RVOL at 9:35 ET from real-time data; backtest uses cached bars
3. **Data Freshness** - Live uses the most recent pre-market data; backtest uses T-1 daily data
4. **Universe Cutoff** - Live builds universe at 9:30 ET; backtest may use different timing

### Symbols with Repeated Discrepancies

| Symbol | Pattern |
|--------|---------|
| LRHC | In live (01-26) but not backtest |
| BNAI | In live (01-27, 01-28) but not always in backtest |
| SLE | In live (01-28) but not backtest |
| AVAV | In backtest (01-27, 01-28) but not always in live |
| LPTH | In backtest (01-27, 01-28) but not always in live |

---

## Backtest Performance (2026-01-26 to 2026-01-28)

- **Total Trades**: 14
- **Final Equity**: $1,442.54 (started $1,500)
- **Return**: -3.8%

---

## Recommendations

1. **Add Universe Snapshot** - Save the full candidate universe with RVOL at 9:35 ET each day for exact comparison
2. **Log Selection Criteria** - Log the filter values (ATR, volume, direction, RVOL) for each candidate
3. **Run EOD Backtest** - At market close each day, run backtest for that day and compare automatically

---

## Files Generated

- `ORB_Live_Trader/backtest/pipeline/` - Self-contained data pipeline
- `ORB_Live_Trader/backtest/data/runs/compound/compare_2026/` - Backtest trades
- `ORB_Live_Trader/backtest/comparison_report.txt` - Detailed comparison output
