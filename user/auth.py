# auth.py
from datetime import datetime, timedelta
import os
import jwt
from fastapi import HTTPException

SECRET = os.getenv("JWT_SECRET", "gegegegegehahahaha")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

def create_access_token(subject: str, role: str, expires_delta: int = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=(expires_delta or ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        return {"username": payload.get("sub"), "role": payload.get("role")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
