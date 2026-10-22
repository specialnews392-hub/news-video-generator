import os
import sys
from pathlib import Path
import paramiko

HOST = "45.147.31.53"
USER = "root"
PASSWORD = "MtQC0L0Nrh81"
REMOTE_DIR = "/root/NEWS"
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LOCAL_DIR = Path(__file__).resolve().parent

FILES = [
    "requirements.txt",
    "services/speech_aligner.py",
    "services/tts_engine.py",
    "services/script_generator.py",
    "services/telegram_notifier.py",
    "services/thumbnail_generator.py",
    "main.py",
    "static/app.js",
    "static/index.html",
    "static/style.css",
]

def main():
    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=15)
    sftp = ssh.open_sftp()

    for rel in FILES:
        local_p = LOCAL_DIR / rel
        if not local_p.exists():
            continue
        remote_p = f"{REMOTE_DIR}/{rel.replace(chr(92), '/')}"
        print(f"Uploading: {rel} -> {remote_p}")
        sftp.put(str(local_p), remote_p)

    sftp.close()
    print("Files uploaded successfully.")

    print("\nEnsuring dependencies installed on VPS (faster-whisper)...")
    stdin, stdout, stderr = ssh.exec_command(f"{REMOTE_DIR}/venv/bin/pip install -r {REMOTE_DIR}/requirements.txt")
    pip_out = stdout.read().decode("utf-8", errors="replace")
    print(pip_out[-500:] if len(pip_out) > 500 else pip_out)

    print("\nRestarting news-generator service...")
    stdin, stdout, stderr = ssh.exec_command("systemctl restart news-generator && sleep 2 && systemctl status news-generator --no-pager")
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err.strip():
        print("ERR:", err)

    print("\nTesting Telegram endpoint on VPS...")
    stdin, stdout, stderr = ssh.exec_command('curl -s -X POST http://127.0.0.1:8501/api/telegram/test -H "Content-Type: application/json" -d "{\\"bot_token\\": \\"\\", \\"chat_id\\": \\"116707819\\", \\"server_url\\": \\"http://45.147.31.53:8501\\"}"')
    res = stdout.read().decode("utf-8", errors="replace")
    print("Telegram test response:", res)

    ssh.close()

if __name__ == "__main__":
    main()
