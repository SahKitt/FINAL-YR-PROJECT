import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import structlog
import time

from config import config
from models import RuledTransaction, ProcessingMetrics, RuleContext
from database import DatabaseManager
from rules import RuleEngine

logger = structlog.get_logger(__name__)


class TransactionProcessor:
    """High-performance transaction processor with parallel execution."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.rule_engine = RuleEngine()
        self.metrics = ProcessingMetrics()
        self.executor = ThreadPoolExecutor(max_workers=config.RULE_ENGINE_WORKERS)

    @staticmethod
    def _ensure_datetime(value) -> datetime:
        """
        Convert various timestamp formats to datetime.
        Tries ISO-8601 (with/without Z), common SQL formats, and fallback to UTC now.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            # Try to parse common formats
            # 1. ISO with 'Z'
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass
            # 2. ISO with space instead of 'T'
            try:
                return datetime.fromisoformat(value.replace(' ', 'T'))
            except (ValueError, TypeError):
                pass
            # 3. Common SQL formats (with/without microseconds)
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except (ValueError, TypeError):
                    continue
            # If all fail, log and fallback to current time
            logger.warning(f"Could not parse timestamp: {value[:100]}, using current UTC time")
            return datetime.utcnow()
        # For any other type (None, int, etc.)
        return datetime.utcnow()

    def process_batch(self, batch: List[Dict[str, Any]]) -> List[RuledTransaction]:
        start_time = time.time()
        processed_transactions = []
        futures = []
        for transaction in batch:
            future = self.executor.submit(self._process_single, transaction)
            futures.append(future)
        for future in futures:
            try:
                result = future.result(timeout=5)
                if result:
                    processed_transactions.append(result)
            except Exception as e:
                logger.error("Failed to process transaction", error=str(e))
        self._update_metrics(processed_transactions, time.time() - start_time)
        logger.info("Batch processed", total=len(batch), processed=len(processed_transactions), duration_seconds=time.time() - start_time)
        return processed_transactions
    
    def _process_single(self, tx: Dict[str, Any]) -> Optional[RuledTransaction]:
        """Process a single transaction, mapping unified schema to flat rule fields."""
        try:
            processing_start = datetime.utcnow()
            
            # ---- Extract from new unified schema ----
            actor = tx.get('actor', {}) or {}
            counterparty = tx.get('counterparty', {}) or {}
            channel = tx.get('channel', {}) or {}
            device = tx.get('device', {}) or {}
            location = tx.get('location', {}) or {}
            merchant = tx.get('merchant', {}) or {}
            
            # ---- Convert current timestamp ----
            timestamp_val = tx.get('normalized_timestamp') or tx.get('timestamp')
            timestamp_val = self._ensure_datetime(timestamp_val)
            
            # Build flat dictionary for rule engine
            flat = {
                'transaction_id': str(tx.get('transaction_id', '')),
                'timestamp': timestamp_val,
                'amount': float(tx.get('transaction_amount') or 0),
                'currency': str(tx.get('currency') or 'KES'),
                'source_system': str(tx.get('source_system', '')),
                'transaction_type': str(tx.get('source_transaction_type') or tx.get('transaction_type', '')),
                'status': str(tx.get('status', '')),
                
                # Actor / Counterparty
                'sender_id': actor.get('primary_id'),
                'sender_msisdn': actor.get('primary_id') if actor.get('id_type') == 'MSISDN' else None,
                'receiver_id': counterparty.get('primary_id'),
                'receiver_msisdn': counterparty.get('primary_id') if counterparty.get('id_type') == 'MSISDN' else None,
                
                # Device
                'device_id': device.get('imei_hash') or device.get('fingerprint_hash'),
                'device_id_hash': device.get('fingerprint_hash'),
                
                # Channel
                'ip_address': channel.get('ip_address'),
                'channel_type': channel.get('type'),
                'user_agent': channel.get('user_agent'),
                'session_id': channel.get('session_id'),
                'authentication_method': channel.get('auth_method'),
                
                # Location
                'country_code': location.get('network_mcc_mnc'),
                'city': location.get('city'),
                'state': None,
                'postal_code': None,
                
                # Merchant
                'merchant_name': merchant.get('name'),
                'merchant_category': merchant.get('category_code'),
                'terminal_id': location.get('network_mcc_mnc'),
                
                # Financial
                'fee': float(tx.get('fee') or 0),
                'balance_before': (tx.get('balances') or {}).get('actor_before'),
                'balance_after': (tx.get('balances') or {}).get('actor_after'),
                
                # Other
                'transaction_subtype': tx.get('source_transaction_type'),
                'description': '',
                'payment_type': channel.get('type'),
                'card_type': None,
                'card_last_four': (tx.get('bank_details') or {}).get('card_last_four'),
                'card_token_hash': None,
                'card_retention_status': None,
                'is_foreign_atm': None,
                'shipping_address_status': (merchant or {}).get('shipping_address_status'),
                'recipient_name_match': None,
                'payer_status': None,
                'agent_msisdn': (tx.get('agent') or {}).get('number'),
                'auth_response_code': None,
                'auth_timestamp': None,
                'posted_timestamp': None,
                'login_timestamp': None,
                'initiated_timestamp': None,
                'completion_timestamp': None,
            }
            
            # Get historical data using actor.primary_id
            historical_data = []
            sender_id = flat.get('sender_id')
            if sender_id:
                historical_data = self.db.get_historical_data('sender_id', sender_id)
                # ---- Convert timestamps in historical data ----
                for htx in historical_data:
                    if 'timestamp' in htx:
                        htx['timestamp'] = self._ensure_datetime(htx['timestamp'])
            
            context = RuleContext(transaction=flat, historical_data=historical_data)
            total_score, triggered_rules = self.rule_engine.evaluate_rules(context)
            
            is_flagged = total_score >= config.RISK_SCORE_THRESHOLD_MEDIUM
            needs_review = total_score >= config.RISK_SCORE_THRESHOLD_MEDIUM
            auto_block = total_score >= config.RISK_SCORE_THRESHOLD_HIGH
            
            for rule in triggered_rules:
                if rule.rule_id in ['R005', 'R013', 'R014']:
                    needs_review = True
                if rule.rule_id in ['R007']:
                    auto_block = True
            
            ruled_tx = RuledTransaction(
                **{k: v for k, v in flat.items() if v is not None},
                processing_start_time=processing_start,
                processing_end_time=datetime.utcnow(),
                total_risk_score=total_score,
                triggered_rules=triggered_rules,
                is_flagged=is_flagged,
                needs_review=needs_review,
                auto_block=auto_block,
                raw_transaction_id=str(tx.get('_id'))
            )
            
            if ruled_tx.risk_level in ['HIGH', 'CRITICAL']:
                logger.warning("High risk transaction detected",
                              transaction_id=ruled_tx.transaction_id,
                              risk_score=ruled_tx.total_risk_score,
                              risk_level=ruled_tx.risk_level,
                              triggered_rules=len(triggered_rules))
            return ruled_tx
            
        except Exception as e:
            logger.error("Failed to process transaction", transaction_id=tx.get('transaction_id'), error=str(e))
            return None
    
    def _update_metrics(self, transactions: List[RuledTransaction], duration: float):
        if not transactions:
            return
        high_risk = sum(1 for tx in transactions if tx.risk_level in ['HIGH', 'CRITICAL'])
        medium_risk = sum(1 for tx in transactions if tx.risk_level == 'MEDIUM')
        low_risk = sum(1 for tx in transactions if tx.risk_level == 'LOW')
        flagged = sum(1 for tx in transactions if tx.is_flagged)
        processing_times = [tx.processing_duration_ms for tx in transactions if tx.processing_duration_ms]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0
        max_time = max(processing_times) if processing_times else 0
        min_time = min(processing_times) if processing_times else 0
        rule_counts = {}
        for tx in transactions:
            for rule in tx.triggered_rules:
                rule_counts[rule.rule_id] = rule_counts.get(rule.rule_id, 0) + 1
        self.metrics.total_processed += len(transactions)
        self.metrics.total_flagged += flagged
        self.metrics.total_high_risk += high_risk
        self.metrics.total_medium_risk += medium_risk
        self.metrics.total_low_risk += low_risk
        self.metrics.avg_processing_time_ms = avg_time
        self.metrics.max_processing_time_ms = max_time
        self.metrics.min_processing_time_ms = min_time
        self.metrics.rules_triggered_count = rule_counts
        self.metrics.last_processed_at = datetime.utcnow()
    
    def get_metrics(self) -> ProcessingMetrics:
        return self.metrics
    
    def shutdown(self):
        self.executor.shutdown(wait=True)
        logger.info("Transaction processor shutdown complete")