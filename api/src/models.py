from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class SourceType(str, Enum):
    """Allowed sources for transaction polling."""
    bank = "bank"
    mpesa = "mpesa"
    airtel = "airtel"
    wallet = "wallet"
    unknown = "unknown"

# ---------- Request / Response ----------
class PollingRequest(BaseModel):
    """Incoming request body for the /ingest/poll endpoint.
       Optionally accepts custom Supabase credentials per request."""
    source: SourceType
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int
    filters: Optional[Dict[str, Any]] = None
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = None

class PollingResponse(BaseModel):
    """Response returned after a successful poll, listing the fetched transactions."""
    source: SourceType
    count: int
    transactions: List[Dict[str, Any]]
    next_cursor: Optional[str] = None
    has_more: bool = False
    execution_time_ms: float

class HealthCheck(BaseModel):
    """Model for the /health endpoint response."""
    status: str
    timestamp: datetime
    version: str
    sources: Dict[str, bool]