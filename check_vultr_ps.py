import paramiko

def check_processes():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect('66.42.118.26', port=22, username='root', password='M,w5_=k@eHA!ecEK')
        stdin, stdout, stderr = ssh.exec_command('ps aux | grep python')
        output = stdout.read().decode('utf-8')
        print(output)
    except Exception as e:
        print(f"SSH Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    check_processes()
