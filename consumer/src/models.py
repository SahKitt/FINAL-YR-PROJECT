from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

class Actor(BaseModel):
    primary_id: str
    id_type: str
    name: Optional[str] = None
    secondary_ids: List[Dict[str, str]] = []

class Counterparty(BaseModel):
    primary_id: str
    id_type: str
    name: Optional[str] = None
    secondary_ids: List[Dict[str, str]] = []

class Balances(BaseModel):
    actor_before: Optional[float] = None
    actor_after: Optional[float] = None
    counterparty_float_before: Optional[float] = None
    counterparty_float_after: Optional[float] = None

class Channel(BaseModel):
    type: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    auth_method: Optional[str] = None
    proxy_vpn_indicator: Optional[bool] = None

class Device(BaseModel):
    fingerprint_hash: Optional[str] = None
    imei_hash: Optional[str] = None
    imsi_hash: Optional[str] = None
    sim_imsi_hash: Optional[str] = None
    cell_tower_id: Optional[str] = None

class Location(BaseModel):
    city: Optional[str] = None
    coordinates: Optional[str] = None
    network_mcc_mnc: Optional[str] = None

class Merchant(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    category_code: Optional[str] = None
    storefront_url: Optional[str] = None
    checkout_type: Optional[str] = None
    shipping_country: Optional[str] = None
    shipping_address_status: Optional[str] = None
    item_quantity: Optional[int] = None

class Agent(BaseModel):
    number: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    float_before: Optional[float] = None
    float_after: Optional[float] = None

class ATM(BaseModel):
    hardware_id: Optional[str] = None
    bank_operator: Optional[str] = None
    coordinates: Optional[str] = None

class Loan(BaseModel):
    facility_id: Optional[str] = None
    principal: Optional[float] = None
    fee: Optional[float] = None
    net_credit: Optional[float] = None
    parent_trigger_receipt: Optional[str] = None
    sub_action: Optional[str] = None

class Remittance(BaseModel):
    direction: Optional[str] = None
    source_currency: Optional[str] = None
    source_amount: Optional[float] = None
    exchange_rate: Optional[float] = None
    net_local_amount: Optional[float] = None
    sender_raw: Optional[str] = None

class Airtime(BaseModel):
    purchase_value: Optional[float] = None
    bonus_awarded: Optional[float] = None
    target_msisdn: Optional[str] = None
    airtel_target_flag: Optional[bool] = None
    purchase_intent: Optional[str] = None

class Dispute(BaseModel):
    original_txn_id: Optional[str] = None
    amount: Optional[float] = None
    reason_code: Optional[str] = None
    trigger_source: Optional[str] = None
    merchant_negative_balance_allowed: Optional[bool] = None

class Bulk(BaseModel):
    corporate_client_id: Optional[str] = None
    profile_name: Optional[str] = None
    batch_recipient_count: Optional[int] = None
    total_volume: Optional[float] = None
    fee_deducted: Optional[float] = None
    float_before: Optional[float] = None
    float_after: Optional[float] = None

class BankDetails(BaseModel):
    card_bin: Optional[str] = None
    card_last_four: Optional[str] = None
    billing_zip: Optional[str] = None
    deposit_method: Optional[str] = None
    check_micr_line: Optional[str] = None
    mobile_image_metadata_hash: Optional[str] = None
    receiver_bank_code: Optional[str] = None
    network_reference_number: Optional[str] = None

class WalletDetails(BaseModel):
    funding_source_type: Optional[str] = None
    funding_institution_name: Optional[str] = None
    card_token_or_masked_pan: Optional[str] = None
    payout_speed: Optional[str] = None
    destination_bank_routing_no: Optional[str] = None
    destination_bank_account_no_hash: Optional[str] = None
    payout_instrument_id: Optional[str] = None

class Risk(BaseModel):
    score: Optional[int] = None
    level: Optional[str] = None
    flags: List[str] = []
    rules_triggered: List[str] = []
    review_required: Optional[bool] = False
    processed_at: Optional[datetime] = None

class UnifiedTransaction(BaseModel):
    transaction_id: str
    source_system: str
    source_transaction_type: Optional[str] = None
    normalized_timestamp: datetime
    status: str
    ledger_status: Optional[str] = None

    actor: Actor
    counterparty: Counterparty

    transaction_amount: float
    currency: str
    fee: Optional[float] = 0.0
    net_amount: Optional[float] = None
    balances: Optional[Balances] = None

    channel: Optional[Channel] = None
    device: Optional[Device] = None
    location: Optional[Location] = None

    merchant: Optional[Merchant] = None
    agent: Optional[Agent] = None
    atm: Optional[ATM] = None
    loan: Optional[Loan] = None
    remittance: Optional[Remittance] = None
    airtime: Optional[Airtime] = None
    dispute: Optional[Dispute] = None
    bulk: Optional[Bulk] = None
    bank_details: Optional[BankDetails] = None
    wallet_details: Optional[WalletDetails] = None

    metadata: Dict[str, Any] = {}
    risk: Optional[Risk] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)