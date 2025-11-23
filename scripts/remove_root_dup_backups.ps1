Set-Location -LiteralPath 'C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)'

$src = 'ml_orb_5m\results\backtest_top20'
$backup = 'archived_nonessential\dup_backups'
if (-Not (Test-Path $backup)) { New-Item -Path $backup -ItemType Directory | Out-Null }

Write-Output "Scanning $src for '_root_dup' files..."
$files = Get-ChildItem -Path $src -Filter '*_root_dup_*' -File -Recurse -ErrorAction SilentlyContinue

if (-Not $files) {
    Write-Output "No _root_dup files found."
    exit 0
}

foreach ($file in $files) {
    $dest = Join-Path $backup $file.Name
    Write-Output "Archiving duplicate: $($file.FullName) -> $dest"
    Move-Item -LiteralPath $file.FullName -Destination $dest -Force -Verbose
}

Write-Output "Done. Moved duplicates to $backup"