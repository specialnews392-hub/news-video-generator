import sys
import paramiko

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("45.147.31.53", port=22, username="root", password="MtQC0L0Nrh81")

cmd = "/root/NEWS/venv/bin/pip install -r /root/NEWS/requirements.txt"
print(f"Running: {cmd}")
stdin, stdout, stderr = ssh.exec_command(cmd)

while True:
    line = stdout.readline()
    if not line:
        break
    print(line.strip())

err = stderr.read().decode('utf-8', errors='replace')
if err.strip():
    print("STDERR:\n", err.strip())

ssh.close()
