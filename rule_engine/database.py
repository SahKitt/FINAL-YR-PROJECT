import asyncio
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import os
import traceback
import json

from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from bson import ObjectId

import structlog
from redis import Redis
from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError

from config import config
from models import RuledTransaction

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """High-performance database manager for rule engine."""

    def __init__(self):
        self.mongo_client: Optional[MongoClient] = None
        self.redis_client: Optional[Redis] = None
        self.db = None
        self.raw_collection_name = os.getenv("MONGO_RAW_COLLECTION", "raw_transactions")
        self.ruled_collection_name = os.getenv("MONGO_RULED_COLLECTION", "ruled_transactions")
        self.redis_connected: bool = False

    def connect(self) -> bool:
        """Connect to MongoDB and Redis."""
        try:
            logger.info("Waiting for MongoDB connection...")
            self.mongo_client = MongoClient(
                config.MONGO_URI,
                maxPoolSize=2000,
                minPoolSize=500,
                connectTimeoutMS=5000,
                socketTimeoutMS=30000
            )

            self.db = self.mongo_client[config.MONGO_DATABASE]
            self.raw_collection = self.db[self.raw_collection_name]
            self.ruled_collection = self.db[self.ruled_collection_name]

            logger.info(
                "DatabaseManager connected",
                raw_collection=self.raw_collection_name,
                ruled_collection=self.ruled_collection_name
            )

            self._connect_redis()
            return True

        except Exception as e:
            logger.error("Failed to connect to databases", error=str(e))
            return False

    def _connect_redis(self):
        """Connect to Redis with retry logic."""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                logger.info("Attempting Redis connection", attempt=attempt + 1, max_retries=max_retries)
                self.redis_client = Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    password=config.REDIS_PASSWORD,
                    db=config.REDIS_DB,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                self.redis_client.ping()
                self.redis_connected = True
                logger.info("Redis connection established successfully")
                return

            except AuthenticationError as e:
                logger.error("Redis authentication failed", error=str(e))
                self.redis_connected = False
                self.redis_client = None
                return

            except (ConnectionError, TimeoutError) as e:
                logger.warning("Redis connection attempt failed", attempt=attempt + 1, error=str(e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    self.redis_connected = False
                    self.redis_client = None

            except Exception as e:
                logger.error("Unexpected Redis error", error=str(e))
                self.redis_connected = False
                self.redis_client = None
                return

    def disconnect(self):
        """Disconnect from databases."""
        if self.mongo_client:
            self.mongo_client.close()
        if self.redis_client:
            self.redis_client.close()
        logger.info("Database connections closed")

    def has_raw_data(self) -> bool:
        """Check if there is unprocessed data in raw_transactions."""
        try:
            count = self.raw_collection.count_documents({"processed_by_rule_engine": {"$ne": True}})
            logger.info("Unprocessed raw transactions", count=count)
            return count > 0
        except Exception as e:
            logger.error("Failed to check raw data", error=str(e))
            return False

    def fetch_raw_batch(
        self,
        batch_size: int = 1000,
        last_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch a batch of unprocessed raw transactions with cursor support."""
        try:
            query = {"processed_by_rule_engine": {"$ne": True}}
            if last_id:
                query["_id"] = {"$gt": ObjectId(last_id)}

            cursor = self.raw_collection.find(
                query,
                projection=self._raw_projection()
            ).sort("_id", 1).limit(batch_size)

            batch = list(cursor)
            logger.info("Fetched raw batch", batch_size=len(batch), last_id=last_id)
            return batch

        except Exception as e:
            logger.error("Failed to fetch raw batch", error=str(e))
            return []

    def mark_as_processed(self, transaction_ids: List[str]):
        """Mark raw transactions as processed by rule engine."""
        if not transaction_ids:
            return
        try:
            result = self.raw_collection.update_many(
                {"transaction_id": {"$in": transaction_ids}},
                {
                    "$set": {
                        "processed_by_rule_engine": True,
                        "rule_engine_processed_at": datetime.utcnow()
                    }
                }
            )
            logger.info("Marked transactions as processed", modified_count=result.modified_count)
        except Exception as e:
            logger.error("Failed to mark transactions as processed", error=str(e))

    def save_ruled_batch(self, transactions: List[RuledTransaction]) -> bool:
        """Persist ruled transactions using unordered bulk upserts."""
        if not transactions:
            return True

        try:
            operations = []
            for tx in transactions:
                tx_dict = tx.dict(exclude_none=True)
                tx_dict["_id"] = tx.transaction_id
                tx_dict["processed_at"] = datetime.utcnow()
                tx_dict["rule_engine_version"] = "1.0"
                tx_dict["source_collection"] = self.raw_collection_name
                tx_dict["raw_data_timestamp"] = tx_dict.get("timestamp")

                operations.append(
                    UpdateOne(
                        {"_id": tx.transaction_id},
                        {"$set": tx_dict},
                        upsert=True
                    )
                )

            result = self.ruled_collection.bulk_write(operations, ordered=False)

            logger.info(
                "Bulk write to ruled collection completed",
                upserted=result.upserted_count,
                modified=result.modified_count,
                total=len(transactions)
            )
            return True

        except Exception as e:
            logger.error("Failed to save ruled batch", error=str(e))
            return False

    def get_historical_data(self, key: str, value: Any, time_window_minutes: int = 1440) -> List[Dict[str, Any]]:
        """Get historical transactions with Redis acceleration."""
        if not value or not self.redis_connected:
            return self._get_historical_from_mongo(key, value, time_window_minutes)

        cache_key = f"rule_engine:history:{key}:{value}:{time_window_minutes}"
        try:
            cached = self.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            return self._get_historical_from_mongo(key, value, time_window_minutes)

        results = self._get_historical_from_mongo(key, value, time_window_minutes)

        try:
            if results:
                self.redis_client.setex(cache_key, 300, json.dumps(results, default=str))
        except Exception:
            pass

        return results

    def _get_historical_from_mongo(self, key: str, value: Any, time_window_minutes: int = 1440) -> List[Dict[str, Any]]:
        """Get historical ruled transactions for velocity/pattern checks."""
        try:
            time_threshold = datetime.utcnow() - timedelta(minutes=time_window_minutes)
            cursor = self.ruled_collection.find(
                {key: value, "timestamp": {"$gte": time_threshold}},
                {
                    "_id": 0,
                    "transaction_id": 1,
                    "timestamp": 1,
                    "amount": 1,
                    "country_code": 1,
                    "city": 1,
                    "state": 1,
                    "device_id": 1,
                    "device_id_hash": 1,
                    "ip_address": 1,
                    "channel_type": 1,
                    "source_system": 1,
                    "transaction_type": 1,
                    "transaction_subtype": 1,
                    "merchant_category": 1,
                    "receiver_id": 1,
                    "receiver_msisdn": 1,
                    "card_token_hash": 1,
                    "agent_msisdn": 1,
                    "terminal_id": 1,
                    "risk_level": 1,
                    "is_flagged": 1,
                    "risk_score": 1,
                    "description": 1,
                }
            ).limit(500)

            return list(cursor)
        except Exception as e:
            logger.error("Failed to fetch historical data from ruled collection", error=str(e))
            return []

    def create_indexes(self):
        """Create necessary indexes for performance."""
        try:
            logger.info("Creating indexes for ruled collection...")

            # Base indexes
            self.ruled_collection.create_index([("transaction_id", 1)], unique=True, name="ruled_transaction_id_idx")
            self.ruled_collection.create_index([("timestamp", -1)], name="ruled_timestamp_idx")
            self.ruled_collection.create_index([("risk_level", 1)], name="ruled_risk_level_idx")
            self.ruled_collection.create_index([("risk_score", -1)], name="ruled_risk_score_idx")
            self.ruled_collection.create_index([("processed_at", -1)], name="ruled_processed_at_idx", background=True)
            self.ruled_collection.create_index([("source_system", 1), ("processed_at", -1)], name="ruled_source_processed_idx", background=True)

            # Indexes for historical queries (velocity rules)
            self.ruled_collection.create_index([("sender_id", 1), ("timestamp", -1)], name="ruled_sender_timestamp_idx", background=True)
            self.ruled_collection.create_index([("device_id", 1), ("timestamp", -1)], name="ruled_device_timestamp_idx", background=True, sparse=True)
            self.ruled_collection.create_index([("ip_address", 1), ("timestamp", -1)], name="ruled_ip_timestamp_idx", background=True, sparse=True)

            logger.info("Rule engine indexes created successfully")
        except Exception as e:
            logger.error("Failed to create rule engine indexes", error=str(e))
            logger.error("Traceback:", exc_info=True)

    def clean_processed_metadata(self):
        """Remove any rule engine metadata from raw collection."""
        try:
            query = {
                "$or": [
                    {"processed_by_rule_engine": {"$exists": True}},
                    {"rule_engine_processed_at": {"$exists": True}},
                    {"rule_engine_version": {"$exists": True}}
                ]
            }
            count = self.raw_collection.count_documents(query)
            if count > 0:
                result = self.raw_collection.update_many(query, {"$unset": {
                    "processed_by_rule_engine": "",
                    "rule_engine_processed_at": "",
                    "rule_engine_version": ""
                }})
                logger.info(f"Cleaned {result.modified_count} documents from raw collection metadata")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            logger.error("Traceback:", exc_info=True)

    def _raw_projection(self) -> Dict[str, int]:
        """Projection for fields needed by rule engine from unified schema."""
        return {
            "_id": 1,
            "transaction_id": 1,
            "normalized_timestamp": 1,
            "timestamp": 1,
            "transaction_amount": 1,
            "currency": 1,
            "source_system": 1,
            "source_transaction_type": 1,
            "transaction_type": 1,
            "transaction_subtype": 1,
            "status": 1,
            "actor": 1,
            "counterparty": 1,
            "channel": 1,
            "device": 1,
            "location": 1,
            "merchant": 1,
            "bank_details": 1,
            "wallet_details": 1,
            "agent": 1,
            "fee": 1,
            "balances": 1,
            "description": 1,
            "metadata": 1,
            "_ingested_at": 1,
        }