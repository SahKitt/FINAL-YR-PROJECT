import os
from dataclasses import dataclass, field
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    """Configuration for the rule engine."""
    
    # MongoDB Configuration
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://host.docker.internal:27017/")
    MONGO_DATABASE: str = os.getenv("MONGO_DATABASE", "transactions_db")
    MONGO_RAW_COLLECTION: str = os.getenv("MONGO_RAW_COLLECTION", "raw_transactions")
    MONGO_RULED_COLLECTION: str = os.getenv("MONGO_RULED_COLLECTION", "ruled_transactions")
    MONGO_BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "1000"))
    
    # Redis Configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    
    # Rule Engine Configuration
    RULE_ENGINE_WORKERS: int = int(os.getenv("RULE_ENGINE_WORKERS", "10"))
    PROCESSING_BATCH_SIZE: int = int(os.getenv("PROCESSING_BATCH_SIZE", "5000"))
    MAX_PROCESSING_TIME: int = int(os.getenv("MAX_PROCESSING_TIME", "300"))
    PROCESSING_CHECK_INTERVAL: int = int(os.getenv("PROCESSING_CHECK_INTERVAL", "5"))
    IDLE_SLEEP_TIME: int = int(os.getenv("IDLE_SLEEP_TIME", "10"))
    
    # Consumer Dependency Settings
    WAIT_FOR_CONSUMER: bool = os.getenv("WAIT_FOR_CONSUMER", "true").lower() == "true"
    CONSUMER_HEALTH_CHECK_MAX_RETRIES: int = int(os.getenv("CONSUMER_HEALTH_CHECK_MAX_RETRIES", "10"))
    CONSUMER_HEALTH_CHECK_INTERVAL: int = int(os.getenv("CONSUMER_HEALTH_CHECK_INTERVAL", "10"))
    
    # Risk Score Thresholds
    RISK_SCORE_THRESHOLD_LOW: int = int(os.getenv("RISK_SCORE_THRESHOLD_LOW", "0"))
    RISK_SCORE_THRESHOLD_MEDIUM: int = int(os.getenv("RISK_SCORE_THRESHOLD_MEDIUM", "5"))
    RISK_SCORE_THRESHOLD_HIGH: int = int(os.getenv("RISK_SCORE_THRESHOLD_HIGH", "10"))
    
    # Rule Thresholds
    HIGH_AMOUNT_THRESHOLD_USD: float = float(os.getenv("HIGH_AMOUNT_THRESHOLD_USD", "2000.0"))
    VELOCITY_WINDOW_MINUTES: int = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
    MAX_TRANSACTIONS_PER_WINDOW: int = int(os.getenv("MAX_TRANSACTIONS_PER_WINDOW", "3"))
    
    # Geolocation Rules
    IMPOSSIBLE_TRAVEL_KM: float = float(os.getenv("IMPOSSIBLE_TRAVEL_KM", "1000.0"))
    IMPOSSIBLE_TRAVEL_MINUTES: int = int(os.getenv("IMPOSSIBLE_TRAVEL_MINUTES", "30"))
    
    # High Risk Countries 
    HIGH_RISK_COUNTRIES: List[str] = field(
        default_factory=lambda: os.getenv("HIGH_RISK_COUNTRIES", "IR,SY,KP,CU,RU,BY,MM").split(",")
    )
    
    # High Risk MCC 
    HIGH_RISK_MCC: List[str] = field(
        default_factory=lambda: os.getenv("HIGH_RISK_MCC", "7996,4829,6051").split(",")
    )
    
    # Monitoring
    METRICS_PORT: int = int(os.getenv("RULE_ENGINE_METRICS_PORT", "9092"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    @property
    def redis_url(self) -> str:
        """Get Redis connection URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

config = Config()