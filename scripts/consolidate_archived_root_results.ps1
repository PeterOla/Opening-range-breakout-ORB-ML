# Move archived root files from ml_orb_5m/results/backtest_top20/archived_from_root into backtest_top20/ with safe renaming if needed
Set-Location -LiteralPath 'C:\Users\Olale\Documents\Codebase\Quant\Opening Range Breakout (ORB)'
$srcDir = 'ml_orb_5m\results\backtest_top20\archived_from_root'
$dstDir = 'ml_orb_5m\results\backtest_top20'

if (-Not (Test-Path $srcDir)) {
    Write-Output "No archived_from_root directory found ($srcDir). Nothing to consolidate."
    exit 0
}

$files = Get-ChildItem -Path $srcDir -File -ErrorAction SilentlyContinue

foreach ($file in $files) {
    $targetPath = Join-Path $dstDir $file.Name
    if (Test-Path $targetPath) {
        # Compare sizes; if equal, delete source; if different, move with suffix
        $sourceSize = (Get-Item $file.FullName).Length
        $targetSize = (Get-Item $targetPath).Length
        if ($sourceSize -eq $targetSize) {
            Write-Output "Duplicate (same size) found; removing archived copy: $($file.Name)"
            Remove-Item -LiteralPath $file.FullName -Force -Verbose
        } else {
            $timestamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
            $newName = [IO.Path]::GetFileNameWithoutExtension($file.Name) + "_root_dup_$timestamp" + $file.Extension
            $newTarget = Join-Path $dstDir $newName
            Write-Output "Target exists and differs; moving $($file.Name) -> $newTarget"
            Move-Item -LiteralPath $file.FullName -Destination $newTarget -Force -Verbose
        }
    } else {
        Write-Output "Moving $($file.Name) -> $targetPath"
        Move-Item -LiteralPath $file.FullName -Destination $targetPath -Force -Verbose
    }
}

# Remove the archived_from_root directory if empty
if ((Get-ChildItem $srcDir -Recurse | Measure-Object).Count -eq 0) {
    Write-Output "Removing empty directory: $srcDir"
    Remove-Item -LiteralPath $srcDir -Force -Recurse -Verbose
}

Write-Output "Consolidation complete."
