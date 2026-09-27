import asyncio
import os
import threading
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import start_http_server, Counter, Gauge

from .model import ModelManager, build_features
from .correlation import CorrelationEngine

MONGO_URI = os.getenv("MONGO_URI", "mongodb://host.docker.internal:27017/")
DB_NAME = os.getenv("MONGO_DATABASE", "transactions_db")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "Blackbutler@212")

# Retrain interval
RETRAIN_HOURS = float(os.getenv("RETRAIN_INTERVAL_HOURS", "2"))
RETRAIN_SECONDS = RETRAIN_HOURS * 3600  # Convert hours to seconds

WORKER_COUNT = int(os.getenv("ML_WORKERS", "20"))
BATCH_SIZE = int(os.getenv("ML_BATCH_SIZE", "5000"))
METRICS_PORT = int(os.getenv("ML_METRICS_PORT", "9093"))

# Shared thread pool for all sync I/O (Neo4j calls)
thread_pool = ThreadPoolExecutor(max_workers=WORKER_COUNT * 2)

# Prometheus metrics
processed_counter = Counter('ml_engine_processed_total', 'Total transactions processed')
fraud_counter = Counter('ml_engine_fraud_total', 'Total fraud verdicts')
model_age = Gauge('ml_engine_model_age_hours', 'Hours since last model retrain')


def _start_metrics_server():
    """Start a Prometheus metrics HTTP server in a daemon thread."""
    try:
        threading.Thread(target=lambda: start_http_server(METRICS_PORT), daemon=True).start()
        print(f"[Metrics] ML Engine metrics server started on port {METRICS_PORT}", flush=True)
    except Exception as e:
        print(f"[Metrics] Failed to start metrics server: {e}", flush=True)


async def process_one_async(model_mgr, corr, raw_tx, ruled_tx,
                            processed_col, raw_col):
    """Process a single transaction ."""
    merged = {**raw_tx, **ruled_tx}

    # ML prediction (CPU‑bound)
    loop = asyncio.get_event_loop()
    try:
        ml_proba = await loop.run_in_executor(thread_pool, model_mgr.predict_proba, merged)
    except Exception as e:
        print(f"  ML prediction failed for {raw_tx['transaction_id']}: {e}", flush=True)
        return

    # Extract identifiers
    sender_id = merged.get("sender_id", "")
    receiver_id = merged.get("receiver_id", "")
    device_id = merged.get("device_id", "")
    ip = merged.get("ip_address", "")
    ts = merged.get("timestamp", datetime.utcnow())
    amount = merged.get("amount", 0)
    source_system = merged.get("source_system", "")
    merchant_id = (
        merged.get("merchant_id") or
        merged.get("merchant_name") or
        (merged.get("merchant") or {}).get("id") or ""
    )
    sim_imsi_hash = (
        merged.get("sim_imsi_hash") or
        (merged.get("device") or {}).get("sim_imsi_hash") or ""
    )

    # Correlation score 
    corr_score = await loop.run_in_executor(
        thread_pool,
        lambda: corr.compute_score(
            sender_id, receiver_id, device_id, ip, ts,
            source_system=source_system,
            merchant_id=merchant_id,
            sim_imsi_hash=sim_imsi_hash
        )
    )

    # Final score
    final_score = (ml_proba * 100) * 0.7 + corr_score * 0.3
    if final_score >= 70:
        verdict = "fraud"
    elif final_score >= 40:
        verdict = "false_positive"
    else:
        verdict = "normal"

    # Store result (async MongoDB)
    await processed_col.update_one(
        {"transaction_id": raw_tx["transaction_id"]},
        {"$set": {
            "transaction_id": raw_tx["transaction_id"],
            "timestamp": ts,
            "amount": amount,
            "currency": merged.get("currency", ""),
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "ml_score": round(ml_proba, 4),
            "correlation_score": corr_score,
            "final_score": round(final_score, 2),
            "verdict": verdict,
            "ml_processed_at": datetime.utcnow()
        }},
        upsert=True
    )

    # Mark raw as processed
    await raw_col.update_one(
        {"_id": raw_tx["_id"]},
        {"$set": {"ml_processed": True}}
    )

    # Neo4j graph update 
    await loop.run_in_executor(
        thread_pool,
        lambda: corr.create_transaction_graph(
            raw_tx["transaction_id"], sender_id, receiver_id,
            device_id, ip, amount, ts,
            is_fraud=(verdict == "fraud"),
            source_system=source_system,
            merchant_id=merchant_id,
            sim_imsi_hash=sim_imsi_hash
        )
    )

    # Update Prometheus counters
    processed_counter.inc()
    if verdict == "fraud":
        fraud_counter.inc()

    print(f"{raw_tx['transaction_id']} → {verdict} (score: {final_score:.1f})", flush=True)


async def process_loop(model_mgr, corr):
    """Fetch batches, pre-load ruled data, process concurrently."""
    mongo = AsyncIOMotorClient(MONGO_URI)
    db = mongo[DB_NAME]
    raw_col = db["raw_transactions"]
    ruled_col = db["ruled_transactions"]
    processed_col = db["processed_transactions"]

    print(f"[ProcessLoop] Starting with {WORKER_COUNT} workers, batch size {BATCH_SIZE}...", flush=True)

    while True:
        batch = await raw_col.find({"ml_processed": {"$ne": True}})\
                             .limit(BATCH_SIZE).to_list(length=BATCH_SIZE)

        if not batch:
            print("[ProcessLoop] No unprocessed transactions. Sleeping 1s...", flush=True)
            await asyncio.sleep(1)
            continue

        print(f"[ProcessLoop] Processing batch of {len(batch)} transactions...", flush=True)

        tx_ids = [tx["transaction_id"] for tx in batch]
        ruled_cursor = ruled_col.find({"transaction_id": {"$in": tx_ids}})
        ruled_list = await ruled_cursor.to_list(length=len(tx_ids))
        ruled_map = {r["transaction_id"]: r for r in ruled_list}

        tasks = []
        for raw_tx in batch:
            ruled_tx = ruled_map.get(raw_tx["transaction_id"])
            if not ruled_tx:
                print(f"  - Waiting for rule engine on {raw_tx['transaction_id']}", flush=True)
                continue
            tasks.append(process_one_async(
                model_mgr, corr, raw_tx, ruled_tx,
                processed_col, raw_col
            ))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        print(f"[ProcessLoop] Batch complete. Next poll immediately.", flush=True)


async def retrain_loop(model_mgr):
    """Periodically retrain the model on new labelled data."""
    print(f"[RetrainLoop] Will retrain every {RETRAIN_HOURS} hours ({RETRAIN_SECONDS} seconds).", flush=True)
    while True:
        await asyncio.sleep(RETRAIN_SECONDS)  # Use seconds, not hours
        print("[RetrainLoop] Checking for new training data...", flush=True)
        mongo = AsyncIOMotorClient(MONGO_URI)
        db = mongo[DB_NAME]
        cutoff = datetime.utcnow() - timedelta(days=7)
        docs = await db.processed_transactions.find({
            "timestamp": {"$lt": cutoff},
            "verdict": {"$in": ["fraud", "normal", "false_positive"]}
        }).limit(10000).to_list(10000)

        if len(docs) < 200:
            print(f"[RetrainLoop] Only {len(docs)} labelled samples. Skipping.", flush=True)
            continue

        df = pd.DataFrame(docs)
        df['label'] = (df['verdict'] == 'fraud').astype(int)
        X = build_features(df)
        y = df['label']
        model_mgr.model.fit(X, y)
        model_mgr.feature_columns = X.columns.tolist()
        model_mgr.save()
        model_age.set(0)  # reset age after retrain
        print(f"[RetrainLoop] Model retrained on {len(df)} transactions.", flush=True)


async def main():
    print("[Main] Starting ML Engine...", flush=True)

    # Start Prometheus metrics server
    _start_metrics_server()

    model_mgr = ModelManager()
    if model_mgr.model is None:
        await model_mgr.train_seed_model(MONGO_URI, DB_NAME)

    corr = CorrelationEngine(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    print("[Main] Model and Correlation engine ready.", flush=True)

    await asyncio.gather(
        process_loop(model_mgr, corr),
        retrain_loop(model_mgr)
    )


if __name__ == "__main__":
    asyncio.run(main())