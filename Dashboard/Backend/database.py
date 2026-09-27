# database.py
import os
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://host.docker.internal:27017/")

# Client for users database
client = MongoClient(MONGO_URI)
users_db = client["users_db"]
users_col = users_db["users"]

# Ensure unique email index
users_col.create_index("email", unique=True)

# Audit logs collection (in the same users_db)
audit_logs_col = users_db["audit_logs"]

# Client for transactions database
transactions_client = MongoClient(MONGO_URI)
transactions_db = transactions_client["transactions_db"]
raw_transactions_col = transactions_db["raw_transactions"]
ruled_transactions_col = transactions_db["ruled_transactions"]
processed_transactions_col = transactions_db["processed_transactions"]
bad_records_col = transactions_db["bad_records"]