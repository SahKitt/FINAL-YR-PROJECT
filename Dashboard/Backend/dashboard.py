from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from bson import ObjectId
import subprocess
import os
import signal
import requests
import threading
import base64
import httpx
import asyncio
import hashlib
from cryptography.fernet import Fernet
from fastapi.responses import Response
from pydantic import BaseModel

from database import (
    ruled_transactions_col,
    raw_transactions_col,
    users_col,
    bad_records_col,
    processed_transactions_col,
    audit_logs_col
)
from auth import get_current_user, create_access_token
from neo4j import GraphDatabase

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Encryption setup – Fernet key derived from JWT secret
def _get_fernet() -> Fernet:
    secret = os.getenv("JWT_SECRET_KEY", "fallback-secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

fernet = _get_fernet()

def encrypt_value(plain: str) -> str:
    return fernet.encrypt(plain.encode()).decode()

def decrypt_value(encrypted: str) -> str:
    return fernet.decrypt(encrypted.encode()).decode()

# ------------------------------------------------------------
def get_user_source_system(current_user: dict = Depends(get_current_user)) -> str:
    source = current_user.get("source_system")
    if not source:
        raise HTTPException(400, "User has no assigned data source. Please configure your Supabase connection first.")
    return source

# ===================== OVERVIEW STATS =====================
@router.get("/stats/overview")
async def get_overview_stats(source_system: str = Depends(get_user_source_system)):
    raw_ids = raw_transactions_col.find({"source_system": source_system}, {"transaction_id": 1})
    txn_ids = [doc["transaction_id"] for doc in raw_ids]
    if not txn_ids:
        return {"totalTransactions": 0, "totalFlagged": 0, "highRisk": 0, "lowRisk": 0, "fraudCount": 0, "normalCount": 0}

    filter_query = {"transaction_id": {"$in": txn_ids}}
    total = ruled_transactions_col.count_documents(filter_query)
    flagged = ruled_transactions_col.count_documents({**filter_query, "is_flagged": True})
    high = ruled_transactions_col.count_documents({"$or": [{**filter_query, "risk_level": "high"}, { "risk_level": "critical"}]})
    low = ruled_transactions_col.count_documents({**filter_query, "risk_level": "low"})
    fraud_count = processed_transactions_col.count_documents({**filter_query, "verdict": "fraud"})
    normal_count = processed_transactions_col.count_documents({**filter_query, "verdict": "normal"})
    
    return {
        "totalTransactions": total,
        "totalFlagged": flagged,
        "highRisk": high,
        "lowRisk": low,
        "fraudCount": fraud_count,
        "normalCount": normal_count
    }

# ===================== PROCESSED TRANSACTIONS =====================
@router.get("/processed-transactions")
async def get_processed_transactions(
    source_system: str = Depends(get_user_source_system),
    limit: int = 1000,
    skip: int = 0
):
    raw_cursor = raw_transactions_col.find(
        {"source_system": source_system},
        {"transaction_id": 1, "_id": 0}
    ).skip(skip).limit(limit)
    transaction_ids = [doc["transaction_id"] for doc in raw_cursor]
    if not transaction_ids:
        return []
    
    cursor = processed_transactions_col.find(
        {"transaction_id": {"$in": transaction_ids}},
        {
            "_id": 0,
            "transaction_id": 1,
            "timestamp": 1,
            "amount": 1,
            "currency": 1,
            "sender_id": 1,
            "receiver_id": 1,
            "ml_score": 1,
            "correlation_score": 1,
            "final_score": 1,
            "verdict": 1,
            "ml_processed_at": 1
        }
    ).sort("timestamp", -1)
    
    processed = []
    for doc in cursor:
        processed.append({
            "id": doc.get("transaction_id"),
            "amount": doc.get("amount", 0),
            "date": doc.get("timestamp").isoformat() if doc.get("timestamp") else None,
            "currency": doc.get("currency", ""),
            "sender": doc.get("sender_id", ""),
            "receiver": doc.get("receiver_id", ""),
            "mlScore": doc.get("ml_score", 0),
            "correlationScore": doc.get("correlation_score", 0),
            "finalScore": doc.get("final_score", 0),
            "verdict": doc.get("verdict", "unknown"),
            "processedAt": doc.get("ml_processed_at").isoformat() if doc.get("ml_processed_at") else None
        })
    return processed

# ===================== RULED TRANSACTIONS  =====================
@router.get("/ruled-transactions")
async def get_ruled_transactions(
    source_system: str = Depends(get_user_source_system),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 1000,
    skip: int = 0
):
    raw_cursor = raw_transactions_col.find(
        {"source_system": source_system},
        {"transaction_id": 1, "_id": 0}
    )
    transaction_ids = [doc["transaction_id"] for doc in raw_cursor]
    if not transaction_ids:
        return []

    match = {"transaction_id": {"$in": transaction_ids}}

    if start_date:
        try:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            match["timestamp"] = {"$gte": start}
        except Exception:
            pass
    if end_date:
        try:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if "timestamp" in match:
                match["timestamp"]["$lte"] = end
            else:
                match["timestamp"] = {"$lte": end}
        except Exception:
            pass

    cursor = ruled_transactions_col.find(
        match,
        {
            "_id": 0,
            "transaction_id": 1,
            "timestamp": 1,
            "amount": 1,
            "currency": 1,
            "risk_level": 1,
            "total_risk_score": 1,
            "is_flagged": 1,
            "triggered_rules": 1,
            "description": 1,
            "merchant_name": 1,
            "sender_id": 1,
            "receiver_id": 1,
            "transaction_type": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit)

    ruled_transactions = []
    for doc in cursor:
        ruled_transactions.append({
            "id": doc.get("transaction_id"),
            "amount": doc.get("amount", 0),
            "date": doc.get("timestamp").isoformat() if doc.get("timestamp") else None,
            "risk": doc.get("risk_level", "unknown"),
            "risk_score": doc.get("total_risk_score", 0),
            "flagged": doc.get("is_flagged", False),
            "triggered_rules": doc.get("triggered_rules", []),
            "description": doc.get("description", ""),
            "merchant": doc.get("merchant_name", ""),
            "sender": doc.get("sender_id", ""),
            "receiver": doc.get("receiver_id", ""),
            "transaction_type": doc.get("transaction_type", "")
        })
    return ruled_transactions

# ===================== RAW TRANSACTIONS =====================
@router.get("/transactions")
async def get_transactions(
    source_system: str = Depends(get_user_source_system),
    limit: int = 200,
    skip: int = 0
):
    cursor = raw_transactions_col.find(
        {"source_system": source_system},
        {
            "_id": 0,
            "transaction_id": 1,
            "amount": 1,
            "timestamp": 1,
            "description": 1,
            "merchant_name": 1,
            "sender_id": 1,
            "receiver_id": 1
        }
    ).sort("timestamp", -1).skip(skip).limit(limit)
    transactions = []
    for doc in cursor:
        transactions.append({
            "id": doc.get("transaction_id"),
            "amount": doc.get("amount", 0),
            "date": doc.get("timestamp").isoformat() if doc.get("timestamp") else None,
            "description": doc.get("description", ""),
            "merchant": doc.get("merchant_name", ""),
            "sender": doc.get("sender_id", ""),
            "receiver": doc.get("receiver_id", "")
        })
    return transactions

# ===================== REPORTS + RECOMMENDATIONS =====================
@router.get("/reports/recommendations")
async def get_recommendations(
    source_system: str = Depends(get_user_source_system),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    verdict: Optional[str] = None,
    limit: int = 10000
):
    raw_ids = raw_transactions_col.find(
        {"source_system": source_system},
        {"transaction_id": 1}
    )
    txn_ids = [doc["transaction_id"] for doc in raw_ids]
    if not txn_ids:
        return {"transactions": [], "summary": {
            "total_count": 0, "total_amount": 0, "avg_final_score": 0,
            "fraud_count": 0, "normal_count": 0, "false_positive_count": 0, "flagged_count": 0
        }}
    
    match = {"transaction_id": {"$in": txn_ids}}
    if start_date:
        try:
            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            match["timestamp"] = {"$gte": start}
        except:
            pass
    if end_date:
        try:
            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if "timestamp" in match:
                match["timestamp"]["$lte"] = end
            else:
                match["timestamp"] = {"$lte": end}
        except:
            pass
    if verdict and verdict != "all":
        match["verdict"] = verdict
    if search:
        match["$or"] = [
            {"transaction_id": {"$regex": search, "$options": "i"}},
            {"sender_id": {"$regex": search, "$options": "i"}},
            {"receiver_id": {"$regex": search, "$options": "i"}}
        ]
    
    cursor = processed_transactions_col.find(
        match,
        {
            "_id": 0,
            "transaction_id": 1,
            "timestamp": 1,
            "amount": 1,
            "currency": 1,
            "sender_id": 1,
            "receiver_id": 1,
            "ml_score": 1,
            "correlation_score": 1,
            "final_score": 1,
            "verdict": 1,
            "ml_processed_at": 1,
            "transaction_type": 1
        }
    ).sort("timestamp", -1).limit(limit)
    
    transactions = []
    total_amount = 0
    fraud_count = 0
    normal_count = 0
    false_positive_count = 0
    
    for doc in cursor:
        amount = doc.get("amount", 0)
        total_amount += amount
        v = doc.get("verdict", "unknown")
        if v == "fraud":
            fraud_count += 1
        elif v == "normal":
            normal_count += 1
        elif v == "false_positive":
            false_positive_count += 1
            
        transactions.append({
            "id": doc.get("transaction_id"),
            "amount": amount,
            "date": doc.get("timestamp").isoformat() if doc.get("timestamp") else None,
            "currency": doc.get("currency", ""),
            "sender": doc.get("sender_id", ""),
            "receiver": doc.get("receiver_id", ""),
            "mlScore": doc.get("ml_score", 0),
            "correlationScore": doc.get("correlation_score", 0),
            "finalScore": doc.get("final_score", 0),
            "verdict": v,
            "processedAt": doc.get("ml_processed_at").isoformat() if doc.get("ml_processed_at") else None,
            "transaction_type": doc.get("transaction_type", "")
        })
    
    count = len(transactions)
    summary = {
        "total_count": count,
        "total_amount": total_amount,
        "avg_final_score": round(sum(t["finalScore"] for t in transactions) / count, 1) if count > 0 else 0,
        "fraud_count": fraud_count,
        "normal_count": normal_count,
        "false_positive_count": false_positive_count,
        "flagged_count": fraud_count + false_positive_count
    }
    return {"transactions": transactions, "summary": summary}

# ===================== USER CONTROLS =====================
class SupabaseConfigModel(BaseModel):
    url: str
    anon_key: str
    service_role_key: str

class SourceSystemModel(BaseModel):
    source_system: str

class LoadTestStartModel(BaseModel):
    limit: int = 1000

_loadtest_states: Dict[str, dict] = {}

@router.post("/controls/verify-credentials")
async def verify_and_save_credentials(config: SupabaseConfigModel, current_user: dict = Depends(get_current_user)):
    user_id = ObjectId(current_user["user_id"])
    if not config.url or not config.url.strip():
        raise HTTPException(400, "API URL is required.")
    if not config.anon_key or not config.anon_key.strip():
        raise HTTPException(400, "Anon Key is required.")
    if not config.service_role_key or not config.service_role_key.strip():
        raise HTTPException(400, "Service Role Key is required.")
    token = create_access_token(data={"sub": current_user["user_id"], "role": "user"})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "http://api:8000/ingest/test-connection",
                json={"supabase_url": config.url, "supabase_service_role_key": config.service_role_key},
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                error_detail = resp.json().get("detail", "Unknown error")
                raise HTTPException(400, f"Verification failed: {error_detail}")
    except Exception as e:
        raise HTTPException(400, f"Could not verify Supabase credentials: {str(e)}")
    encrypted_anon = encrypt_value(config.anon_key)
    encrypted_service = encrypt_value(config.service_role_key)
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"supabase_config": {"url": config.url, "anon_key_encrypted": encrypted_anon, "service_role_key_encrypted": encrypted_service}}}
    )
    return {"message": "Supabase credentials verified and saved"}

@router.post("/controls/set-source")
async def set_source_system(payload: SourceSystemModel, current_user: dict = Depends(get_current_user)):
    user_id = ObjectId(current_user["user_id"])
    source = payload.source_system.strip()
    if not source:
        raise HTTPException(400, "Source System is required.")
    user = users_col.find_one({"_id": user_id})
    if not user or "supabase_config" not in user or "anon_key_encrypted" not in user["supabase_config"]:
        raise HTTPException(400, "Please verify and save your Supabase credentials first.")
    users_col.update_one({"_id": user_id}, {"$set": {"source_system": source}})
    return {"message": "Source system saved"}

@router.get("/controls/supabase-config")
async def get_supabase_config(current_user: dict = Depends(get_current_user)):
    user = users_col.find_one({"_id": ObjectId(current_user["user_id"])})
    if not user or "supabase_config" not in user:
        raise HTTPException(404, "No Supabase configuration found")
    config = user["supabase_config"]
    return {
        "url": config["url"],
        "anon_key": decrypt_value(config["anon_key_encrypted"]) if "anon_key_encrypted" in config else "",
        "service_role_key": decrypt_value(config["service_role_key_encrypted"]) if "service_role_key_encrypted" in config else "",
        "source_system": user.get("source_system", "")
    }

@router.post("/controls/loadtest/start")
async def start_load_test(payload: LoadTestStartModel, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    if user_id in _loadtest_states:
        _loadtest_states[user_id]["running"] = False
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user or "supabase_config" not in user:
        raise HTTPException(400, "Please configure your Supabase connection first.")
    source_system = user.get("source_system")
    if not source_system:
        raise HTTPException(400, "Source system not set. Please set it in the Controls section.")
    config = user["supabase_config"]
    decrypted_url = config["url"]
    decrypted_service_key = decrypt_value(config["service_role_key_encrypted"])
    token = create_access_token(data={"sub": user_id, "role": "user"})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "http://api:8000/ingest/test-connection",
                json={"supabase_url": decrypted_url, "supabase_service_role_key": decrypted_service_key},
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                raise HTTPException(400, "Invalid details. Please check API details.")
    except Exception as e:
        raise HTTPException(400, f"Invalid details. Please check API details: {str(e)}")
    logs = []
    state = {"running": True, "logs": logs}
    _loadtest_states[user_id] = state
    def run_poll():
        try:
            logs.append(f"[{datetime.utcnow().isoformat()}] Starting load test for source {source_system} with limit {payload.limit}")
            token = create_access_token(data={"sub": user_id, "role": "user"})
            headers = {"Authorization": f"Bearer {token}"}
            request_body = {"source": source_system, "limit": payload.limit, "supabase_url": decrypted_url, "supabase_service_role_key": decrypted_service_key}
            with httpx.Client(timeout=300) as client:
                response = client.post("http://api:8000/ingest/poll", json=request_body, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    logs.append(f"Successfully ingested {data.get('count', 0)} transactions.")
                else:
                    logs.append(f"Ingestion API returned {response.status_code}: {response.text[:200]}")
        except Exception as e:
            logs.append(f"Error: {str(e)}")
        finally:
            state["running"] = False
            logs.append(f"[{datetime.utcnow().isoformat()}] Load test finished")
    thread = threading.Thread(target=run_poll)
    thread.start()
    state["thread"] = thread
    return {"message": "Load test started"}

@router.post("/controls/loadtest/stop")
async def stop_load_test(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    if user_id not in _loadtest_states or not _loadtest_states[user_id].get("running"):
        raise HTTPException(400, "No load test running")
    _loadtest_states[user_id]["running"] = False
    return {"message": "Load test stop requested"}

@router.get("/controls/loadtest/logs")
async def get_load_test_logs(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    if user_id not in _loadtest_states:
        return {"logs": [], "running": False}
    state = _loadtest_states[user_id]
    return {"logs": state["logs"], "running": state["running"]}

# ===================== ADMIN ENDPOINTS =====================
def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return current_user

@router.get("/admin/stats/overview", dependencies=[Depends(require_admin)])
async def admin_overview_stats():
    total_raw = raw_transactions_col.count_documents({})
    total_ruled = ruled_transactions_col.count_documents({})
    total_bad = bad_records_col.count_documents({})
    total_processed = processed_transactions_col.count_documents({})
    high = ruled_transactions_col.count_documents({"risk_level": {"$in": ["high", "critical"]}})
    medium = ruled_transactions_col.count_documents({"risk_level": "medium"})
    low = ruled_transactions_col.count_documents({"risk_level": "low"})
    flagged = ruled_transactions_col.count_documents({"is_flagged": True})
    fraud = processed_transactions_col.count_documents({"verdict": "fraud"})
    normal = processed_transactions_col.count_documents({"verdict": "normal"})
    false_pos = processed_transactions_col.count_documents({"verdict": "false_positive"})
    return {
        "totalRaw": total_raw,
        "totalRuled": total_ruled,
        "totalBad": total_bad,
        "totalProcessed": total_processed,
        "highRisk": high,
        "mediumRisk": medium,
        "lowRisk": low,
        "flagged": flagged,
        "fraud": fraud,
        "normal": normal,
        "falsePositive": false_pos
    }

@router.get("/admin/data/raw", dependencies=[Depends(require_admin)])
async def admin_raw_data(limit: int = 500, skip: int = 0):
    cursor = raw_transactions_col.find({}, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    return list(cursor)

@router.get("/admin/data/ruled", dependencies=[Depends(require_admin)])
async def admin_ruled_data(limit: int = 500, skip: int = 0):
    cursor = ruled_transactions_col.find({}, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    return list(cursor)

@router.get("/admin/data/bad", dependencies=[Depends(require_admin)])
async def admin_bad_data(limit: int = 500, skip: int = 0):
    cursor = bad_records_col.find({}, {"_id": 0}).sort("error_timestamp", -1).skip(skip).limit(limit)
    return list(cursor)

@router.get("/admin/data/processed", dependencies=[Depends(require_admin)])
async def admin_processed_data(limit: int = 500, skip: int = 0):
    cursor = processed_transactions_col.find({}, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    return list(cursor)

@router.get("/admin/reports/{risk_type}", dependencies=[Depends(require_admin)])
async def admin_risk_reports(risk_type: str, limit: int = 500):
    if risk_type == "flagged":
        query = {"is_flagged": True}
        collection = ruled_transactions_col
    elif risk_type in ["high", "medium", "low"]:
        query = {"risk_level": risk_type}
        collection = ruled_transactions_col
    elif risk_type == "fraud":
        query = {"verdict": "fraud"}
        collection = processed_transactions_col
    elif risk_type == "false_positive":
        query = {"verdict": "false_positive"}
        collection = processed_transactions_col
    elif risk_type == "normal":
        query = {"verdict": "normal"}
        collection = processed_transactions_col
    else:
        raise HTTPException(400, "Invalid risk/verdict type")
    cursor = collection.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
    return list(cursor)

@router.get("/admin/users", dependencies=[Depends(require_admin)])
async def admin_list_users():
    users = list(users_col.find({}, {"password": 0, "docs.cert_file.data": 0, "docs.kra_cert_file.data": 0}))
    for u in users:
        u["user_id"] = str(u.pop("_id"))
    return users

@router.put("/admin/users/{user_id}/status", dependencies=[Depends(require_admin)])
async def admin_update_user_status(user_id: str, status_data: dict):
    new_status = status_data.get("status")
    if new_status not in ["active", "inactive", "pending", "rejected"]:
        raise HTTPException(400, "Invalid status. Use 'active', 'inactive', 'pending', or 'rejected'.")
    result = users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": new_status}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "User not found")
    return {"message": f"User status updated to {new_status}"}

@router.get("/admin/users/{user_id}/document/{doc_type}", dependencies=[Depends(require_admin)])
async def get_user_document(user_id: str, doc_type: str):
    user = users_col.find_one({"_id": ObjectId(user_id)}, {"docs": 1})
    if not user or "docs" not in user or doc_type not in user["docs"]:
        raise HTTPException(404, "Document not found")
    doc = user["docs"][doc_type]
    file_bytes = base64.b64decode(doc["data"])
    return Response(
        content=file_bytes,
        media_type=doc.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f"inline; filename={doc.get('filename', 'document')}"}
    )

@router.get("/admin/syshealth", dependencies=[Depends(require_admin)])
async def admin_syshealth():
    health_status = []
    prometheus_url = "http://prometheus:9090/api/v1/query"
    service_targets = {
        "api": "up{job='transaction-api'}",
        "consumer": "up{job='transaction-consumer'}",
        "rule-engine": "up{job='rule-engine'}",
        "ml-engine": "up{job='ml-engine'}",
    }
    try:
        for name, query in service_targets.items():
            resp = requests.get(prometheus_url, params={"query": query}, timeout=3)
            data = resp.json()
            if data["status"] == "success" and data["data"]["result"]:
                value = int(data["data"]["result"][0]["value"][1])
                status = "active" if value == 1 else "inactive"
            else:
                status = "unknown"
            health_status.append({"name": name, "status": status, "health": "healthy" if status == "active" else "unhealthy"})
    except Exception:
        for name in service_targets:
            health_status.append({"name": name, "status": "unknown", "health": "unreachable"})
    neo4j_status = "inactive"
    neo4j_health = "unhealthy"
    try:
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "Blackbutler@212"))
        )
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) LIMIT 1")
            result.single()
        neo4j_status = "active"
        neo4j_health = "healthy"
    except Exception:
        pass
    finally:
        try: driver.close()
        except: pass
    health_status.append({"name": "neo4j", "status": neo4j_status, "health": neo4j_health})
    core = [
        {"name": "MongoDB", "status": "active", "health": "healthy"},
        {"name": "Redis", "status": "active", "health": "healthy"},
        {"name": "Kafka", "status": "active", "health": "healthy"}
    ]
    health_status.extend(core)
    return health_status

# ===================== ADMIN AUDIT LOGS =====================
@router.get("/admin/audit-logs", dependencies=[Depends(require_admin)])
async def admin_audit_logs(limit: int = 200):
    cursor = audit_logs_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
    return list(cursor)