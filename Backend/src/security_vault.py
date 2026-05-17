from cryptography.fernet import Fernet
import os

# 1. Generate/Load Key (Ek baar generate karke save karlo)
KEY_FILE = "secret.key"

def load_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)
    return open(KEY_FILE, "rb").read()

def encrypt_file(file_path):
    key = load_key()
    f = Fernet(key)
    with open(file_path, "rb") as file:
        file_data = file.read()
    encrypted_data = f.encrypt(file_data)
    with open(file_path, "wb") as file:
        file.write(encrypted_data)
    print(f"🔒 {file_path} is now Encrypted.")

# Isse hum PDF reports ko download ke baad secure kar sakte hain.