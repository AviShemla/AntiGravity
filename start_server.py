import subprocess

subprocess.Popen(
    ["C:\\Users\\AviShemla\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)
print("Server started in background with DEVNULL.")
