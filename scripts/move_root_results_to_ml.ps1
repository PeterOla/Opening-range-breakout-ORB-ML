# Move any misplaced backtest result CSV/PNG files from repo root to ml_orb_5m/results/backtest_top20/archive
Set-Location -LiteralPath 'C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)'

$destDir = 'ml_orb_5m\results\backtest_top20\archived_from_root'
if (-Not (Test-Path $destDir)) {
    New-Item -Path $destDir -ItemType Directory | Out-Null
}

# Patterns to move
$patternList = @(
    'equity_curve_*.csv',
    'trade_log_*.csv',
    'master_comparison_lstm.csv',
    'equity_curve_*.png',
    'trade_log_*.png'
)

foreach ($pattern in $patternList) {
    $found = Get-ChildItem -LiteralPath '.' -Filter $pattern -File -ErrorAction SilentlyContinue
    if ($found) {
        foreach ($file in $found) {
            $newName = ($file.BaseName -replace '%', 'pct') + $file.Extension
            $newPath = Join-Path $destDir $newName
            Write-Output "Moving $($file.Name) -> $newPath"
            Move-Item -LiteralPath $file.FullName -Destination $newPath -Force -Verbose
        }
    }
}

# Also move 'master_comparison_lstm.csv' if present
if (Test-Path 'master_comparison_lstm.csv') {
    Move-Item -LiteralPath 'master_comparison_lstm.csv' -Destination (Join-Path $destDir 'master_comparison_lstm.csv') -Force -Verbose
}

Write-Output "Done. Files moved to $destDir"
