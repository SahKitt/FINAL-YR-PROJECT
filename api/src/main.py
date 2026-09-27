from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from prometheus_client import Counter, Summary, generate_latest, CONTENT_TYPE_LATEST
from datetime import datetime
import json
import redis
import asyncio
import httpx
from typing import Dict, Any, List
import os
from dotenv import load_dotenv

from .auth import verify_token, HTTPBearer
from .models import PollingRequest, PollingResponse, SourceType
from .polling_service import PollingService
from .supabase_client import SupabaseClient

from confluent_kafka import Producer

load_dotenv()

app = FastAPI(title="Transaction Ingestion API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
ingested_counter = Counter('ingested_total', 'Total ingested transactions', ['source'])
rejected_counter = Counter('rejected_total', 'Total rejected transactions', ['source', 'reason'])
polling_counter = Counter('polling_requests_total', 'Total polling requests', ['source'])

polling_service = PollingService()

# Redis connection 
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True
)

# Kafka producer configuration for idempotent, compressed delivery
kafka_conf = {
    'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9093"),
    'enable.idempotence': True,
    'acks': 'all',
    'retries': 5,
    'compression.type': 'snappy'
}
kafka_producer = Producer(kafka_conf)

def delivery_callback(err, msg):
    """Kafka delivery report handler - logs success or failure."""
    if err:
        print(f'Message delivery failed: {err}')
    else:
        print(f'Message delivered to {msg.topic()} [{msg.partition()}]')

@app.on_event("startup")
async def startup_event():
    """Called when the API starts; initialisation logging."""
    print("Transaction Ingestion API starting up...")

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully close connections and flush pending Kafka messages."""
    redis_client.close()
    kafka_producer.flush()

@app.get("/health")
async def health_check():
    """Liveliness probe - returns status, timestamp, version and supported sources."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "sources": ["supabase"]
    }

@app.get("/metrics")
async def metrics():
    """Expose Prometheus metrics in the standard text format."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency that extracts and validates the JWT token from the request."""
    return verify_token(credentials)

# ========== Test Supabase connection ==========
@app.post("/ingest/test-connection")
async def test_supabase_connection(
    payload: dict,
    current_user: dict = Depends(get_current_user)
):
    """Verify that the supplied Supabase URL and service-role key are valid
       by calling the Auth Admin API. Returns 200 when the connection works."""
    supabase_url = payload.get("supabase_url")
    supabase_key = payload.get("supabase_service_role_key")
    if not supabase_url or not supabase_key:
        raise HTTPException(400, "supabase_url and supabase_service_role_key are required")

    base_url = supabase_url.rstrip('/')
    admin_url = f"{base_url}/auth/v1/admin/users"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                admin_url,
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "apikey": supabase_key
                }
            )
            if resp.status_code == 200:
                return {"status": "connected"}
            else:
                error_msg = resp.text[:200]
                raise HTTPException(400, f"Verification failed: {error_msg}")
    except Exception as e:
        raise HTTPException(400, f"Connection failed: {str(e)}")

# ========== polling endpoint ==========
@app.post("/ingest/poll", response_model=PollingResponse)
async def ingest_poll(
    request: PollingRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Poll a source for new transactions, enqueue each record into Kafka,
       and return a summary response to the caller."""
    print(f"[AUTH] Authenticated user: {current_user.get('sub', 'unknown')}")

    try:
        response = await polling_service.poll_source(request)

        # Offload the actual Kafka production to background tasks
        for raw_record in response.transactions:
            background_tasks.add_task(enqueue_for_processing, raw_record, response.source.value)

        polling_counter.labels(source=request.source.value).inc()
        return response

    except Exception as e:
        print(f"Error in ingest_poll: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def enqueue_for_processing(raw_record: dict, source: str):
    """Push a raw transaction record into Kafka for downstream normalisation.
       Increments the ingested counter on success, or the rejected counter on failure."""
    try:
        message = {
            "processed_at": datetime.utcnow().isoformat(),
            "source": source,
            "transaction": raw_record,
            "raw_data": raw_record.get("raw_data", raw_record)
        }
        tx_id = raw_record.get("transaction_id") or raw_record.get("id") or "unknown"
        kafka_producer.produce(
            os.getenv("KAFKA_TRANSACTIONS_TOPIC", "transactions_topic"),
            key=str(tx_id),
            value=json.dumps(message, default=str),
            callback=delivery_callback
        )
        kafka_producer.poll(0)          # serve delivery callbacks
        ingested_counter.labels(source=source).inc()
    except Exception as e:
        print(f"Failed to enqueue to Kafka: {e}")
        rejected_counter.labels(source=source, reason="kafka_error").inc()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True
    )