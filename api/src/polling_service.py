import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
import os

from .models import PollingRequest, PollingResponse
from .supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

class PollingService:
    """Service that dispatches a PollingRequest to the correct Supabase source method.
       Falls back to a default client if no request credentials are supplied."""

    def __init__(self):
        self.default_supabase = None
        try:
            if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
                self.default_supabase = SupabaseClient()
        except Exception as e:
            logger.warning(f"Default Supabase client not available: {e}")

    async def poll_source(self, request: PollingRequest) -> PollingResponse:
        """Fetch records from the requested source and wrap them in a PollingResponse."""
        start_date = request.start_date
        end_date = request.end_date
        limit = request.limit
        raw_records = []

        # Use per‑request Supabase credentials if provided, otherwise the default
        if request.supabase_url is not None and request.supabase_service_role_key is not None:
            supabase = SupabaseClient(url=request.supabase_url, key=request.supabase_service_role_key)
        else:
            supabase = self.default_supabase
            if supabase is None:
                raise ValueError("No Supabase credentials provided and default not available")

        source_tag = request.source.value

        if source_tag == "bank":
            raw_records = await asyncio.to_thread(supabase.get_bank_transactions, start_date, end_date, limit)
        elif source_tag == "mpesa":
            raw_records = await asyncio.to_thread(supabase.get_mpesa_transactions, start_date, end_date, limit)
        elif source_tag == "airtel":
            raw_records = await asyncio.to_thread(supabase.get_airtel_transactions, start_date, end_date, limit)
        elif source_tag == "wallet":
            raw_records = await asyncio.to_thread(supabase.get_wallet_transactions, start_date, end_date, limit)
        else:
            return PollingResponse(source=request.source, count=0, transactions=[], has_more=False, execution_time_ms=0)

        # Stamp each record with the source system and fetch time
        for rec in raw_records:
            rec["_source_system"] = source_tag
            rec["_fetched_at"] = datetime.utcnow().isoformat()

        return PollingResponse(
            source=request.source,
            count=len(raw_records),
            transactions=raw_records,
            has_more=len(raw_records) >= limit,
            execution_time_ms=0
        )