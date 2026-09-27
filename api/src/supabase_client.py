from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import json
from loguru import logger
from supabase import create_client, Client

# Mapping of source tag
TABLE_CONFIG = {
    "bank": {
        "table": "card_atm_transactions",
        "date_column": "timestamp"
    },
    "mpesa": {
        "table": "mpesa_mobile_transactions",
        "date_column": "raw_timestamp"
    },
    "airtel": {
        "table": "airtel_mobile_money",
        "date_column": "raw_timestamp"
    },
    "wallet": {
        "table": "digital_wallet_transactions",
        "date_column": "raw_timestamp"
    }
}

class SupabaseClient:
    """Wrapper around the Supabase Python client that provides paginated,
       date-filtered fetching for the four transaction sources."""

    SUPABASE_PAGE_SIZE = 1000

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = url if url is not None else os.getenv("SUPABASE_URL")
        self.key = key if key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        self.client: Optional[Client] = None
        self.connect()

    def connect(self):
        """Establish the connection to Supabase, raising an error if credentials are missing."""
        try:
            if not self.url or not self.key:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (or provided)")
            self.client = create_client(self.url, self.key)
            logger.info("Connected to Supabase")
        except Exception as e:
            logger.error(f"Failed to connect to Supabase: {e}")
            raise

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Attempt to convert a string or datetime to a proper datetime object.
           Handles ISO-8601 with Z and a few common formats."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                if value.endswith("Z"):
                    return datetime.fromisoformat(value[:-1] + "+00:00")
                return datetime.fromisoformat(value)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S.%f"):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
        return None

    def fetch_transactions(
        self,
        source_tag: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10000,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Core fetcher: paginates through the source table, applies date ranges
           and optional equality filters, then normalises date fields."""
        config = TABLE_CONFIG.get(source_tag)
        if not config:
            raise ValueError(f"Unknown source tag: {source_tag}")

        table = config["table"]
        date_column = config["date_column"]

        if not self.client:
            raise ConnectionError("Supabase client not connected")

        results: List[Dict[str, Any]] = []
        offset = 0

        try:
            while offset < limit:
                query = self.client.table(table).select("*")

                if start_date:
                    query = query.gte(date_column, start_date.isoformat())
                if end_date:
                    query = query.lte(date_column, end_date.isoformat())

                if filters:
                    for key, value in filters.items():
                        if value is not None:
                            query = query.eq(key, value)

                query = query.order(date_column, desc=True).range(offset, offset + self.SUPABASE_PAGE_SIZE - 1)
                response = query.execute()
                batch = response.data or []

                if not batch:
                    break

                results.extend(batch)
                if len(batch) < self.SUPABASE_PAGE_SIZE:
                    break
                offset += self.SUPABASE_PAGE_SIZE

            results = results[:limit]

            # Normalise known date/time fields for downstream consumers
            for tx in results:
                for field in list(tx.keys()):
                    if field.endswith("_timestamp") or field.endswith("_time") or field in (
                        "created_at", "date", "transaction_date",
                        "initiation_time", "completion_time", "raw_timestamp", "timestamp"
                    ):
                        if tx.get(field):
                            parsed = self._parse_datetime(tx[field])
                            if parsed:
                                tx[field] = parsed

                # If event_data is a JSON string, parse it and normalise its timestamps too
                if "event_data" in tx:
                    if isinstance(tx["event_data"], str):
                        try:
                            tx["event_data"] = json.loads(tx["event_data"])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse event_data JSON for {tx.get('id')}")

                    if isinstance(tx["event_data"], dict):
                        for key in ("event_timestamp", "initiated_timestamp", "auth_timestamp", "login_timestamp"):
                            if key in tx["event_data"]:
                                parsed = self._parse_datetime(tx["event_data"][key])
                                if parsed:
                                    tx["event_data"][key] = parsed

                tx["_source_collection"] = table
                tx["_source_system"] = source_tag
                tx["_fetched_at"] = datetime.utcnow()

            logger.info(f"Fetched {len(results)} transactions from {table}")
            return results

        except Exception as e:
            logger.error(f"Error fetching from Supabase table {table}: {e}")
            raise

    def get_bank_transactions(self, start_date=None, end_date=None, limit=10000):
        """Convenience wrapper for bank source."""
        return self.fetch_transactions("bank", start_date, end_date, limit)

    def get_mpesa_transactions(self, start_date=None, end_date=None, limit=10000):
        """Convenience wrapper for MPesa source."""
        return self.fetch_transactions("mpesa", start_date, end_date, limit)

    def get_airtel_transactions(self, start_date=None, end_date=None, limit=10000):
        """Convenience wrapper for Airtel source."""
        return self.fetch_transactions("airtel", start_date, end_date, limit)

    def get_wallet_transactions(self, start_date=None, end_date=None, limit=10000):
        """Convenience wrapper for digital wallet source."""
        return self.fetch_transactions("wallet", start_date, end_date, limit)