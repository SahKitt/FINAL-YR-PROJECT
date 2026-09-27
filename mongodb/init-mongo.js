db = db.getSiblingDB("transactions_db");

// Drop everything fresh
db.raw_transactions.drop();
db.bad_records.drop();
db.ruled_transactions.drop();
db.processed_transactions.drop();

// =====================
// 1. RAW TRANSACTIONS
// =====================
db.createCollection("raw_transactions");
db.raw_transactions.createIndex(
    { transaction_id: 1 }, { unique: true, sparse: true, name: "raw_transaction_id_idx" }
);
db.raw_transactions.createIndex(
    { normalized_timestamp: -1 }, { name: "raw_normalized_timestamp_idx" }
);
db.raw_transactions.createIndex(
    { source_system: 1 }, { name: "raw_source_system_idx" }
);
db.raw_transactions.createIndex(
    { "actor.primary_id": 1 }, { name: "raw_actor_primary_id_idx" }
);
db.raw_transactions.createIndex(
    { "counterparty.primary_id": 1 }, { name: "raw_counterparty_primary_id_idx" }
);
db.raw_transactions.createIndex(
    { "device.fingerprint_hash": 1 }, { name: "raw_device_fingerprint_hash_idx" }
);
db.raw_transactions.createIndex(
    { "channel.ip_address": 1 }, { name: "raw_channel_ip_address_idx" }
);
db.raw_transactions.createIndex(
    { "risk.score": 1 }, { name: "raw_risk_score_idx" }
);

// =====================
// 2. BAD RECORDS
// =====================
db.createCollection("bad_records");
db.bad_records.createIndex(
    { error_timestamp: -1 }, { name: "bad_timestamp_idx" }
);

// =====================
// 3. RULED TRANSACTIONS
// =====================
db.createCollection("ruled_transactions", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["transaction_id", "timestamp", "amount", "total_risk_score", "risk_level"],
      properties: {
        transaction_id: { bsonType: "string" },
        timestamp: { bsonType: "date" },
        amount: { bsonType: "double" },
        currency: { bsonType: "string" },
        source_system: { bsonType: "string" },
        transaction_type: { bsonType: "string" },
        sender_id: { bsonType: "string" },
        receiver_id: { bsonType: "string" },
        device_id: { bsonType: "string" },
        ip_address: { bsonType: "string" },
        total_risk_score: { bsonType: "int", minimum: 0, maximum: 100 },
        risk_level: { enum: ["low", "medium", "high", "critical"] },
        triggered_rules: { bsonType: "array" },
        is_flagged: { bsonType: "bool" },
        processed_at: { bsonType: "date" }
      }
    }
  }
});
db.ruled_transactions.createIndex(
    { transaction_id: 1 }, { unique: true, name: "ruled_transaction_id_idx" }
);
db.ruled_transactions.createIndex(
    { timestamp: -1 }, { name: "ruled_timestamp_idx" }
);
db.ruled_transactions.createIndex(
    { risk_level: 1, timestamp: -1 }, { name: "ruled_risk_level_timestamp_idx" }
);
db.ruled_transactions.createIndex(
    { sender_id: 1, timestamp: -1 }, { sparse: true, name: "ruled_sender_timestamp_idx" }
);
db.ruled_transactions.createIndex(
    { is_flagged: 1, timestamp: -1 }, { name: "ruled_flagged_timestamp_idx" }
);

// =====================
// 4. PROCESSED TRANSACTIONS
// =====================
db.createCollection("processed_transactions", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["transaction_id", "timestamp", "amount", "ml_score", "correlation_score", "final_score", "verdict"],
      properties: {
        transaction_id: { bsonType: "string" },
        timestamp: { bsonType: "date" },
        amount: { bsonType: "double" },
        currency: { bsonType: "string" },
        sender_id: { bsonType: "string" },
        receiver_id: { bsonType: "string" },
        ml_score: { bsonType: "double" },
        correlation_score: { bsonType: "int" },
        final_score: { bsonType: "double" },
        verdict: { enum: ["fraud", "false_positive", "normal"] },
        ml_processed_at: { bsonType: "date" }
      }
    }
  }
});
db.processed_transactions.createIndex(
    { transaction_id: 1 }, { unique: true, name: "processed_transaction_id_idx" }
);
db.processed_transactions.createIndex(
    { timestamp: -1 }, { name: "processed_timestamp_idx" }
);
db.processed_transactions.createIndex(
    { verdict: 1, timestamp: -1 }, { name: "processed_verdict_timestamp_idx" }
);
db.processed_transactions.createIndex(
    { sender_id: 1, timestamp: -1 }, { sparse: true, name: "processed_sender_timestamp_idx" }
);

print("MongoDB initialized with all indexes");