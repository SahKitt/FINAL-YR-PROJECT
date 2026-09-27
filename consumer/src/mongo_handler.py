from pymongo import MongoClient, InsertOne
from pymongo.errors import BulkWriteError
from typing import Dict, Any, List
import os, sys, time, uuid, traceback
from datetime import datetime

class MongoDBHandler:
    def __init__(self, collection_prefix: str = ""):
        self.mongo_uri = os.getenv("MONGO_URI", "mongodb://host.docker.internal:27017/")
        self.database_name = os.getenv("MONGO_DATABASE", "transactions_db")
        self.collection_prefix = collection_prefix
        self.raw_collection_name = f"{collection_prefix}{os.getenv('MONGO_RAW_COLLECTION', 'raw_transactions')}"
        self.bad_collection_name = f"{collection_prefix}{os.getenv('MONGO_BAD_COLLECTION', 'bad_records')}"
        self.client = None
        self._connect_with_retry()
        

    def _connect_with_retry(self):
        for uri in [self.mongo_uri, "mongodb://localhost:27017/", "mongodb://127.0.0.1:27017/"]:
            try:
                self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, maxPoolSize=50)
                self.client.admin.command("ping")
                self.db = self.client[self.database_name]
                self.raw_collection = self.db[self.raw_collection_name]
                self.bad_collection = self.db[self.bad_collection_name]
                print(f"[Mongo] Connected at {uri}", flush=True)
                return
            except Exception as e:
                print(f"[Mongo] Connection failed: {e}", flush=True)
        sys.exit(1)

    def batch_insert(self, transactions: List[Dict[str, Any]]) -> int:
        if not transactions:
            return 0
        inserted, batch_id = 0, str(uuid.uuid4())
        for i in range(0, len(transactions), 1000):
            chunk = transactions[i:i+1000]
            ops = []
            for tx in chunk:
                try:
                    doc = {k: v for k, v in tx.items() if v is not None}
                    doc['_created_at'] = doc.get('_created_at', datetime.utcnow())
                    doc['_updated_at'] = datetime.utcnow()
                    doc['_batch_id'] = batch_id
                    ops.append(InsertOne(doc))
                except Exception:
                    pass
            if ops:
                try:
                    inserted += self.raw_collection.bulk_write(ops, ordered=False).inserted_count
                except BulkWriteError as bwe:
                    inserted += bwe.details.get('nInserted', 0)
        return inserted

    def insert_bad_record(self, raw_data, error_message: str, source: str, error_type: str = "VALIDATION_ERROR"):
        try:
            self.bad_collection.insert_one({
                "raw_data": raw_data,
                "error_message": error_message[:1000],
                "source": source,
                "error_type": error_type,
                "error_timestamp": datetime.utcnow(),
                "_created": datetime.utcnow(),
                "_batch_id": str(uuid.uuid4()),
                "transaction_id": raw_data.get('transaction_id') or raw_data.get('id', f"txn_{uuid.uuid4().hex[:16]}")
            })
        except Exception:
            pass

    def close(self):
        if self.client:
            self.client.close()