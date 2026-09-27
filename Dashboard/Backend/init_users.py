import os
from datetime import datetime
from pymongo import MongoClient
from passlib.context import CryptContext

MONGO_URI = os.getenv("MONGO_URI", "mongodb://host.docker.internal:27017/")
client = MongoClient(MONGO_URI)
db = client["users_db"]
col = db["users"]
col.create_index("email", unique=True)

pwd = CryptContext(schemes=["bcrypt"]).hash("Kaveve@123!")

admin = {
    "organization_name": "Admin",
    "email": "Kazoze12@gmail.com",
    "password": pwd,
    "role": "admin",
    "status": "active",
    "created_at": datetime.utcnow()
}

if not col.find_one({"email": admin["email"]}):
    col.insert_one(admin)
    print("Admin user created.")
else:
    print("Admin already exists.")