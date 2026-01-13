# Backlog & Experiments

## Optimization Experiments (Post-Top 10 Analysis)
- [x] **Regime Filter:** Tested `SPY > SMA200`. Result: DD -64.7% (Ineffective).
- [x] **Position Sizing:** Tested 0.5x Risk Scale. Result: DD -38.1% (Effective).
- [x] **Day-of-Week Optimization:** Tested Skipping Tue/Wed/Thu. Result: DD -31.6% (Very Effective but low profit).
- [x] **Stop Loss Variations:** 
    -   **Tight (5% ATR):** Profit **$1.47 Billion** (!!!), DD -33.9%, PF 1.92. (Game Changer).
    -   **Wide (20% ATR):** Profit $84k, DD -94%. (Disaster).
    -   **Combo (Risk Half + Skip Tue):** Profit $80k, DD -54%. (Mediocre).

- [x] **Stress Test (Slippage/Spread Sensitivity):**
    -   **Spread 0.2%:** Profit drops (0.05 ATR=Ruin, 0.08 ATR=$8k). Drawdown explodes (-81% to -92%).
    -   **Verdict:** BOTH 0.05 (Tight) and 0.08 (Middle) fail the stress test. They rely on "perfect" execution.

## Infrastructure & Logic
- [ ] **Verify Execution Reality:** The 5% ATR strategy relies on Stops being > Spread. Analysis shows 99.3% of trades have Stop > 0.1% Spread. Need to verify real-world spreads for Micro caps (are they < 0.3%?).
- [ ] **Deep Dive on Top 10 Selection:** Analyze if the 6th-10th best trades are actually profitable or if they just reduce variance. (Initial batch results suggest they *added* $3M profit compared to Top 5, so they are profitable).
- [ ] **Mid-Week Logic:** Why do Tuesdays perform so poorly? Investigate market reversal patterns or volume drying up mid-week.
