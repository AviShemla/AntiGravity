import subprocess
import os

ps_script = """
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"C:\\Users\\AviShemla\\AntiGravity\\run_weekend_backtest.bat`"" -WorkingDirectory "C:\\Users\\AviShemla\\AntiGravity"
Set-ScheduledTask -TaskName "AntiGravity_Weekend_Backtest" -Action $action

$action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"C:\\Users\\AviShemla\\AntiGravity\\run_pipeline.bat`"" -WorkingDirectory "C:\\Users\\AviShemla\\AntiGravity"
Set-ScheduledTask -TaskName "AntiGravity_Daily_Pipeline" -Action $action2
"""

with open("fix_task.ps1", "w") as f:
    f.write(ps_script)

subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "fix_task.ps1"])
print("Tasks fixed and WorkingDirectory attached!")
