from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator
from enum import Enum
from dataclasses import dataclass


class RiskLevel(str, Enum):
    """Risk levels for transactions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggeredRule(BaseModel):
    """Details of a triggered rule."""
    rule_id: str
    rule_name: str
    rule_description: str
    risk_score: int
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RuledTransaction(BaseModel):
    """Processed transaction with risk scores."""

    # ------------------------------------------------------------------
    # Core transaction fields (required)
    # ------------------------------------------------------------------
    transaction_id: str = Field(..., min_length=1)
    timestamp: datetime
    amount: float
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source_system: str = Field(..., min_length=1)
    transaction_type: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)

    # ------------------------------------------------------------------
    # Risk scoring
    # ------------------------------------------------------------------
    total_risk_score: int = Field(default=0, ge=0, le=100)
    risk_level: RiskLevel = RiskLevel.LOW
    triggered_rules: List[TriggeredRule] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Core entities
    # ------------------------------------------------------------------
    sender_id: Optional[str] = None
    receiver_id: Optional[str] = None
    sender_msisdn: Optional[str] = None
    receiver_msisdn: Optional[str] = None

    # ------------------------------------------------------------------
    # Device & network
    # ------------------------------------------------------------------
    device_id: Optional[str] = None
    device_id_hash: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    # ------------------------------------------------------------------
    # Authentication & session
    # ------------------------------------------------------------------
    authentication_method: Optional[str] = None
    login_timestamp: Optional[datetime] = None
    session_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Payment instrument
    # ------------------------------------------------------------------
    card_type: Optional[str] = None
    card_last_four: Optional[str] = None
    card_token_hash: Optional[str] = None
    card_retention_status: Optional[str] = None
    payment_type: Optional[str] = None

    # ------------------------------------------------------------------
    # Merchant / agent context
    # ------------------------------------------------------------------
    merchant_name: Optional[str] = None
    merchant_category: Optional[str] = None
    terminal_id: Optional[str] = None
    agent_msisdn: Optional[str] = None

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    country_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------
    initiated_timestamp: Optional[datetime] = None
    completion_timestamp: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Financial balances
    # ------------------------------------------------------------------
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None
    fee: Optional[float] = None

    # ------------------------------------------------------------------
    # Channel-specific flags
    # ------------------------------------------------------------------
    channel_type: Optional[str] = None
    payer_status: Optional[str] = None
    recipient_name_match: Optional[bool] = None
    shipping_address_status: Optional[str] = None
    is_foreign_atm: Optional[bool] = None
    transaction_subtype: Optional[str] = None

    # ------------------------------------------------------------------
    # Metadata & classification
    # ------------------------------------------------------------------
    description: Optional[str] = None

    # ------------------------------------------------------------------
    # Processing metrics (ML + performance)
    # ------------------------------------------------------------------
    processing_start_time: Optional[datetime] = None
    processing_end_time: Optional[datetime] = None
    processing_duration_ms: Optional[float] = None

    # ------------------------------------------------------------------
    # Audit & actions
    # ------------------------------------------------------------------
    raw_transaction_id: Optional[str] = None
    is_flagged: bool = False
    needs_review: bool = False
    auto_block: bool = False

    # ------------------------------------------------------------------
    # Authorization fields for rules
    # ------------------------------------------------------------------
    auth_response_code: Optional[str] = None
    auth_timestamp: Optional[datetime] = None
    posted_timestamp: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @validator("risk_level", pre=True, always=True)
    def set_risk_level(cls, v, values):
        """Derive risk level from total risk score.
        
        Thresholds from config (env):
          - RISK_SCORE_THRESHOLD_LOW    = 0   (0‑4  → low)
          - RISK_SCORE_THRESHOLD_MEDIUM = 8   (5‑7  → medium, 8‑14 → high)
          - RISK_SCORE_THRESHOLD_HIGH   = 15  (15+ → critical)
        """
        score = values.get("total_risk_score", 0)
        
        if score >= 15:
            return RiskLevel.CRITICAL
        if score >= 8:
            return RiskLevel.HIGH
        if score >= 5:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @validator("processing_duration_ms", always=True)
    def calculate_processing_duration(cls, v, values):
        """Compute processing time in milliseconds."""
        start = values.get("processing_start_time")
        end = values.get("processing_end_time")
        if start and end:
            return (end - start).total_seconds() * 1000
        return v

    @validator("amount")
    def handle_negative_amount(cls, v):
        """Allow negative amounts (for refunds, reversals, etc.)."""
        return v


class RuleDefinition(BaseModel):
    """Definition of a business rule."""
    rule_id: str
    rule_name: str
    description: str
    risk_score: int
    is_active: bool = True
    conditions: Dict[str, Any]
    action: str
    priority: int = 1
    category: str


class ProcessingMetrics(BaseModel):
    """Metrics for processing performance."""
    total_processed: int = 0
    total_flagged: int = 0
    total_high_risk: int = 0
    total_medium_risk: int = 0
    total_low_risk: int = 0
    avg_processing_time_ms: float = 0.0
    max_processing_time_ms: float = 0.0
    min_processing_time_ms: float = 0.0
    rules_triggered_count: Dict[str, int] = Field(default_factory=dict)
    last_processed_at: Optional[datetime] = None


@dataclass
class RuleContext:
    """Context for rule evaluation including historical data."""
    transaction: Dict[str, Any]
    historical_data: List[Dict[str, Any]]
    customer_profile: Optional[Dict[str, Any]] = None
    device_profile: Optional[Dict[str, Any]] = None