"""
User-derived-key encryption-at-rest utilities.

Each file is encrypted with a random per-file key (envelope encryption). That per-file
key is then wrapped by a key derived from the user's password via PBKDF2-HMAC-SHA256.
The wrapped key is stored in the DB; the file ciphertext is stored in object storage.

THREAT MODEL — this is NOT zero-knowledge / end-to-end encryption.
Derivation, encryption and decryption all run SERVER-SIDE, so the plaintext file and
the user's password both pass through the server at upload/download time. This protects
data AT REST (a stolen DB or object-storage dump is useless without the user's password)
but does NOT protect against a compromised server or a privileged operator who can
observe a request in flight. Do not advertise this as "zero-knowledge" or "not even we
can read them" — to make those claims true, key derivation and encryption must move to
the client so plaintext never reaches the server.

KEY ROTATION — because the wrapping key is derived from the password, changing the
password requires re-wrapping every stored file key (see ``rewrap_file_key``). A
password *reset* (no old password available) leaves previously-encrypted files
unrecoverable by design; that is the inherent trade-off of user-held keys.
"""
import os
import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# PBKDF2 work factor. New wraps use the OWASP-aligned cost; documents wrapped before it was
# raised are still readable via the fallback in _unwrap_file_key — so raising this does NOT
# strand old data (that was the trap flagged in the audit).
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 100_000


def derive_key_from_password(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    """
    Derive a "Key-Wrapping Key" from the user's password using PBKDF2-HMAC-SHA256.

    New wraps use PBKDF2_ITERATIONS; pass LEGACY_PBKDF2_ITERATIONS to derive the key for
    documents that were wrapped before the cost was raised.

    Args:
        password: User's password (plain text, from login session)
        salt: Salt bytes (unique per user, stored in the database)
        iterations: PBKDF2 iteration count (defaults to the current cost)

    Returns:
        bytes: 32-byte urlsafe-base64 key suitable for Fernet
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend()
    )
    key = kdf.derive(password.encode('utf-8'))
    return base64.urlsafe_b64encode(key)


def _unwrap_file_key(wrapped_file_key: bytes, password: str, salt: bytes) -> bytes:
    """
    Unwrap a Fernet-wrapped file key, trying the current then the legacy PBKDF2 cost.

    This lets us raise the KDF cost for new documents while still decrypting ones wrapped at
    the old 100k cost. Raises InvalidToken if neither works (wrong password / corrupted /
    orphaned by an earlier reset).
    """
    for iterations in (PBKDF2_ITERATIONS, LEGACY_PBKDF2_ITERATIONS):
        try:
            kek = derive_key_from_password(password, salt, iterations)
            return Fernet(kek).decrypt(wrapped_file_key)
        except InvalidToken:
            continue
    raise InvalidToken("Could not unwrap the file key with any known KDF cost.")

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
        # Unwrap the file key (tries current then legacy PBKDF2 cost), then decrypt the file.
        file_key = _unwrap_file_key(encrypted_file_key, user_password, user_salt)
        return Fernet(file_key).decrypt(encrypted_file_data)
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


def rewrap_file_key(
    encrypted_file_key_b64: str,
    old_password: str,
    new_password: str,
    user_salt: bytes,
) -> str:
    """
    Re-wrap a stored (base64) file key from the old password to the new one.

    Called on password CHANGE so the user keeps access to documents that were encrypted
    under the previous password. Only the wrapping key (derived from the password) is
    rotated — the per-file content key is unchanged, so the file ciphertext already in
    object storage does NOT need to be rewritten.

    Args:
        encrypted_file_key_b64: The stored, base64-encoded wrapped file key.
        old_password: The user's current password (verified by the caller).
        new_password: The user's new password.
        user_salt: The user's encryption salt (raw bytes).

    Returns:
        str: The new base64-encoded wrapped file key, to persist in place of the old one.

    Raises:
        InvalidToken / ValueError / binascii.Error: if the old password cannot unwrap the
        key (e.g. it was already orphaned by an earlier password reset). Callers should
        catch this and skip-and-log rather than overwrite the row with a bad value.
    """
    wrapped = base64.b64decode(encrypted_file_key_b64.encode("utf-8"))
    file_key = _unwrap_file_key(wrapped, old_password, user_salt)  # tries current + legacy cost
    new_kek = derive_key_from_password(new_password, user_salt)     # re-wrap at the current cost
    new_wrapped = Fernet(new_kek).encrypt(file_key)
    return base64.b64encode(new_wrapped).decode("utf-8")

