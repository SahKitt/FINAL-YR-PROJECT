import time
import signal
import sys
from typing import Optional
from datetime import datetime
import structlog
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from config import config
from database import DatabaseManager
from processor import TransactionProcessor

logger = structlog.get_logger(__name__)

# Prometheus gauge: always 1 if the engine is running
HEALTH_GAUGE = Gauge("rule_engine_health", "Rule engine health status (1 = healthy)")


class HealthHandler(BaseHTTPRequestHandler):
    """
    HTTP handler that responds to:
      - GET /          → returns 'OK' (used by Docker healthcheck)
      - GET /metrics   → returns Prometheus metrics in text format
      - GET *anything* → also returns 200 (safe for any health probes)
    """

    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_health_server(port: int):
    """
    Start a background HTTP server that serves /metrics and returns 200 for all paths.
    The gauge is set to 1 to indicate the service is healthy.
    """
    HEALTH_GAUGE.set(1)
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health + metrics server started on port {port}")


class RuleBasedEngine:
    """Main rule-based engine orchestrator with health/monitoring endpoint."""

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.processor = None
        self.is_running = False
        self.last_processed_id = None

    def start(self):
        """Start the rule engine, connect to databases, and begin processing."""
        logger.info("Starting Rule-Based Engine")

        # Connect to databases
        if not self.db_manager.connect():
            logger.error("Failed to connect to databases. Exiting.")
            sys.exit(1)

        # Ensure indexes exist for performance
        self.db_manager.create_indexes()

        # Start the health + metrics server
        start_health_server(config.METRICS_PORT)

        # Initialize the transaction processor
        self.processor = TransactionProcessor(self.db_manager)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.is_running = True

        # Enter the main processing loop
        self._run()

    def _run(self):
        """Main processing loop - checks for unprocessed data and processes it in batches."""
        logger.info("Entering main processing loop")

        while self.is_running:
            try:
                # Check if there is raw data to process
                if not self.db_manager.has_raw_data():
                    logger.info("No raw data to process. Waiting...")
                    time.sleep(config.IDLE_SLEEP_TIME)
                    continue

                # Process available data in batches
                self._process_batches()

                # Short sleep to prevent busy waiting
                time.sleep(config.PROCESSING_CHECK_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error("Error in main processing loop", error=str(e))
                time.sleep(5)

        self.stop()

    def _process_batches(self):
        """Fetch a batch of unprocessed transactions, apply rules, and store results."""
        batch_count = 0
        total_processed = 0

        while self.is_running and batch_count < 10:
            # Fetch a batch from the raw collection
            batch = self.db_manager.fetch_raw_batch(
                batch_size=config.PROCESSING_BATCH_SIZE,
                last_id=self.last_processed_id
            )

            if not batch:
                break

            start_time = time.time()

            # Process the batch (apply rules)
            processed_transactions = self.processor.process_batch(batch)

            if processed_transactions:
                # Save the ruled transactions to MongoDB
                success = self.db_manager.save_ruled_batch(processed_transactions)

                if success:
                    # Mark the raw transactions as processed
                    transaction_ids = [tx.transaction_id for tx in processed_transactions]
                    self.db_manager.mark_as_processed(transaction_ids)

                    # Update the cursor for pagination
                    if batch:
                        self.last_processed_id = str(batch[-1]['_id'])

                    total_processed += len(processed_transactions)

                    logger.info(
                        "Batch processed",
                        batch_size=len(batch),
                        processed=len(processed_transactions),
                        duration_seconds=time.time() - start_time
                    )

            batch_count += 1

            # Log progress periodically
            if batch_count % 5 == 0:
                logger.info("Batch processing progress",
                            batches_processed=batch_count,
                            total_transactions=total_processed)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.is_running = False

    def stop(self):
        """Clean shutdown: stop processor and close database connections."""
        logger.info("Stopping Rule-Based Engine")

        if self.processor:
            self.processor.shutdown()

        if self.db_manager:
            self.db_manager.disconnect()

        logger.info("Rule-Based Engine stopped")