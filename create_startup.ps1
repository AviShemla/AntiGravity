$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Start_Oracle.lnk")
$Shortcut.TargetPath = "C:\Users\AviShemla\AntiGravity\run_oracle.bat"
$Shortcut.WorkingDirectory = "C:\Users\AviShemla\AntiGravity"
$Shortcut.Save()
