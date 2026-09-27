from neo4j import GraphDatabase
from datetime import datetime, timedelta

class CorrelationEngine:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._seed_schema()
        self._ensure_constraints()

    def _ensure_constraints(self):
        """Create uniqueness constraints to guarantee no duplicate nodes."""
        with self.driver.session() as session:
            try:
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Account) REQUIRE a.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Transaction) REQUIRE t.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (i:IP) REQUIRE i.address IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Merchant) REQUIRE m.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:SIM) REQUIRE s.imsi IS UNIQUE")
                print("[Correlation] Constraints ensured - no duplicates possible.", flush=True)
            except Exception as e:
                print(f"[Correlation] Constraint creation warning: {e}", flush=True)

    def _seed_schema(self):
        """
        Seed dummy nodes and relationships to suppress warnings(Docker) for ALL labels and relationship types
        used by the  correlation rules:
          - Nodes: Account, Transaction, Device, IP, Merchant, SIM
          - Relationships: PERFORMED, TO, USED_DEVICE, LOGGED_IN_FROM, AT_MERCHANT, USES_SIM
        """
        try:
            with self.driver.session() as session:
                # Seed all node types
                session.run("MERGE (:Account {id: '__seed__'})")
                session.run("MERGE (:Account {id: '__seed_receiver__'})")
                session.run("MERGE (:Device {id: '__seed_device__'})")
                session.run("MERGE (:IP {address: '0.0.0.0'})")
                session.run("MERGE (:Merchant {id: '__seed_merchant__'})")
                session.run("MERGE (:SIM {imsi: '__seed_sim__'})")

                # Dummy transaction + relationships: PERFORMED, TO
                session.run("""
                    MERGE (s:Account {id: '__seed__'})
                    MERGE (r:Account {id: '__seed_receiver__'})
                    MERGE (t:Transaction {id: '__seed__'})
                    ON CREATE SET t.is_fraud = false, t.timestamp = datetime(), t.source_system = 'none'
                    MERGE (s)-[:PERFORMED]->(t)
                    MERGE (t)-[:TO]->(r)
                """)

                # USED_DEVICE
                session.run("""
                    MERGE (s:Account {id: '__seed__'})
                    MERGE (d:Device {id: '__seed_device__'})
                    MERGE (s)-[:USED_DEVICE]->(d)
                """)

                # LOGGED_IN_FROM
                session.run("""
                    MERGE (s:Account {id: '__seed__'})
                    MERGE (ip:IP {address: '0.0.0.0'})
                    MERGE (s)-[:LOGGED_IN_FROM]->(ip)
                """)

                # AT_MERCHANT 
                session.run("""
                    MERGE (m:Merchant {id: '__seed_merchant__'})
                    MERGE (t:Transaction {id: '__seed__'})
                    MERGE (t)-[:AT_MERCHANT]->(m)
                """)

                # USES_SIM
                session.run("""
                    MERGE (s:Account {id: '__seed__'})
                    MERGE (sim:SIM {imsi: '__seed_sim__'})
                    MERGE (s)-[:USES_SIM]->(sim)
                """)

            print("[Correlation] Schema seeded - all warnings suppressed.", flush=True)
        except Exception as e:
            print(f"[Correlation] Failed to seed schema: {e}", flush=True)

    def close(self):
        self.driver.close()

    def compute_score(self, sender_id: str, receiver_id: str,
                      device_id: str, ip: str, timestamp: datetime,
                      source_system: str = "",
                      merchant_id: str = "",
                      sim_imsi_hash: str = "") -> int:
        """
        Returns a cross-channel correlation score (0-100).
        Uses all 8 rules.
        """
        score = 0
        lookback = timestamp - timedelta(days=30)

        with self.driver.session() as session:
            # 1. Fraud peer check (+30)
            res = session.run("""
                MATCH (a:Account {id: $sender_id})-[:PERFORMED]->(t:Transaction {is_fraud: true})-[:TO]->(b:Account)
                WHERE t.timestamp > $lookback
                RETURN count(b) as cnt
            """, sender_id=sender_id, lookback=lookback.isoformat())
            if res.single()["cnt"] > 0:
                score += 30

            # 2. Shared IP with fraudster (+20)
            res = session.run("""
                MATCH (ip:IP {address: $ip})<-[:LOGGED_IN_FROM]-(a:Account)-[:PERFORMED]->(t:Transaction {is_fraud: true})
                WHERE t.timestamp > $lookback
                RETURN count(a) as cnt
            """, ip=ip, lookback=lookback.isoformat())
            if res.single()["cnt"] > 0:
                score += 20

            # 3. New device for account (+10)
            if device_id:
                res = session.run("""
                    MATCH (a:Account {id: $sender_id})-[:USED_DEVICE]->(d:Device {id: $device_id})
                    RETURN count(d) as cnt
                """, sender_id=sender_id, device_id=device_id)
                if res.single()["cnt"] == 0:
                    score += 10

            # 4. Cross‑channel velocity (+15)
            if source_system:
                recent_window = timestamp - timedelta(hours=2)
                res = session.run("""
                    MATCH (a:Account {id: $sender_id})-[:PERFORMED]->(t:Transaction)
                    WHERE t.timestamp > $recent_window
                    RETURN collect(DISTINCT t.source_system) as channels
                """, sender_id=sender_id, recent_window=recent_window.isoformat())
                channels = res.single()["channels"] or []
                all_channels = set(channels)
                all_channels.add(source_system)
                if len(all_channels) >= 3:
                    score += 15

            # 5. Device previously used in fraud (+15)
            if device_id:
                res = session.run("""
                    MATCH (d:Device {id: $device_id})<-[:USED_DEVICE]-(a:Account)-[:PERFORMED]->(t:Transaction {is_fraud: true})
                    WHERE t.timestamp > $lookback
                    RETURN count(t) as cnt
                """, device_id=device_id, lookback=lookback.isoformat())
                if res.single()["cnt"] > 0:
                    score += 15

            # 6. Rapid counterparty changes (+10)
            if receiver_id:
                recent_window = timestamp - timedelta(hours=2)
                res = session.run("""
                    MATCH (a:Account {id: $sender_id})-[:PERFORMED]->(t:Transaction)-[:TO]->(b:Account)
                    WHERE t.timestamp > $recent_window
                    RETURN count(DISTINCT b) as cnt
                """, sender_id=sender_id, recent_window=recent_window.isoformat())
                if res.single()["cnt"] > 5:
                    score += 10

            # 7. Merchant previously involved in fraud (+15)
            if merchant_id:
                res = session.run("""
                    MATCH (m:Merchant {id: $merchant_id})<-[:AT_MERCHANT]-(t:Transaction {is_fraud: true})
                    WHERE t.timestamp > $lookback
                    RETURN count(t) as cnt
                """, merchant_id=merchant_id, lookback=lookback.isoformat())
                if res.single()["cnt"] > 0:
                    score += 15

            # 8. SIM previously used in fraud (+15)
            if sim_imsi_hash:
                res = session.run("""
                    MATCH (s:SIM {imsi: $sim_imsi_hash})<-[:USES_SIM]-(a:Account)-[:PERFORMED]->(t:Transaction {is_fraud: true})
                    WHERE t.timestamp > $lookback
                    RETURN count(t) as cnt
                """, sim_imsi_hash=sim_imsi_hash, lookback=lookback.isoformat())
                if res.single()["cnt"] > 0:
                    score += 15

        return min(score, 100)

    def create_transaction_graph(self, tx_id: str, sender_id: str, receiver_id: str,
                                 device_id: str, ip: str, amount: float,
                                 timestamp: datetime, is_fraud: bool,
                                 source_system: str = "",
                                 merchant_id: str = "",
                                 sim_imsi_hash: str = ""):
        """
        Insert a transaction into Neo4j - IDEMPOTENT.
        Uses MERGE for ALL nodes and relationships.
        No duplicates will ever be created.
        """
        with self.driver.session() as session:
            # Main query: merge all nodes and relationships
            session.run("""
                MERGE (s:Account {id: $sender_id})
                MERGE (r:Account {id: $receiver_id})
                MERGE (d:Device {id: $device_id})
                MERGE (ip:IP {address: $ip})
                MERGE (t:Transaction {id: $tx_id})
                ON CREATE SET
                    t.amount = $amount,
                    t.timestamp = $timestamp,
                    t.is_fraud = $is_fraud,
                    t.source_system = $source_system,
                    t.created_at = datetime()
                ON MATCH SET
                    t.amount = $amount,
                    t.timestamp = $timestamp,
                    t.is_fraud = $is_fraud,
                    t.source_system = $source_system,
                    t.updated_at = datetime()
                WITH s, r, t, d, ip
                MERGE (s)-[:PERFORMED]->(t)
                MERGE (t)-[:TO]->(r)
                MERGE (s)-[:USED_DEVICE]->(d)
                MERGE (s)-[:LOGGED_IN_FROM]->(ip)
            """,
                sender_id=sender_id, receiver_id=receiver_id,
                device_id=device_id, ip=ip,
                tx_id=tx_id, amount=amount,
                timestamp=timestamp.isoformat(),
                is_fraud=is_fraud,
                source_system=source_system)

            # Merchant link (if present)
            if merchant_id:
                session.run("""
                    MERGE (m:Merchant {id: $merchant_id})
                    WITH m
                    MATCH (t:Transaction {id: $tx_id})
                    MERGE (t)-[:AT_MERCHANT]->(m)
                """, merchant_id=merchant_id, tx_id=tx_id)

            # SIM link (if present)
            if sim_imsi_hash:
                session.run("""
                    MERGE (sim:SIM {imsi: $sim_imsi_hash})
                    WITH sim
                    MATCH (a:Account {id: $sender_id})
                    MERGE (a)-[:USES_SIM]->(sim)
                """, sim_imsi_hash=sim_imsi_hash, sender_id=sender_id)