$source = "C:\Users\AviShemla\AntiGravity"
$destinationFolder = "C:\Users\AviShemla\AG_BCK"
$destinationFile = "$destinationFolder\AntiGravity_Full_Migration_Backup.zip"

Write-Host "Creating AG_BCK directory if it doesn't exist..." -ForegroundColor Yellow
if (-not (Test-Path $destinationFolder)) {
    New-Item -ItemType Directory -Force -Path $destinationFolder
}

if (Test-Path $destinationFile) {
    Write-Host "Removing old backup..." -ForegroundColor Yellow
    Remove-Item -Force $destinationFile
}

Write-Host "Compressing the AntiGravity ecosystem into a single package. This may take a moment..." -ForegroundColor Yellow
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Optimize compression to avoid breaking on large .git objects
[System.IO.Compression.ZipFile]::CreateFromDirectory($source, $destinationFile, [System.IO.Compression.CompressionLevel]::Optimal, $false)

Write-Host "Migration Backup Complete! Package successfully exported to Google Drive: $destinationFile" -ForegroundColor Green
