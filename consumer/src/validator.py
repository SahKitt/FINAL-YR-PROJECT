from typing import Dict, Any, Tuple, List
from datetime import datetime

class TransactionValidator:
    def validate(self, transaction: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = []
        required = ["transaction_id", "source_system", "normalized_timestamp", "transaction_amount", "currency", "actor", "counterparty"]
        for field in required:
            if field not in transaction or transaction[field] is None:
                errors.append(f"Missing {field}")
                return False, errors

        if not transaction.get("actor", {}).get("primary_id"):
            errors.append("actor.primary_id missing")
        if not transaction.get("counterparty", {}).get("primary_id"):
            errors.append("counterparty.primary_id missing")

        try:
            float(transaction["transaction_amount"])
        except (ValueError, TypeError):
            errors.append("Invalid transaction_amount")

        if not isinstance(transaction["normalized_timestamp"], datetime):
            errors.append("normalized_timestamp must be datetime")

        return len(errors) == 0, errors