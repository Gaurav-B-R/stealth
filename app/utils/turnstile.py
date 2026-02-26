"""
Cloudflare Turnstile verification utility
"""
import os
import requests
from typing import Optional
from fastapi import HTTPException, status

# Cloudflare Turnstile verification endpoint
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_FLAG_NAMES = ("TURNSTILE", "TURNSTILE_ENABLED")
TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSY_VALUES = {"0", "false", "no", "off", "disabled"}


def _parse_optional_bool(raw_value: Optional[str]) -> Optional[bool]:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if value in TRUTHY_VALUES:
        return True
    if value in FALSY_VALUES:
        return False
    return None


def is_turnstile_enabled() -> bool:
    """
    Return True when Turnstile checks should run.

    Supported env toggles:
    - TURNSTILE=ON/OFF (preferred)
    - TURNSTILE_ENABLED=true/false (backward-compatible alias)

    If neither toggle is set (or value is invalid), defaults to enabled.
    """
    for env_name in TURNSTILE_FLAG_NAMES:
        parsed = _parse_optional_bool(os.getenv(env_name))
        if parsed is not None:
            return parsed
    return True

def verify_turnstile_token(token: str, remote_ip: Optional[str] = None) -> bool:
    """
    Verify a Cloudflare Turnstile token with Cloudflare's API.
    
    Args:
        token: The Turnstile token to verify
        remote_ip: Optional client IP address for additional verification
        
    Returns:
        bool: True if token is valid, False otherwise
        
    Raises:
        HTTPException: If verification fails or secret key is not configured
    """
    if not is_turnstile_enabled():
        return True

    secret_key = os.getenv("TURNSTILE_SECRET_KEY")
    
    if not secret_key:
        # In development, allow bypassing Turnstile if not configured
        if os.getenv("ENVIRONMENT", "production").lower() == "development":
            print("Warning: TURNSTILE_SECRET_KEY not set. Skipping Turnstile verification in development mode.")
            return True
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Turnstile verification is not properly configured"
        )
    
    if not token:
        return False
    
    # Prepare verification request
    data = {
        "secret": secret_key,
        "response": token
    }
    
    if remote_ip:
        data["remoteip"] = remote_ip
    
    try:
        response = requests.post(TURNSTILE_VERIFY_URL, data=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Check if verification was successful
        if result.get("success"):
            return True
        else:
            # Log error codes for debugging
            error_codes = result.get("error-codes", [])
            if error_codes:
                print(f"Turnstile verification failed: {error_codes}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"Error verifying Turnstile token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Turnstile token"
        )
