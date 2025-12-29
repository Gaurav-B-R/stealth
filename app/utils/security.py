"""
Zero-Knowledge Encryption Utilities
Implements user-held key encryption where files are encrypted with keys
derived from the user's password. Even admins cannot decrypt files.
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """
    Derive a "Key-Wrapping Key" from the User's Password using PBKDF2.
    This key is used to encrypt/decrypt the file encryption keys.
    
    Args:
        password: User's password (plain text, from login session)
        salt: Salt bytes (should be unique per user, stored in database)
    
    Returns:
        bytes: 32-byte key suitable for Fernet encryption
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = kdf.derive(password.encode('utf-8'))
    return base64.urlsafe_b64encode(key)

def encrypt_file_with_user_password(file_bytes: bytes, user_password: str, user_salt: bytes) -> tuple:
    """
    Encrypt a file using Zero-Knowledge architecture.
    
    Workflow:
    1. Generate a random key for THIS specific file
    2. Encrypt the file content with the file key
    3. Encrypt the file key using a key derived from user's password
    4. Return encrypted file data and encrypted key
    
    Args:
        file_bytes: Raw file content to encrypt
        user_password: User's password (from login session)
        user_salt: Salt for password derivation (should be stored per user)
    
    Returns:
        tuple: (encrypted_file_data, encrypted_file_key)
            - encrypted_file_data: File encrypted with file key (store in R2)
            - encrypted_file_key: File key encrypted with user password (store in DB)
    """
    # Step 1: Generate a random key for THIS specific file
    file_key = Fernet.generate_key()
    f_file = Fernet(file_key)
    
    # Step 2: Encrypt the actual file content
    encrypted_file_data = f_file.encrypt(file_bytes)
    
    # Step 3: Derive key from user's password and encrypt the file key
    user_key_bytes = derive_key_from_password(user_password, user_salt)
    f_user = Fernet(user_key_bytes)
    encrypted_file_key = f_user.encrypt(file_key)
    
    # Step 4: Return encrypted data and encrypted key
    # Note: file_key is now discarded from memory
    return encrypted_file_data, encrypted_file_key

def decrypt_file_with_user_password(
    encrypted_file_data: bytes, 
    encrypted_file_key: bytes, 
    user_password: str, 
    user_salt: bytes
) -> bytes:
    """
    Decrypt a file using Zero-Knowledge architecture.
    
    Workflow:
    1. Derive key from user's password
    2. Decrypt the file key using user's password-derived key
    3. Decrypt the file content using the decrypted file key
    4. Return decrypted file data
    
    Args:
        encrypted_file_data: Encrypted file content from R2
        encrypted_file_key: Encrypted file key from database
        user_password: User's password (from login session)
        user_salt: Salt for password derivation (stored per user)
    
    Returns:
        bytes: Decrypted file content
    
    Raises:
        ValueError: If password is incorrect or data is corrupted
    """
    try:
        # Step 1: Derive key from user's password
        user_key_bytes = derive_key_from_password(user_password, user_salt)
        f_user = Fernet(user_key_bytes)
        
        # Step 2: Decrypt the file key using user's password-derived key
        file_key = f_user.decrypt(encrypted_file_key)
        
        # Step 3: Decrypt the file content using the decrypted file key
        f_file = Fernet(file_key)
        decrypted_file_bytes = f_file.decrypt(encrypted_file_data)
        
        return decrypted_file_bytes
        
    except Exception as e:
        # Wrong password, corrupted data, or other decryption error
        raise ValueError(f"Decryption failed: {str(e)}. This may indicate incorrect password or corrupted data.")

def generate_user_salt() -> bytes:
    """
    Generate a random salt for a user.
    This should be generated once per user and stored in the database.
    
    Returns:
        bytes: 16-byte random salt
    """
    return os.urandom(16)

def encode_salt_for_storage(salt: bytes) -> str:
    """
    Encode salt bytes to base64 string for database storage.
    
    Args:
        salt: Salt bytes
    
    Returns:
        str: Base64-encoded salt string
    """
    return base64.b64encode(salt).decode('utf-8')

def decode_salt_from_storage(salt_str: str) -> bytes:
    """
    Decode salt string from database to bytes.
    
    Args:
        salt_str: Base64-encoded salt string
    
    Returns:
        bytes: Salt bytes
    """
    return base64.b64decode(salt_str.encode('utf-8'))

