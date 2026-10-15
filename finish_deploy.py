import sys
import time
import paramiko

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("45.147.31.53", port=22, username="root", password="MtQC0L0Nrh81")

def run(cmd):
    print(f"\n--> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out.strip():
        print(out.strip()[:1000])
    if err.strip():
        print("ERR:", err.strip()[:1000])

# 1. Test packages
run("/root/NEWS/venv/bin/python -c 'import fastapi, moviepy, edge_tts, PIL, trafilatura, uvicorn; print(\"ALL PACKAGES IMPORTED SUCCESSFULLY!\")'")

# 2. Configure systemd
service_text = """[Unit]
Description=News Video Generator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/NEWS
ExecStart=/root/NEWS/venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
sftp = ssh.open_sftp()
with sftp.file("/etc/systemd/system/news-generator.service", "w") as f:
    f.write(service_text)
sftp.close()

# 3. Reload and start
run("systemctl daemon-reload")
run("systemctl enable news-generator")
run("systemctl restart news-generator")

time.sleep(3)

# 4. Check status and curl
run("systemctl status news-generator --no-pager")
run("curl -s http://127.0.0.1:8501/api/queue")

ssh.close()
print("\nFINISHED!")
