import joblib
import pandas as pd
import os
from xgboost import XGBClassifier

MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/xgb_fraud_model.pkl")

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract features from a DataFrame that may contain a single transaction.
    Handles missing columns by filling with defaults (0 or empty string).
    """
    feats = pd.DataFrame(index=df.index)
    
    # Numeric fields – fill missing with 0
    feats['amount'] = df.get('amount', pd.Series([0]*len(df))).fillna(0)
    feats['total_risk_score'] = df.get('total_risk_score', pd.Series([0]*len(df))).fillna(0)
    feats['fee'] = df.get('fee', pd.Series([0]*len(df))).fillna(0)
    
    # Categorical fields – convert to category codes, missing → 0
    for col in ['transaction_type', 'source_system', 'currency', 'merchant_category', 'country_code']:
        if col in df.columns:
            feats[col] = df[col].astype('category').cat.codes
        else:
            feats[col] = 0
    
    # Temporal features – if timestamp missing, use current time
    if 'timestamp' in df.columns:
        ts = pd.to_datetime(df['timestamp'])
    else:
        ts = pd.Timestamp.utcnow()
    feats['hour'] = ts.dt.hour if hasattr(ts, 'dt') else ts.hour
    feats['day_of_week'] = ts.dt.dayofweek if hasattr(ts, 'dt') else ts.dayofweek
    feats['is_weekend'] = (feats['day_of_week'] >= 5).astype(int)
    
    # Number of triggered rules
    feats['num_triggered_rules'] = df.get('triggered_rules', pd.Series([[]]*len(df))).apply(
        lambda x: len(x) if isinstance(x, list) else 0
    )
    
    return feats.fillna(0)


class ModelManager:
    def __init__(self, path=MODEL_PATH):
        self.path = path
        self.model = None
        self.feature_columns = []
        if os.path.exists(path):
            self.load()
        else:
            print("[Model] No existing model found. Will seed-train on startup.")

    def load(self):
        data = joblib.load(self.path)
        self.model = data['model']
        self.feature_columns = data['feature_columns']
        print(f"[Model] Loaded model with features: {self.feature_columns}")

    def save(self):
        joblib.dump({
            'model': self.model,
            'feature_columns': self.feature_columns
        }, self.path)
        print("[Model] Model saved to disk.")

    def predict_proba(self, transaction: dict) -> float:
        """Return fraud probability (0..1) for a single transaction."""
        df = pd.DataFrame([transaction])
        X = build_features(df)
        # Align columns to trained model
        for col in self.feature_columns:
            if col not in X.columns:
                X[col] = 0
        X = X[self.feature_columns]
        return float(self.model.predict_proba(X)[0][1])

    async def train_seed_model(self, mongo_uri: str, db_name: str):
        """
        Build an initial model from ruled_transactions (proxy labels).
        Use risk_level: critical/high → fraud (1), else normal (0).
        """
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(mongo_uri)
        db = client[db_name]
        docs = await db.ruled_transactions.find().limit(10000).to_list(10000)
        if len(docs) < 100:
            print("[Seed] Not enough data. Creating a dummy model (always returns 0.5).")
            self._create_dummy_model()
            return

        df = pd.DataFrame(docs)
        df['label'] = df['risk_level'].apply(lambda x: 1 if x in ['critical', 'high'] else 0)
        X = build_features(df)
        y = df['label']

        self.model = XGBClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            use_label_encoder=False, eval_metric='logloss', random_state=42
        )
        self.model.fit(X, y)
        self.feature_columns = X.columns.tolist()
        self.save()
        print(f"[Seed] Seeded model on {len(df)} ruled transactions.")

    def _create_dummy_model(self):
        """Fallback: a trivial model that outputs 0.5."""
        self.model = XGBClassifier(n_estimators=1, max_depth=1)
        dummy_X = pd.DataFrame([{
            'amount': 0, 'transaction_type': 0, 'source_system': 0,
            'currency': 0, 'hour': 0, 'day_of_week': 0,
            'is_weekend': 0, 'total_risk_score': 0,
            'num_triggered_rules': 0, 'fee': 0,
            'merchant_category': 0, 'country_code': 0
        }])
        dummy_y = [0]
        self.model.fit(dummy_X, dummy_y)
        self.feature_columns = dummy_X.columns.tolist()
        self.save()