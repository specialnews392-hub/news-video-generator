import os
import sys
import time
from pathlib import Path
import paramiko

HOST = "45.147.31.53"
USER = "root"
PASSWORD = "MtQC0L0Nrh81"
REMOTE_DIR = "/root/NEWS"
LOCAL_DIR = Path(r"c:\Users\mikro\Downloads\NEWS")

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

def run_cmd(ssh, cmd):
    print(f"--> [CMD]: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if out.strip():
        # print first and last few lines if output is very large
        lines = out.strip().splitlines()
        if len(lines) > 20:
            print("\n".join(lines[:5]))
            print(f"... ({len(lines) - 10} lines omitted) ...")
            print("\n".join(lines[-5:]))
        else:
            print(out.strip())
    if exit_status != 0 and err.strip():
        print(f"Error ({exit_status}): {err.strip()}")
    return exit_status, out, err

def upload_folder(sftp, local_path, remote_path):
    for item in local_path.iterdir():
        if item.name in [".git", "__pycache__", "temp", "output", "venv", ".idea", ".vscode"]:
            continue
        # Skip temporary test video and image files in root
        if item.is_file() and (item.suffix in [".mp4", ".wav", ".avi"] or (item.suffix in [".jpg", ".png"] and item.name.startswith(("crop_", "check_", "sec_", "frame_", "sub_frame_", "cv_frame_")))):
            continue
            
        r_item = f"{remote_path}/{item.name}"
        if item.is_dir():
            try:
                sftp.mkdir(r_item)
            except Exception:
                pass
            upload_folder(sftp, item, r_item)
        else:
            print(f"Uploading: {item.relative_to(LOCAL_DIR)}")
            sftp.put(str(item), r_item)

def deploy():
    print(f"=== Deploying to {HOST} ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=30)
    print("SSH Connected!")

    print("\n--- 1. Installing Ubuntu packages (ffmpeg, python3, fonts) ---")
    run_cmd(ssh, "DEBIAN_FRONTEND=noninteractive apt-get update -y")
    run_cmd(ssh, "DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv ffmpeg fonts-liberation fonts-dejavu-core git")

    print("\n--- 2. Creating remote directory ---")
    run_cmd(ssh, f"mkdir -p {REMOTE_DIR}")

    print("\n--- 3. Uploading project files ---")
    sftp = ssh.open_sftp()
    upload_folder(sftp, LOCAL_DIR, REMOTE_DIR)
    sftp.close()
    print("Files uploaded successfully!")

    print("\n--- 4. Creating virtual environment and installing python packages ---")
    run_cmd(ssh, f"python3 -m venv {REMOTE_DIR}/venv")
    run_cmd(ssh, f"{REMOTE_DIR}/venv/bin/pip install --upgrade pip")
    run_cmd(ssh, f"{REMOTE_DIR}/venv/bin/pip install -r {REMOTE_DIR}/requirements.txt")

    print("\n--- 5. Configuring systemd auto-start service ---")
    service_content = f"""[Unit]
Description=News Video Generator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
ExecStart={REMOTE_DIR}/venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    # Write service file
    sftp = ssh.open_sftp()
    with sftp.file("/etc/systemd/system/news-generator.service", "w") as f:
        f.write(service_content)
    sftp.close()

    print("\n--- 6. Starting service ---")
    run_cmd(ssh, "systemctl daemon-reload")
    run_cmd(ssh, "systemctl enable news-generator")
    run_cmd(ssh, "systemctl restart news-generator")

    time.sleep(3)
    print("\n--- 7. Checking service status ---")
    run_cmd(ssh, "systemctl status news-generator --no-pager")
    run_cmd(ssh, "curl -s http://127.0.0.1:8501/api/queue")

    ssh.close()
    print(f"\n==========================================")
    print(f"  DEPLOYMENT COMPLETE!")
    print(f"  Open in browser: http://{HOST}:8501")
    print(f"==========================================")

if __name__ == "__main__":
    deploy()
