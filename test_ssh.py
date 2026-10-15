import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to 45.147.31.53...")
    ssh.connect("45.147.31.53", port=22, username="root", password="MtQC0L0Nrh81", timeout=15)
    print("Connected successfully!")
    stdin, stdout, stderr = ssh.exec_command("uname -a && cat /etc/os-release | grep PRETTY_NAME && lscpu | grep 'Model name'")
    print(stdout.read().decode())
    ssh.close()
except Exception as e:
    print(f"Error: {e}")
