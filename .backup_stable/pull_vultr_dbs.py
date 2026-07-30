import paramiko
import os

print("Connecting to Vultr to pull DB files...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("66.42.118.26", port=22, username="root", password="M,w5_=k@eHA!ecEK")
sftp = ssh.open_sftp()

local_dir = r"C:\Users\AviShemla\AntiGravity\financial_data"
remote_dir = "/opt/antigravity/financial_data"

def download_folder_dbs(remote_path, local_path):
    if not os.path.exists(local_path):
        os.makedirs(local_path)
    for fileattr in sftp.listdir_attr(remote_path):
        rpath = remote_path + "/" + fileattr.filename
        lpath = os.path.join(local_path, fileattr.filename)
        import stat
        if stat.S_ISDIR(fileattr.st_mode):
            download_folder_dbs(rpath, lpath)
        else:
            if fileattr.filename.endswith(".db") or fileattr.filename.endswith(".sqlite"):
                print(f"Downloading {fileattr.filename}...")
                sftp.get(rpath, lpath)

download_folder_dbs(remote_dir, local_dir)

sftp.close()
ssh.close()
print("Vultr DB data successfully synced to local laptop!")
