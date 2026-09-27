from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import hmac
import os
from dotenv import load_dotenv

load_dotenv()

security = HTTPBearer()
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Build a signed JWT containing the supplied data and an expiry claim.
       If no expires_delta is given, the token lives for one hour."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=1)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Decode a Bearer token and return its payload. Returns 401 when the token
       is invalid or expired."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def verify_webhook_signature(payload: bytes, signature: str, secret_key: str) -> bool:
    """Compare the HMAC‑SHA256 signature of the raw payload with the provided
       signature. Uses constant‑time comparison to avoid timing attacks."""
    if not signature or not secret_key:
        return False
    expected_signature = hmac.new(secret_key.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected_signature)