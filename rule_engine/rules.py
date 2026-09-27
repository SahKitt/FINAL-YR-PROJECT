from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import ipaddress
import structlog
from enum import Enum

from config import config
from models import TriggeredRule, RuleDefinition, RuleContext

logger = structlog.get_logger(__name__)


class RuleCategory(str, Enum):
    THRESHOLD = "threshold"
    VELOCITY = "velocity"
    GEO_LOCATION = "geolocation"
    PATTERN = "pattern"
    DEVICE = "device"
    TIME = "time"
    AUTHORIZATION = "authorization"
    BLACKLIST = "blacklist"
    CROSS_CHANNEL = "cross_channel"


class RuleEngine:
    """Core rule engine with optimized rule evaluation."""
    
    def __init__(self):
        self.rules: Dict[str, RuleDefinition] = {}
        self.high_risk_countries = set(config.HIGH_RISK_COUNTRIES)
        self.high_risk_mcc = set(config.HIGH_RISK_MCC)
        self._load_rules()
    
    def _load_rules(self):
        """Load all rule definitions."""
        # Threshold Rules
        self.rules['R001'] = RuleDefinition(
            rule_id='R001',
            rule_name='High Amount Transaction',
            description='Transaction amount (absolute value) exceeds threshold',
            risk_score=3,
            category=RuleCategory.THRESHOLD,
            conditions={'threshold': config.HIGH_AMOUNT_THRESHOLD_USD},
            action='FLAG',
            priority=1
        )
        
        self.rules['R002'] = RuleDefinition(
            rule_id='R002',
            rule_name='Small Repeated Transactions',
            description='Multiple small transactions (absolute value) just under threshold',
            risk_score=2,
            category=RuleCategory.THRESHOLD,
            conditions={'max_transactions': 5, 'time_window': 30},
            action='FLAG',
            priority=2
        )
        
        # Velocity Rules
        self.rules['R003'] = RuleDefinition(
            rule_id='R003',
            rule_name='Rapid Transaction Burst',
            description=f'More than {config.MAX_TRANSACTIONS_PER_WINDOW} transactions in {config.VELOCITY_WINDOW_MINUTES} minutes',
            risk_score=3,
            category=RuleCategory.VELOCITY,
            conditions={'max_transactions': config.MAX_TRANSACTIONS_PER_WINDOW, 
                       'time_window': config.VELOCITY_WINDOW_MINUTES},
            action='ALERT',
            priority=1
        )
        
        self.rules['R004'] = RuleDefinition(
            rule_id='R004',
            rule_name='Accelerated Cash Withdrawals',
            description='Multiple withdrawals (negative amounts) in short time across different locations',
            risk_score=4,
            category=RuleCategory.VELOCITY,
            conditions={'max_withdrawals': 3, 'time_window': 60},
            action='BLOCK',
            priority=1
        )
        
        # Geolocation Rules
        self.rules['R005'] = RuleDefinition(
            rule_id='R005',
            rule_name='Impossible Travel',
            description=f'Transactions from distant locations within {config.IMPOSSIBLE_TRAVEL_MINUTES} minutes',
            risk_score=4,
            category=RuleCategory.GEO_LOCATION,
            conditions={'max_distance_km': config.IMPOSSIBLE_TRAVEL_KM,
                       'max_time_minutes': config.IMPOSSIBLE_TRAVEL_MINUTES},
            action='REVIEW',
            priority=1
        )
        
        self.rules['R006'] = RuleDefinition(
            rule_id='R006',
            rule_name='VPN/Proxy Detection',
            description='Transaction from known VPN/Proxy IP',
            risk_score=3,
            category=RuleCategory.GEO_LOCATION,
            conditions={'check_vpn': True},
            action='FLAG',
            priority=2
        )
        
        self.rules['R007'] = RuleDefinition(
            rule_id='R007',
            rule_name='High Risk Country',
            description='Transaction originates from high-risk country',
            risk_score=5,
            category=RuleCategory.GEO_LOCATION,
            conditions={'high_risk_countries': list(self.high_risk_countries)},
            action='BLOCK',
            priority=1
        )
        
        # Device Rules
        self.rules['R008'] = RuleDefinition(
            rule_id='R008',
            rule_name='New Device',
            description='Transaction from new/unrecognized device',
            risk_score=2,
            category=RuleCategory.DEVICE,
            conditions={'max_history_days': 90},
            action='FLAG',
            priority=2
        )
        
        self.rules['R009'] = RuleDefinition(
            rule_id='R009',
            rule_name='Device Mismatch',
            description='Device used doesn\'t match historical pattern',
            risk_score=3,
            category=RuleCategory.DEVICE,
            conditions={'check_device_history': True},
            action='REVIEW',
            priority=2
        )
        
        # Pattern Rules
        self.rules['R010'] = RuleDefinition(
            rule_id='R010',
            rule_name='Dormancy Burst',
            description='Dormant account suddenly active with large transaction (absolute value)',
            risk_score=4,
            category=RuleCategory.PATTERN,
            conditions={'dormancy_days': 30},
            action='REVIEW',
            priority=2
        )
        
        self.rules['R011'] = RuleDefinition(
            rule_id='R011',
            rule_name='Unusual Merchant Category',
            description='Transaction in high-risk MCC not typical for customer',
            risk_score=2,
            category=RuleCategory.PATTERN,
            conditions={'high_risk_mcc': list(self.high_risk_mcc)},
            action='FLAG',
            priority=3
        )
        
        # Time Rules
        self.rules['R012'] = RuleDefinition(
            rule_id='R012',
            rule_name='Unusual Hours',
            description='Transaction at unusual time relative to customer pattern',
            risk_score=2,
            category=RuleCategory.TIME,
            conditions={'check_hours': True},
            action='FLAG',
            priority=3
        )
        
        # Cross-Channel Rules
        self.rules['R013'] = RuleDefinition(
            rule_id='R013',
            rule_name='Cross-Channel Correlation',
            description='Similar transactions across multiple channels in short time',
            risk_score=4,
            category=RuleCategory.CROSS_CHANNEL,
            conditions={'max_channels': 2, 'time_window': 10},
            action='REVIEW',
            priority=1
        )
        
        # Authorization Rules
        self.rules['R014'] = RuleDefinition(
            rule_id='R014',
            rule_name='Authorization Response Code Anomaly',
            description='Non-standard authorization response code but marked as COMPLETED',
            risk_score=3,
            category=RuleCategory.AUTHORIZATION,
            conditions={'valid_response_codes': ['00', '01', '02']},
            action='REVIEW',
            priority=2
        )
        
        logger.info(f"Loaded {len(self.rules)} rules")
    
    def evaluate_rules(self, context: RuleContext) -> Tuple[int, List[TriggeredRule]]:
        """
        Evaluate all rules against a transaction.
        Returns total risk score and list of triggered rules.
        """
        triggered_rules = []
        total_score = 0
        
        # Evaluate each rule
        for rule_id, rule in self.rules.items():
            if not rule.is_active:
                continue
                
            triggered, score = self._evaluate_rule(rule, context)
            if triggered:
                triggered_rules.append(TriggeredRule(
                    rule_id=rule_id,
                    rule_name=rule.rule_name,
                    rule_description=rule.description,
                    risk_score=score,
                    metadata=rule.conditions
                ))
                total_score += score
        
        return total_score, triggered_rules
    
    def _evaluate_rule(self, rule: RuleDefinition, context: RuleContext) -> Tuple[bool, int]:
        """Evaluate a single rule."""
        method_name = f"_rule_{rule.rule_id.lower()}"
        method = getattr(self, method_name, None)
        
        if method:
            return method(context, rule.conditions)
        
        # Fallback to generic evaluation
        logger.warning(f"No implementation for rule {rule.rule_id}")
        return False, 0
    
    # Rule implementations
    def _rule_r001(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """High Amount Transaction."""
        threshold = conditions.get('threshold', config.HIGH_AMOUNT_THRESHOLD_USD)
        
        # Use absolute value for amount comparison
        amount = abs(context.transaction.get('amount', 0))
        
        if amount > threshold:
            logger.debug("High amount transaction detected", 
                        amount=context.transaction.get('amount'),
                        absolute_amount=amount,
                        threshold=threshold)
            return True, 3
        return False, 0
    
    def _rule_r002(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Small Repeated Transactions."""
        max_transactions = conditions.get('max_transactions', 5)
        time_window = conditions.get('time_window', 30)
        
        # Use absolute value for amount comparison
        amount = abs(context.transaction.get('amount', 0))
        
        # Threshold for "small" transactions is 10% of high amount threshold
        small_amount_threshold = config.HIGH_AMOUNT_THRESHOLD_USD * 0.1
        
        if amount >= small_amount_threshold or not context.historical_data:
            return False, 0
        
        # Count small transactions in time window
        transaction_time = context.transaction.get('timestamp')
        if not transaction_time:
            return False, 0
        
        window_start = transaction_time - timedelta(minutes=time_window)
        
        small_transactions = sum(
            1 for tx in context.historical_data
            if tx.get('timestamp') and tx.get('timestamp') >= window_start 
            and abs(tx.get('amount', 0)) < small_amount_threshold
        )
        
        if small_transactions >= max_transactions:
            logger.debug("Small repeated transactions detected",
                        count=small_transactions + 1,
                        max_allowed=max_transactions)
            return True, 2
        return False, 0
    
    def _rule_r003(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Rapid Transaction Burst."""
        max_transactions = conditions.get('max_transactions', 3)
        time_window = conditions.get('time_window', 10)
        
        if not context.historical_data:
            return False, 0
        
        # Count transactions in time window (any amount, positive or negative)
        transaction_time = context.transaction.get('timestamp')
        if not transaction_time:
            return False, 0
        
        window_start = transaction_time - timedelta(minutes=time_window)
        
        recent_transactions = sum(
            1 for tx in context.historical_data
            if tx.get('timestamp') and tx.get('timestamp') >= window_start
        )
        
        if recent_transactions >= max_transactions:
            logger.debug("Rapid transaction burst detected",
                        count=recent_transactions + 1,
                        max_allowed=max_transactions)
            return True, 3
        return False, 0
    
    def _rule_r004(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Accelerated Cash Withdrawals."""
        max_withdrawals = conditions.get('max_withdrawals', 3)
        time_window = conditions.get('time_window', 60)
        
        # Check if this is a cash withdrawal (negative amount or specific transaction type)
        amount = context.transaction.get('amount', 0)
        transaction_type = context.transaction.get('transaction_type', '')
        description = context.transaction.get('description', '').lower()
        
        # Negative amount indicates withdrawal
        is_withdrawal = (amount < 0 or 
                        'atm' in transaction_type.lower() or 
                        'withdrawal' in transaction_type.lower() or
                        'cash' in description)
        
        if not is_withdrawal:
            return False, 0
        
        if not context.historical_data:
            return False, 0
        
        transaction_time = context.transaction.get('timestamp')
        if not transaction_time:
            return False, 0
        
        window_start = transaction_time - timedelta(minutes=time_window)
        
        # Count withdrawals in time window
        withdrawals = 0
        for tx in context.historical_data:
            if tx.get('timestamp') and tx.get('timestamp') >= window_start:
                tx_amount = tx.get('amount', 0)
                tx_type = tx.get('transaction_type', '').lower()
                tx_desc = tx.get('description', '').lower()
                
                # Check if it's a withdrawal (negative amount or specific type)
                if (tx_amount < 0 or 
                    'atm' in tx_type or 
                    'withdrawal' in tx_type or 
                    'cash' in tx_desc):
                    withdrawals += 1
        
        if withdrawals >= max_withdrawals:
            logger.debug("Accelerated cash withdrawals detected",
                        count=withdrawals + 1,
                        max_allowed=max_withdrawals)
            return True, 4
        return False, 0
    
    def _rule_r005(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Impossible Travel."""
        max_distance_km = conditions.get('max_distance_km', 1000.0)
        max_time_minutes = conditions.get('max_time_minutes', 30)
        
        current_country = context.transaction.get('country_code')
        transaction_time = context.transaction.get('timestamp')
        
        if not current_country or not transaction_time:
            return False, 0
        
        # Find most recent transaction in different country
        for tx in context.historical_data:
            tx_country = tx.get('country_code')
            tx_time = tx.get('timestamp')
            
            if (tx_country and tx_country != current_country and tx_time):
                time_diff = (transaction_time - tx_time).total_seconds() / 60
                
                # Check if impossible travel
                if time_diff <= max_time_minutes:
                    logger.debug("Impossible travel detected",
                                from_country=tx_country,
                                to_country=current_country,
                                time_diff_minutes=time_diff)
                    return True, 4
        
        return False, 0
    
    def _rule_r006(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """VPN/Proxy Detection."""
        ip_address = context.transaction.get('ip_address')
        
        if not ip_address:
            return False, 0
        
        # Simple check for private IPs
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            if ip_obj.is_private:
                return False, 0
        except ValueError:
            return False, 0
        
        # Mark as potential VPN if from certain range
        if ip_address.startswith(('185.159.', '192.168.', '10.')):
            logger.debug("VPN/Proxy IP detected", ip=ip_address)
            return True, 3
        
        return False, 0
    
    def _rule_r007(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """High Risk Country."""
        country_code = context.transaction.get('country_code')
        
        if country_code and country_code.upper() in self.high_risk_countries:
            logger.debug("High risk country detected", country=country_code)
            return True, 5
        
        return False, 0
    
    def _rule_r008(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """New Device."""
        device_id = context.transaction.get('device_id')
        max_history_days = conditions.get('max_history_days', 90)
        
        if not device_id:
            return False, 0
        
        # Check if device has been seen before
        for tx in context.historical_data:
            if tx.get('device_id') == device_id:
                return False, 0
        
        # Device not found in history
        logger.debug("New device detected", device_id=device_id)
        return True, 2
    
    def _rule_r009(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Device Mismatch."""
        device_id = context.transaction.get('device_id')
        
        if not device_id or not context.historical_data:
            return False, 0
        
        # Find most common device for this user
        device_counts = {}
        for tx in context.historical_data:
            tx_device = tx.get('device_id')
            if tx_device:
                device_counts[tx_device] = device_counts.get(tx_device, 0) + 1
        
        if not device_counts:
            return False, 0
        
        # Get the most common device
        most_common_device = max(device_counts.items(), key=lambda x: x[1])[0]
        
        # Check if current device matches the most common one
        if device_id != most_common_device:
            logger.debug("Device mismatch detected",
                        current_device=device_id,
                        common_device=most_common_device)
            return True, 3
        return False, 0
    
    def _rule_r010(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Dormancy Burst."""
        dormancy_days = conditions.get('dormancy_days', 30)
        
        # Use absolute value for amount comparison
        amount = abs(context.transaction.get('amount', 0))
        
        if amount <= 0 or not context.historical_data:
            return False, 0
        
        # Check if account was dormant
        transaction_time = context.transaction.get('timestamp')
        if not transaction_time:
            return False, 0
        
        # Find most recent transaction
        latest_historical = max(
            (tx.get('timestamp') for tx in context.historical_data if tx.get('timestamp')),
            default=None
        )
        
        if latest_historical:
            days_inactive = (transaction_time - latest_historical).days
            
            if days_inactive >= dormancy_days and amount > 100:
                logger.debug("Dormancy burst detected",
                            days_inactive=days_inactive,
                            amount=context.transaction.get('amount'),
                            absolute_amount=amount)
                return True, 4
        
        return False, 0
    
    def _rule_r011(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Unusual Merchant Category."""
        merchant_category = context.transaction.get('merchant_category')
        
        if merchant_category and merchant_category in self.high_risk_mcc:
            logger.debug("High risk merchant category detected", mcc=merchant_category)
            return True, 2
        
        return False, 0
    
    def _rule_r012(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Unusual Hours."""
        transaction_time = context.transaction.get('timestamp')
        
        if not transaction_time:
            return False, 0
        
        hour = transaction_time.hour
        
        # Check if transaction is in unusual hours (1 AM to 5 AM)
        if 1 <= hour <= 5:
            if context.historical_data:
                historical_hours = [
                    tx.get('timestamp').hour 
                    for tx in context.historical_data 
                    if tx.get('timestamp')
                ]
                
                if historical_hours:
                    hour_counts = {}
                    for h in historical_hours:
                        hour_counts[h] = hour_counts.get(h, 0) + 1
                    
                    if hour not in hour_counts or hour_counts[hour] < 0.1 * len(historical_hours):
                        logger.debug("Unusual hour transaction", hour=hour)
                        return True, 2
        
        return False, 0
    
    def _rule_r013(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Cross-Channel Correlation."""
        max_channels = conditions.get('max_channels', 2)
        time_window = conditions.get('time_window', 10)
        
        if not context.historical_data:
            return False, 0
        
        transaction_time = context.transaction.get('timestamp')
        if not transaction_time:
            return False, 0
        
        window_start = transaction_time - timedelta(minutes=time_window)
        
        # Get unique channels used in time window
        channels_used = set()
        for tx in context.historical_data:
            if tx.get('timestamp') and tx.get('timestamp') >= window_start:
                channel = tx.get('channel_type') or tx.get('source_system') or 'unknown'
                channels_used.add(channel)
        
        # Add current transaction channel
        current_channel = context.transaction.get('channel_type') or context.transaction.get('source_system') or 'unknown'
        channels_used.add(current_channel)
        
        if len(channels_used) >= max_channels:
            logger.debug("Cross-channel correlation detected",
                        channels=list(channels_used),
                        max_allowed=max_channels)
            return True, 4
        return False, 0
    
    def _rule_r014(self, context: RuleContext, conditions: Dict) -> Tuple[bool, int]:
        """Authorization Response Code Anomaly."""
        auth_response = context.transaction.get('auth_response_code')
        status = context.transaction.get('status')
        
        valid_codes = conditions.get('valid_response_codes', ['00', '01', '02'])
        
        if (status == 'COMPLETED' and auth_response and 
            auth_response not in valid_codes):
            logger.debug("Suspicious authorization response code",
                        response_code=auth_response,
                        status=status)
            return True, 3
        return False, 0