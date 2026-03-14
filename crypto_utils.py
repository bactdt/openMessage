from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash, check_password_hash

def generate_key() -> str:
    """Generates a random Fernet key (AES-128-CBC + HMAC-SHA256)."""
    return Fernet.generate_key().decode('utf-8')

def encrypt_message(plaintext: str, key: str) -> str:
    """Encrypts plaintext using the given Fernet key."""
    f = Fernet(key.encode('utf-8'))
    ciphertext = f.encrypt(plaintext.encode('utf-8'))
    return ciphertext.decode('utf-8')

def decrypt_message(ciphertext: str, key: str) -> str:
    """Decrypts the ciphertext using the given Fernet key."""
    f = Fernet(key.encode('utf-8'))
    plaintext = f.decrypt(ciphertext.encode('utf-8'))
    return plaintext.decode('utf-8')

def hash_password(password: str) -> str:
    """Hashes a password for storage."""
    return generate_password_hash(password)

def verify_password(password: str, pwhash: str) -> bool:
    """Verifies a password against a hash."""
    return check_password_hash(pwhash, password)
