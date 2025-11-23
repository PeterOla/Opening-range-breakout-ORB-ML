Set-Location -LiteralPath 'C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)'

# For quick enforcement:
$patterns = @('equity_curve_*.csv', 'trade_log_*.csv', 'master_comparison_*.csv', 'master_comparison_lstm.csv')
$dest = 'ml_orb_5m\results\backtest'
if (-Not (Test-Path $dest)) { New-Item -Path $dest -ItemType Directory | Out-Null }

$rootMoved = 0
foreach ($p in $patterns) {
    $files = Get-ChildItem -Path '.' -Filter $p -File -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        Write-Output "Moving: $($f.Name) -> $dest"
        Move-Item -LiteralPath $f.FullName -Destination (Join-Path $dest $f.Name) -Force -Verbose
        $rootMoved += 1
    }
}

# Also check for '.png' images used as equity images in repo root
$imgPattern = 'equity_curve_*.png'
$imgFiles = Get-ChildItem -Path '.' -Filter $imgPattern -File -ErrorAction SilentlyContinue
foreach ($ifile in $imgFiles) {
    Write-Output "Moving image: $($ifile.Name) -> $dest"
    Move-Item -LiteralPath $ifile.FullName -Destination (Join-Path $dest $ifile.Name) -Force -Verbose
    $rootMoved += 1
}

if ($rootMoved -gt 0) { Write-Output "Done. Moved $rootMoved items to $dest" } else { Write-Output "No result files found in repo root." }
