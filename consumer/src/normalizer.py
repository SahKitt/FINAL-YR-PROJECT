from typing import Dict, Any, Optional
from datetime import datetime
import logging
from .models import UnifiedTransaction, Actor, Counterparty, Channel, Device, Location, Merchant, Agent, ATM, Balances, BankDetails, WalletDetails, Loan, Remittance, Airtime, Dispute, Bulk, Risk

logger = logging.getLogger(__name__)

class TransactionNormalizer:

    def normalize(self, raw_message: Dict[str, Any]) -> Optional[UnifiedTransaction]:
        if 'transaction' in raw_message and 'source' in raw_message:
            source = raw_message.get('source', 'unknown')
            record = raw_message['transaction']
            record['_source_system'] = source
        else:
            record = raw_message
            if '_source_system' not in record:
                record['_source_system'] = record.get('source', 'unknown')

        source = record.get('_source_system', 'unknown')
        logger.info(f"[Normalizer] source={source}, keys={list(record.keys())[:8]}")

        try:
            if source == 'bank':
                result = self._map_bank(record)
            elif source == 'mpesa':
                result = self._map_mpesa(record)
            elif source == 'airtel':
                result = self._map_airtel(record)
            elif source == 'wallet':
                result = self._map_wallet(record)
            else:
                result = self._map_generic(record)

            logger.info(f"[Normalizer] id={result.transaction_id}, actor={result.actor.primary_id}, cp={result.counterparty.primary_id}")
            return result
        except Exception as e:
            logger.error(f"[Normalizer] Failed: {e}")
            return None

    # ---- BANK ----
    def _map_bank(self, data: Dict[str, Any]) -> UnifiedTransaction:
        return UnifiedTransaction(
            transaction_id=data.get('txn_id', ''),
            source_system='bank',
            source_transaction_type=self._guess_bank_type(data),
            normalized_timestamp=self._to_datetime(data.get('timestamp')),
            status=data.get('status_code') or 'unknown',
            actor=Actor(primary_id=data.get('account_id') or data.get('sender_account_id') or '', id_type='ACCOUNT', name=data.get('sender_name')),
            counterparty=Counterparty(primary_id=data.get('receiver_account_id') or data.get('raw_merchant_name') or 'UNKNOWN', id_type='ACCOUNT', name=data.get('receiver_name') or data.get('raw_merchant_name')),
            transaction_amount=float(data.get('amount') or 0),
            currency=data.get('currency') or 'KES',
            balances=Balances(actor_before=data.get('balance_before'), actor_after=data.get('balance_after')),
            channel=Channel(type=data.get('payment_channel'), ip_address=data.get('client_ip'), session_id=data.get('session_id'), auth_method=data.get('auth_factor_used'), user_agent=data.get('raw_user_agent')),
            device=Device(fingerprint_hash=data.get('device_fingerprint_hash')),
            location=Location(city=data.get('atm_location_city'), coordinates=data.get('atm_location_coordinates')),
            merchant=Merchant(id=data.get('raw_merchant_name'), category_code=data.get('merchant_category_code')) if data.get('raw_merchant_name') else None,
            atm=ATM(hardware_id=data.get('terminal_id'), coordinates=data.get('atm_location_coordinates')) if data.get('atm_location_city') else None,
            bank_details=BankDetails(card_bin=data.get('card_bin'), card_last_four=data.get('card_last_four'), billing_zip=data.get('billing_zip_postal'), deposit_method=data.get('deposit_method'), check_micr_line=data.get('check_micr_line'), mobile_image_metadata_hash=data.get('mobile_image_metadata_hash'), receiver_bank_code=data.get('receiver_bank_code'), network_reference_number=data.get('network_reference_number')),
            metadata={k: v for k, v in data.items() if k not in ['txn_id', 'timestamp', 'account_id', 'sender_account_id', 'sender_name', 'receiver_account_id', 'receiver_name', 'raw_merchant_name', 'merchant_category_code', 'terminal_id', 'amount', 'currency', 'balance_before', 'balance_after', 'status_code', 'payment_channel', 'client_ip', 'session_id', 'device_fingerprint_hash', 'auth_factor_used', 'raw_user_agent', 'card_bin', 'card_last_four', 'billing_zip_postal', 'deposit_method', 'check_micr_line', 'mobile_image_metadata_hash', 'atm_location_city', 'atm_location_coordinates', 'receiver_bank_code', 'network_reference_number', '_source_system', '_source_collection', '_fetched_at']}
        )

    # ---- MPESA ----
    def _map_mpesa(self, data: Dict[str, Any]) -> UnifiedTransaction:
        amt = float(data.get('amount') or 0)
        fee = float(data.get('transaction_fee') or 0)
        cp_id = (data.get('recipient_msisdn') or data.get('agent_number') or data.get('destination_till_number') or data.get('paybill_business_number') or 'UNKNOWN')
        mapped = [
            'mpesa_receipt_number', 'raw_timestamp', 'transaction_type', 'initiator_msisdn', 'sender_ledger_name',
            'amount', 'transaction_fee', 'wallet_balance_before', 'wallet_balance_after', 'channel_type',
            'network_mcc_mnc', 'device_imei_hash', 'sim_imsi_hash', 'current_cell_tower_id', 'transaction_status',
            'recipient_msisdn', 'recipient_ledger_name', 'agent_number', 'agent_registered_name', 'agent_operating_city',
            'agent_float_before', 'agent_float_after', 'atm_hardware_id', 'atm_bank_operator', 'atm_location_coordinates',
            'destination_till_number', 'merchant_legal_name', 'paybill_business_number', 'paybill_account_number_input',
            'recipient_business_name', 'associated_facility_id', 'triggering_parent_receipt', 'overdraft_principal_advanced',
            'overdraft_access_fee', 'mshwari_sub_action', 'partner_bank', 'loan_facility_reference', 'principal_amount',
            'loan_facility_fee', 'kcb_bridge_action', 'kcb_loan_reference', 'clearing_direction', 'commercial_bank_code',
            'bank_account_number_hidden', 'interbank_reference_id', 'originating_sender_raw', 'remittance_direction',
            'source_currency', 'source_amount_gross', 'applied_exchange_rate', 'net_kes_credit', 'target_msisdn',
            'airtel_target_flag', 'airtime_purchase_intent', 'target_disputed_receipt', 'disputed_amount',
            'intended_recipient_msisdn_claim', '_source_system', '_source_collection', '_fetched_at'
        ]
        return UnifiedTransaction(
            transaction_id=data.get('mpesa_receipt_number', ''),
            source_system='mpesa',
            source_transaction_type=data.get('transaction_type'),
            normalized_timestamp=self._to_datetime(data.get('raw_timestamp')),
            status=data.get('transaction_status') or 'unknown',
            actor=Actor(primary_id=data.get('initiator_msisdn') or '', id_type='MSISDN', name=data.get('sender_ledger_name')),
            counterparty=Counterparty(primary_id=cp_id, id_type='MSISDN' if data.get('recipient_msisdn') else 'AGENT' if data.get('agent_number') else 'TILL', name=data.get('recipient_ledger_name') or data.get('agent_registered_name') or data.get('merchant_legal_name')),
            transaction_amount=amt, currency='KES', fee=fee, net_amount=amt - fee if amt else None,
            balances=Balances(actor_before=data.get('wallet_balance_before'), actor_after=data.get('wallet_balance_after')),
            channel=Channel(type=data.get('channel_type')),
            device=Device(imei_hash=data.get('device_imei_hash'), sim_imsi_hash=data.get('sim_imsi_hash'), cell_tower_id=data.get('current_cell_tower_id')),
            location=Location(network_mcc_mnc=data.get('network_mcc_mnc')),
            agent=Agent(number=data.get('agent_number'), name=data.get('agent_registered_name'), city=data.get('agent_operating_city'), float_before=data.get('agent_float_before'), float_after=data.get('agent_float_after')) if data.get('agent_number') else None,
            atm=ATM(hardware_id=data.get('atm_hardware_id'), bank_operator=data.get('atm_bank_operator'), coordinates=data.get('atm_location_coordinates')) if data.get('atm_hardware_id') else None,
            loan=Loan(facility_id=data.get('associated_facility_id') or data.get('loan_facility_reference'), principal=data.get('overdraft_principal_advanced') or data.get('principal_amount'), fee=data.get('overdraft_access_fee') or data.get('loan_facility_fee')) if (data.get('associated_facility_id') or data.get('loan_facility_reference')) else None,
            remittance=Remittance(direction=data.get('remittance_direction'), source_currency=data.get('source_currency'), source_amount=data.get('source_amount_gross'), exchange_rate=data.get('applied_exchange_rate'), net_local_amount=data.get('net_kes_credit'), sender_raw=data.get('originating_sender_raw')) if data.get('remittance_direction') else None,
            airtime=Airtime(purchase_value=amt, target_msisdn=data.get('target_msisdn'), airtel_target_flag=data.get('airtel_target_flag'), purchase_intent=data.get('airtime_purchase_intent')) if data.get('airtime_purchase_intent') else None,
            dispute=Dispute(original_txn_id=data.get('target_disputed_receipt'), amount=data.get('disputed_amount'), trigger_source='INTERNAL_BUYER_CLAIM' if data.get('intended_recipient_msisdn_claim') else None) if data.get('target_disputed_receipt') else None,
            metadata={k: v for k, v in data.items() if k not in mapped}
        )

    # ---- AIRTEL ----
    def _map_airtel(self, data: Dict[str, Any]) -> UnifiedTransaction:
        amt = float(data.get('amount_transferred') or 0)
        fee = float(data.get('transaction_fee') or data.get('withdrawal_fee_charged') or 0)
        cp_id = (data.get('recipient_msisdn') or data.get('agent_number') or data.get('destination_till_number') or data.get('paybill_shortcode') or 'UNKNOWN')
        mapped = [
            'airtel_txn_id', 'raw_timestamp', 'transaction_type', 'initiator_msisdn', 'sender_ledger_name',
            'recipient_msisdn', 'recipient_ledger_name', 'amount_transferred', 'transaction_fee', 'withdrawal_fee_charged',
            'wallet_balance_before', 'wallet_balance_after', 'channel_type', 'network_mcc_mnc', 'device_imei_hash',
            'sim_imsi_hash', 'current_cell_tower_id', 'transaction_status', 'agent_number', 'agent_registered_name',
            'agent_float_before', 'agent_float_after', 'destination_till_number', 'merchant_legal_name', 'paybill_shortcode',
            'credit_facility_id', 'loan_principal_advanced', 'processing_fee_deducted', 'net_wallet_credit',
            'amount_deducted_repayment', 'purchase_value_kes', 'automated_bonus_value_awarded', 'corporate_client_id',
            'corporate_profile_name', 'batch_recipient_count', 'total_batch_volume_kes', 'corporate_float_before',
            'corporate_float_after', 'clearing_direction', 'commercial_bank_id_code', 'target_bank_account_masked',
            'interbank_bridge_reference', '_source_system', '_source_collection', '_fetched_at'
        ]
        return UnifiedTransaction(
            transaction_id=data.get('airtel_txn_id', ''), source_system='airtel', source_transaction_type=data.get('transaction_type'),
            normalized_timestamp=self._to_datetime(data.get('raw_timestamp')), status=data.get('transaction_status') or 'unknown',
            actor=Actor(primary_id=data.get('initiator_msisdn') or '', id_type='MSISDN', name=data.get('sender_ledger_name')),
            counterparty=Counterparty(primary_id=cp_id, id_type='MSISDN' if data.get('recipient_msisdn') else 'AGENT' if data.get('agent_number') else 'TILL', name=data.get('recipient_ledger_name') or data.get('agent_registered_name') or data.get('merchant_legal_name')),
            transaction_amount=amt, currency='KES', fee=fee, net_amount=amt - fee if amt else None,
            balances=Balances(actor_before=data.get('wallet_balance_before'), actor_after=data.get('wallet_balance_after')),
            channel=Channel(type=data.get('channel_type')),
            device=Device(imei_hash=data.get('device_imei_hash'), sim_imsi_hash=data.get('sim_imsi_hash'), cell_tower_id=data.get('current_cell_tower_id')),
            location=Location(network_mcc_mnc=data.get('network_mcc_mnc')),
            agent=Agent(number=data.get('agent_number'), name=data.get('agent_registered_name'), float_before=data.get('agent_float_before'), float_after=data.get('agent_float_after')) if data.get('agent_number') else None,
            loan=Loan(facility_id=data.get('credit_facility_id'), principal=data.get('loan_principal_advanced'), fee=data.get('processing_fee_deducted'), net_credit=data.get('net_wallet_credit')) if data.get('credit_facility_id') else None,
            airtime=Airtime(purchase_value=data.get('purchase_value_kes'), bonus_awarded=data.get('automated_bonus_value_awarded'), purchase_intent='BUY_AIRTIME_SELF') if data.get('purchase_value_kes') else None,
            bulk=Bulk(corporate_client_id=data.get('corporate_client_id'), profile_name=data.get('corporate_profile_name'), batch_recipient_count=data.get('batch_recipient_count'), total_volume=data.get('total_batch_volume_kes'), fee_deducted=data.get('transaction_fee'), float_before=data.get('corporate_float_before'), float_after=data.get('corporate_float_after')) if data.get('corporate_client_id') else None,
            metadata={k: v for k, v in data.items() if k not in mapped}
        )

    # ---- WALLET (FIXED) ----
    def _map_wallet(self, data: Dict[str, Any]) -> UnifiedTransaction:
        amt = float(data.get('gross_amount') or 0)
        fee = float(data.get('platform_withdrawal_fee') or data.get('merchant_fee_deducted') or 0)
        cp_id = data.get('recipient_account_id') or data.get('merchant_id') or 'UNKNOWN'
        mapped = [
            'wallet_txn_id', 'raw_timestamp', 'actor_account_id', 'client_ip', 'session_cookie_hash',
            'proxy_vpn_indicator', 'auth_token_type', 'ledger_status', 'funding_source_type', 'funding_institution_name',
            'card_token_or_masked_pan', 'gross_amount', 'currency_code', 'account_balance_before', 'account_balance_after',
            'payout_speed', 'destination_bank_routing_no', 'destination_bank_account_no_hash', 'payout_instrument_id',
            'platform_withdrawal_fee', 'net_settlement_amount', 'merchant_id', 'merchant_storefront_url',
            'checkout_integration_type', 'buyer_shipping_country', 'shipping_address_status', 'item_quantity_count',
            'purchase_gross_amount', 'merchant_fee_deducted', 'recipient_account_id', 'recipient_email_or_phone',
            'p2p_sub_type', 'disputed_original_txn_id', 'exception_trigger_source', 'dispute_reason_code',
            'escrow_held_amount', 'merchant_negative_balance_allowed', '_source_system', '_source_collection', '_fetched_at'
        ]
        return UnifiedTransaction(
            transaction_id=data.get('wallet_txn_id', ''),
            source_system='wallet',
            source_transaction_type=data.get('auth_token_type') or data.get('p2p_sub_type'),
            normalized_timestamp=self._to_datetime(data.get('raw_timestamp')),
            status=data.get('ledger_status') or 'unknown',
            actor=Actor(
                primary_id=data.get('actor_account_id') or '',
                id_type='ACCOUNT',
                name=None
            ),
            counterparty=Counterparty(
                primary_id=cp_id,
                id_type='ACCOUNT',
                name=data.get('recipient_email_or_phone')
            ),
            transaction_amount=amt,
            currency=data.get('currency_code') or 'USD',       
            fee=fee,
            net_amount=data.get('net_settlement_amount'),
            balances=Balances(
                actor_before=data.get('account_balance_before'),
                actor_after=data.get('account_balance_after')
            ),
            channel=Channel(
                type=data.get('checkout_integration_type'),
                ip_address=data.get('client_ip'),
                session_id=data.get('session_cookie_hash'),
                auth_method=data.get('auth_token_type'),
                proxy_vpn_indicator=data.get('proxy_vpn_indicator')
            ),
            device=Device(
                fingerprint_hash=data.get('session_cookie_hash')
            ),
            location=Location(
                city=data.get('buyer_shipping_country')
            ),
            merchant=Merchant(
                id=data.get('merchant_id'),
                name=data.get('merchant_storefront_url'),
                checkout_type=data.get('checkout_integration_type'),
                shipping_country=data.get('buyer_shipping_country'),
                shipping_address_status=data.get('shipping_address_status'),
                item_quantity=data.get('item_quantity_count')
            ) if data.get('merchant_id') else None,
            wallet_details=WalletDetails(
                funding_source_type=data.get('funding_source_type'),
                funding_institution_name=data.get('funding_institution_name'),
                card_token_or_masked_pan=data.get('card_token_or_masked_pan'),
                payout_speed=data.get('payout_speed'),
                destination_bank_routing_no=data.get('destination_bank_routing_no'),
                destination_bank_account_no_hash=data.get('destination_bank_account_no_hash'),
                payout_instrument_id=data.get('payout_instrument_id')
            ),
            dispute=Dispute(
                original_txn_id=data.get('disputed_original_txn_id'),
                amount=data.get('escrow_held_amount'),
                reason_code=data.get('dispute_reason_code'),
                trigger_source=data.get('exception_trigger_source'),
                merchant_negative_balance_allowed=data.get('merchant_negative_balance_allowed')
            ) if data.get('disputed_original_txn_id') else None,
            metadata={k: v for k, v in data.items() if k not in mapped}
        )

    # ---- Generic fallback ----
    def _map_generic(self, data: Dict[str, Any]) -> UnifiedTransaction:
        return UnifiedTransaction(
            transaction_id=data.get('transaction_id', ''), source_system=data.get('_source_system', 'unknown'),
            normalized_timestamp=self._to_datetime(data.get('timestamp') or data.get('raw_timestamp')),
            status=data.get('status') or 'unknown',
            actor=Actor(primary_id=data.get('initiator_msisdn') or data.get('account_id') or '', id_type='ACCOUNT'),
            counterparty=Counterparty(primary_id=data.get('recipient_msisdn') or data.get('receiver_account_id') or 'UNKNOWN', id_type='ACCOUNT'),
            transaction_amount=float(data.get('amount') or 0), currency=data.get('currency') or 'KES', metadata=data
        )

    @staticmethod
    def _to_datetime(value) -> datetime:
        if isinstance(value, datetime): return value
        if isinstance(value, str):
            try:
                if 'T' in value: return datetime.fromisoformat(value.replace('Z', '+00:00'))
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except: pass
        return datetime.utcnow()

    @staticmethod
    def _guess_bank_type(data: Dict[str, Any]) -> str:
        if data.get('transfer_type'): return 'EXTERNAL_WIRE'
        if data.get('deposit_method'): return 'DEPOSIT'
        if data.get('withdrawal_method'): return 'WITHDRAWAL'
        if data.get('payment_channel'): return 'PAYMENT'
        return 'unknown'