from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Form, UploadFile, File, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import re
import random
from typing import Optional
from bson import ObjectId
from pydantic import BaseModel, EmailStr

from models import UserLogin, UserResponse, UpdateProfileRequest
from database import users_col, audit_logs_col

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        source_system = payload.get("source_system")
        if not user_id:
            raise HTTPException(401, "Invalid token")
        return {"user_id": user_id, "role": role, "source_system": source_system}
    except JWTError:
        raise HTTPException(401, "Invalid token")

def require_admin(current_user = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(403, "Admin required")
    return current_user

# ----------------------- Duplicate org check -----------------------
@router.get("/check-org")
async def check_org(name: str):
    """Check if an organisation with a similar name (case-insensitive) already exists."""
    existing = users_col.find_one({
        "organization_name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}
    })
    return {"exists": existing is not None}

# ----------------------- Registration -----------------------
@router.post("/register", status_code=201)
async def register(
    request: Request,
    organization_name: str = Form(...),
    email: str = Form(...),
    physical_address: str = Form(...),
    contact_phone: str = Form(...),
    company_reg_no: str = Form(...),
    kra_pin: str = Form(...),
    password: str = Form(...),
    cert_file: UploadFile = File(...),
    kra_cert_file: UploadFile = File(...)
):
    # 1. Duplicate checks
    if users_col.find_one({
        "organization_name": {"$regex": f"^{re.escape(organization_name)}$", "$options": "i"}
    }):
        raise HTTPException(400, "An organisation with this name already exists")

    if users_col.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    if users_col.find_one({"company_reg_no": company_reg_no}):
        raise HTTPException(400, "Company Registration Number already registered")

    if users_col.find_one({"kra_pin": kra_pin}):
        raise HTTPException(400, "KRA PIN already registered")

    # 2. Read file bytes & convert to base64
    import base64

    cert_bytes = await cert_file.read()
    cert_b64 = base64.b64encode(cert_bytes).decode("utf-8")
    cert_content_type = cert_file.content_type or "application/octet-stream"

    kra_bytes = await kra_cert_file.read()
    kra_b64 = base64.b64encode(kra_bytes).decode("utf-8")
    kra_content_type = kra_cert_file.content_type or "application/octet-stream"

    # 3. Hash password and build user doc
    hashed = pwd_context.hash(password)

    doc = {
        "organization_name": organization_name,
        "email": email,
        "physical_address": physical_address,
        "contact_phone": contact_phone,
        "company_reg_no": company_reg_no,
        "kra_pin": kra_pin,
        "password": hashed,
        "docs": {
            "cert_file": {
                "filename": cert_file.filename,
                "content_type": cert_content_type,
                "data": cert_b64
            },
            "kra_cert_file": {
                "filename": kra_cert_file.filename,
                "content_type": kra_content_type,
                "data": kra_b64
            }
        },
        "role": "user",
        "source_system": None,
        "status": "pending",
        "created_at": datetime.utcnow()
    }

    result = users_col.insert_one(doc)

    # ---- Audit log ----
    client_ip = request.client.host if request.client else "unknown"
    audit_logs_col.insert_one({
        "action": "registration",
        "email": email,
        "organization_name": organization_name,
        "ip": client_ip,
        "timestamp": datetime.utcnow(),
        "user_id": str(result.inserted_id)
    })

    return {
        "message": "Registration submitted. Awaiting admin approval.",
        "user_id": str(result.inserted_id)
    }

# ----------------------- Login -----------------------
@router.post("/login")
async def login(request: Request, user: UserLogin):
    db_user = users_col.find_one({"email": user.email})
    if not db_user or not pwd_context.verify(user.password, db_user["password"]):
        raise HTTPException(401, "Invalid credentials")

    status = db_user.get("status")
    if status == "pending":
        raise HTTPException(403, "Account pending approval. Please wait for admin confirmation.")
    elif status == "inactive":
        raise HTTPException(403, "Account suspended. Please contact support.")
    elif status == "rejected":
        raise HTTPException(403, "Account Not Approved. Please contact support.")
    elif status != "active":
        raise HTTPException(403, "Account status not recognized. Please contact support.")

    source_system = db_user.get("source_system", "")
    token = create_access_token({
        "sub": str(db_user["_id"]),
        "role": db_user["role"],
        "source_system": source_system
    })

    # ---- Audit log ----
    client_ip = request.client.host if request.client else "unknown"
    audit_logs_col.insert_one({
        "action": "login",
        "email": user.email,
        "ip": client_ip,
        "timestamp": datetime.utcnow(),
        "user_id": str(db_user["_id"])
    })

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(db_user["_id"]),
            "email": db_user["email"],
            "role": db_user["role"],
            "full_name": db_user.get("full_name", ""),
            "organization_name": db_user.get("organization_name", ""),
            "source_system": source_system
        }
    }

# ----------------------- Token Refresh -----------------------
@router.post("/refresh-token")
async def refresh_token(current_user: dict = Depends(get_current_user)):
    user = users_col.find_one({"_id": ObjectId(current_user["user_id"])})
    if not user:
        raise HTTPException(404, "User not found")

    token = create_access_token({
        "sub": str(user["_id"]),
        "role": user["role"],
        "source_system": user.get("source_system", "")
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(user["_id"]),
            "email": user["email"],
            "role": user["role"],
            "full_name": user.get("full_name", ""),
            "organization_name": user.get("organization_name", ""),
            "source_system": user.get("source_system", "")
        }
    }

# ----------------------- Profile Update and Me -----------------------
@router.put("/update-profile")
async def update_profile(
    update_data: UpdateProfileRequest,
    current_user = Depends(get_current_user)
):
    user_id = current_user["user_id"]
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "User not found")
    
    update_fields = {}
    
    if update_data.email and update_data.email != user["email"]:
        existing = users_col.find_one({"email": update_data.email})
        if existing:
            raise HTTPException(400, "Email already registered")
        update_fields["email"] = update_data.email
    
    if update_data.password:
        if len(update_data.password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        update_fields["password"] = pwd_context.hash(update_data.password)
    
    if not update_fields:
        return {"message": "No changes provided"}
    
    update_fields["updated_at"] = datetime.utcnow()
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})
    
    updated_user = users_col.find_one({"_id": ObjectId(user_id)})
    return {
        "user_id": str(updated_user["_id"]),
        "email": updated_user["email"],
        "role": updated_user["role"],
        "full_name": updated_user.get("full_name", ""),
        "source_system": updated_user.get("source_system", "")
    }

@router.get("/me", response_model=UserResponse)
async def me(current_user = Depends(get_current_user)):
    user = users_col.find_one({"_id": ObjectId(current_user["user_id"])})
    if not user:
        raise HTTPException(404, "User not found")
    return UserResponse(
        user_id=str(user["_id"]),
        email=user["email"],
        role=user["role"],
        source_system=user.get("source_system", "")
    )