# Run Batch Backtest for Sentiment Experiment (2021) - Top 5
$thresholds = @("0.6", "0.7", "0.8", "0.9", "0.95")

foreach ($t in $thresholds) {
    $runName = "Sent_Top5_2021_Thresh_$t"
    $univ = "research_2021_sentiment/universe_sentiment_$t.parquet"
    
    Write-Host "----------------------------------------------------------------"
    Write-Host "Running Backtest Top 5: $runName"
    Write-Host "Universe: $univ"
    Write-Host "----------------------------------------------------------------"

    python prod/backend/scripts/ORB/fast_backtest.py `
        --universe $univ `
        --run-name $runName `
        --start-date 2021-01-01 --end-date 2021-12-31 `
        --initial-capital 1500 --leverage 6.0 --top-n 5 `
        --side long --stop-atr-scale 0.05 `
        --comm-share 0.005 --comm-min 0.99
}
