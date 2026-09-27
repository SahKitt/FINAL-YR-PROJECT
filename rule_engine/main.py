import sys
import structlog
import time
from datetime import datetime

from config import config
from database import DatabaseManager
from engine import RuleBasedEngine

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger(__name__)


def wait_for_mongodb():
    """Wait for MongoDB to be available."""
    logger.info("Waiting for MongoDB connection...")
    max_retries = 10
    interval = 5
    
    db_manager = DatabaseManager()
    
    for attempt in range(max_retries):
        try:
            if db_manager.connect():
                logger.info("MongoDB connection successful")
                return db_manager
            else:
                logger.warning(f"MongoDB connection failed on attempt {attempt + 1}/{max_retries}")
        except Exception as e:
            logger.warning(f"MongoDB connection error: {e}")
        
        if attempt < max_retries - 1:
            logger.info(f"Retrying in {interval} seconds...")
            time.sleep(interval)
    
    logger.error("Failed to connect to MongoDB after multiple attempts")
    return None


def wait_for_consumer_data(db_manager):
    """Wait for consumer to populate some data."""
    if not config.WAIT_FOR_CONSUMER:
        return True
    
    logger.info("Waiting for consumer to populate data...")
    max_retries = 10
    interval = 2
    
    for attempt in range(max_retries):
        has_data = db_manager.has_raw_data()
        
        if has_data:
            count = db_manager.raw_collection.count_documents({})
            logger.info(f"Consumer data found: {count} transactions")
            return True
        else:
            logger.info(f"Waiting for consumer data... Attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(interval)
    
    logger.warning("No consumer data found after waiting. Starting anyway...")
    return False


def main():
    """Main function to start the rule engine."""
    logger.info("Rule-Based Engine Starting", timestamp=datetime.utcnow().isoformat())
    
    # Print configuration
    logger.info("Configuration loaded",
                mongo_database=config.MONGO_DATABASE,
                batch_size=config.MONGO_BATCH_SIZE,
                processing_batch_size=config.PROCESSING_BATCH_SIZE,
                workers=config.RULE_ENGINE_WORKERS)
    
    try:
        # Wait for MongoDB
        db_manager = wait_for_mongodb()
        if not db_manager:
            sys.exit(1)
        
        # Wait for consumer data
        wait_for_consumer_data(db_manager)
        db_manager.disconnect()
        
        # Start rule engine
        engine = RuleBasedEngine()
        engine.start()
        
    except KeyboardInterrupt:
        logger.info("Rule engine stopped by user")
    except Exception as e:
        logger.error("Rule engine failed", error=str(e))
        sys.exit(1)
    finally:
        logger.info("Rule engine shutdown complete")


if __name__ == "__main__":
    main()