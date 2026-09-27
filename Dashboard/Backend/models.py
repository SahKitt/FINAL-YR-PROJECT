# models.py
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field

# ========== Auth Models ==========
class UserRegister(BaseModel):
    organization_name: str
    email: EmailStr
    physical_address: str
    contact_phone: str
    company_reg_no: str
    kra_pin: str
    password: str

class UserOut(BaseModel):
    user_id: str
    email: str
    organization_name: Optional[str] = ""
    physical_address: Optional[str] = ""
    contact_phone: Optional[str] = ""
    company_reg_no: Optional[str] = ""
    kra_pin: Optional[str] = ""
    role: str
    source_system: Optional[str] = ""
    status: str
    created_at: datetime

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    organization_name: Optional[str] = ""

class UserResponse(BaseModel):
    user_id: str
    email: str
    role: str
    source_system: Optional[str] = ""

class UpdateProfileRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None

# ========== Dashboard Stats Models ==========
class DashboardStats(BaseModel):
    totalTransactions: int
    totalFlagged: int
    highRisk: int
    lowRisk: int

# ========== Transaction Models ==========
class TransactionSummary(BaseModel):
    id: str
    amount: float
    date: Optional[datetime] = None
    risk: str        
    flagged: bool
    description: Optional[str] = ""
    merchant: Optional[str] = ""
    sender: Optional[str] = ""
    receiver: Optional[str] = ""

class TransactionDetail(BaseModel):
    transaction_id: str
    timestamp: datetime
    amount: float
    currency: str
    source_system: str
    transaction_type: str
    status: str
    total_risk_score: int
    risk_level: str
    triggered_rules: Optional[List[Dict[str, Any]]] = []
    sender_id: Optional[str] = None
    receiver_id: Optional[str] = None
    device_id: Optional[str] = None
    ip_address: Optional[str] = None
    country_code: Optional[str] = None
    merchant_category: Optional[str] = None
    card_type: Optional[str] = None
    channel_type: Optional[str] = None
    is_flagged: bool = False
    needs_review: bool = False
    auto_block: bool = False
    description: Optional[str] = None
    merchant_name: Optional[str] = None

# ========== Recommendation Models ==========
class Recommendation(BaseModel):
    id: str                # transaction_id
    recommendation: str

class RecommendationsResponse(BaseModel):
    high: List[Recommendation]
    low: List[Recommendation]

# ========== Graph Data Model ==========
class GraphDataPoint(BaseModel):
    name: str     
    value: float 

# ========== Rule Engine Models ==========
class RuledTransaction(BaseModel):
    transaction_id: str
    timestamp: datetime
    amount: float
    currency: str
    source_system: str
    transaction_type: str
    status: str
    total_risk_score: int = Field(..., ge=0, le=10)
    risk_level: str   
    triggered_rules: Optional[List[Dict[str, Any]]] = []
    sender_id: Optional[str] = None
    receiver_id: Optional[str] = None
    device_id: Optional[str] = None
    ip_address: Optional[str] = None
    country_code: Optional[str] = None
    merchant_category: Optional[str] = None
    card_type: Optional[str] = None
    channel_type: Optional[str] = None
    is_flagged: bool = False
    needs_review: bool = False
    auto_block: bool = False
    description: Optional[str] = None
    merchant_name: Optional[str] = None
    processing_start_time: Optional[datetime] = None
    processing_end_time: Optional[datetime] = None
    processing_duration_ms: Optional[float] = None
    raw_transaction_id: Optional[str] = None
    ingested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    normalized_id: Optional[str] = None
    session_id: Optional[str] = None
    terminal_id: Optional[str] = None
    user_agent: Optional[str] = None

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }