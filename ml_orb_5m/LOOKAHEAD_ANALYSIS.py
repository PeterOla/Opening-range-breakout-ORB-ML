"""
LOOKAHEAD BIAS ANALYSIS
========================

Feature Extraction Timeline Analysis
-------------------------------------

Trade Entry: Earliest = 09:35, Most = 09:40 or later
Feature Calculation: Uses ONLY opening range (09:30-09:35)

DETAILED ANALYSIS:
==================

1. OPENING RANGE METRICS (or_open, or_high, or_low, or_close, or_volume, etc.)
   - Data used: 09:30-09:35 bars ONLY
   - Entry time: 09:35 or later (typically 09:40+)
   - Lookahead? NO ✅
   - Reason: OR completes at 09:35, entry is at/after 09:35

2. GAP FEATURES (overnight_gap, gap_pct, gap_direction, gap_filled_by_or)
   - Data used: 
     * Previous day's close (day before target date)
     * Current day's open (09:30)
     * Gap fill check uses ONLY first 5-min bar (09:30-09:35)
   - Entry time: 09:35 or later
   - Lookahead? NO ✅
   - Reason: All gap data known by 09:35

3. CANDLESTICK PATTERNS (is_doji, is_hammer, is_shooting_star, is_marubozu)
   - Data used: OR bars (09:30-09:35)
   - Entry time: 09:35 or later
   - Lookahead? NO ✅
   - Reason: Patterns calculated from completed OR

4. MOMENTUM INDICATORS (roc_5min, rsi_5min)
   - Data used: First 3 bars = first 15 minutes (09:30-09:45)
   - Entry time: Some trades at 09:35, 09:40
   - Lookahead? POTENTIAL ISSUE ⚠️
   - Issue: If entry at 09:35 or 09:40, we're using bars up to 09:45
   - FIX NEEDED: Should use ONLY bars BEFORE entry time

5. PRICE LEVELS (distance_to_prev_high, distance_to_prev_low)
   - Data used:
     * Previous day high/low (from dates < target_date)
     * Current price from OR close (09:35)
   - Entry time: 09:35 or later
   - Lookahead? NO ✅
   - Reason: Previous day data is historical, OR close known at entry

6. ATR-NORMALIZED FEATURES (or_range_vs_atr, atr_14, gap_vs_atr)
   - Data used: 
     * ATR(14) from 14 days BEFORE target date
     * OR range size (09:30-09:35)
   - Entry time: 09:35 or later
   - Lookahead? NO ✅
   - Reason: ATR from previous 14 days, OR range complete

CRITICAL ISSUE FOUND:
======================

**momentum_features = calculate_momentum_indicators(bars_today[:3])**
- Uses first 3 bars = 09:30-09:45 (15 minutes)
- Some trades enter at 09:35 or 09:40
- This means we're using future data (bars after entry)

EXAMPLE VIOLATION:
- Trade enters at 09:35
- We calculate RSI/ROC using bars through 09:45
- This is 10 minutes of FUTURE data = LOOKAHEAD BIAS

SOLUTIONS:
==========

Option 1: Filter bars by entry_time
- Only use bars where timestamp < entry_time
- Most accurate but requires entry_time in feature extraction

Option 2: Use only OR bars (09:30-09:35)
- Calculate momentum from just the opening range
- Safe for all trades since OR completes before earliest entry

Option 3: Remove momentum features
- Simplest solution if momentum not critical

RECOMMENDATION:
===============
Use Option 2: Calculate momentum from OR bars ONLY (09:30-09:35)

Change:
  momentum_features = calculate_momentum_indicators(bars_today[:3])  # Uses 15 min
To:
  or_bars = bars_today[bars_today['timestamp'].dt.time < pd.to_datetime("09:35").time()]
  momentum_features = calculate_momentum_indicators(or_bars)  # Uses OR only

This ensures:
- All features use ONLY data from 09:30-09:35
- All trades enter at 09:35 or later
- Zero lookahead bias
"""
print(__doc__)
