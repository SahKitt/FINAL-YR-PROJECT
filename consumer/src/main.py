from confluent_kafka import Consumer, KafkaError
import json, signal, sys, os, threading, traceback
from datetime import datetime
from time import time, sleep
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from typing import Dict, Any, List

from prometheus_client import start_http_server, Counter, Gauge

from .normalizer import TransactionNormalizer
from .validator import TransactionValidator
from .mongo_handler import MongoDBHandler

class TransactionConsumer:
    def __init__(self):
        print(f"[{datetime.utcnow().isoformat()}] [TransactionConsumer] Initializing", flush=True)

        # ---- Prometheus metrics server  ----
        self._start_metrics_server()

        self.normalizer = TransactionNormalizer()
        self.validator = TransactionValidator()
        self.mongo_handler = MongoDBHandler(collection_prefix="")
        self.kafka_conf = {
            'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"),
            'group.id': os.getenv("KAFKA_CONSUMER_GROUP_ID", "transaction-consumers"),
            'auto.offset.reset': 'earliest',
            'session.timeout.ms': 60000, 'heartbeat.interval.ms': 10000, 'max.poll.interval.ms': 1200000,
            'enable.auto.commit': True, 'enable.auto.offset.store': False,
            'fetch.message.max.bytes': 52428800 * 2, 'receive.message.max.bytes': 524288000,
            'queued.min.messages': 100000, 'fetch.wait.max.ms': 50,
            'enable.partition.eof': False, 'allow.auto.create.topics': False,
        }
        self.consumer = Consumer(self.kafka_conf)
        self.topics = [os.getenv("KAFKA_TRANSACTIONS_TOPIC", "transactions_topic"),
                       os.getenv("KAFKA_BAD_RECORDS_TOPIC", "bad_records_topic")]
        self.running = False
        self.batch_size = int(os.getenv("BATCH_SIZE", "20000"))
        self.max_workers = int(os.getenv("MAX_WORKERS", "100"))
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.processed_count = 0; self.total_inserted = 0; self.total_errors = 0; self.last_report_time = time()
        self.batch_queue = deque(maxlen=50); self.batch_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.shutdown); signal.signal(signal.SIGTERM, self.shutdown)

    def _start_metrics_server(self):
        """Start a Prometheus metrics HTTP server in a daemon thread."""
        port = int(os.getenv("METRICS_PORT", "9091"))
        try:
            # Create some basic metrics (they will appear in /metrics)
            self.transactions_processed = Counter('consumer_processed_total', 'Total transactions processed')
            self.transactions_errors = Counter('consumer_errors_total', 'Total transactions rejected')
            self.queue_size = Gauge('consumer_queue_size', 'Current batch queue size')

            threading.Thread(target=lambda: start_http_server(port), daemon=True).start()
            print(f"[{datetime.utcnow().isoformat()}] [Consumer] Prometheus metrics server started on port {port}",
                  flush=True)
        except Exception as e:
            print(f"[{datetime.utcnow().isoformat()}] [Consumer] Failed to start metrics server: {e}", flush=True)

    def start(self):
        self.consumer.subscribe(self.topics)
        self.running = True
        threading.Thread(target=self._performance_monitor, daemon=True).start()
        threading.Thread(target=self._batch_processor, daemon=True).start()
        batch, batch_start_time = [], time()
        while self.running:
            try:
                msgs = self.consumer.consume(num_messages=5000, timeout=1.0)
                if not msgs:
                    if batch and (len(batch) >= self.batch_size or time() - batch_start_time > 1.0):
                        self._submit_batch(batch); batch = []; batch_start_time = time()
                    continue
                for msg in msgs:
                    if msg.error():
                        if msg.error().code() != KafkaError._PARTITION_EOF:
                            print(f"Kafka error: {msg.error()}", flush=True)
                        continue
                    try:
                        message = json.loads(msg.value())
                        if 'transactions' in message and 'source' in message:
                            for tx in message['transactions']:
                                tx['_source_system'] = message['source']
                                tx['_ingested_at'] = datetime.utcnow()
                                batch.append(tx)
                        else:
                            message['_ingested_at'] = datetime.utcnow()
                            batch.append(message)
                    except json.JSONDecodeError as e:
                        self.mongo_handler.insert_bad_record(
                            raw_data=msg.value() or {},
                            error_message=f"JSON error: {e}",
                            source="consumer",
                            error_type="JSON_PARSE_ERROR"
                        )
                if len(batch) >= self.batch_size or (batch and time() - batch_start_time > 1.0):
                    self._submit_batch(batch); batch = []; batch_start_time = time()
            except Exception as e:
                print(f"CRITICAL: {e}", flush=True); sleep(1)
        if batch: self._submit_batch(batch)
        self.shutdown()

    def _submit_batch(self, batch):
        if not batch: return
        with self.batch_lock:
            while len(self.batch_queue) >= self.batch_queue.maxlen:
                sleep(0.1)
            self.batch_queue.append(batch.copy())

    def _batch_processor(self):
        while self.running:
            batch = None
            with self.batch_lock:
                if self.batch_queue: batch = self.batch_queue.popleft()
            if batch:
                self.executor.submit(self._process_batch, batch)
            else:
                sleep(0.01)

    def _process_batch(self, batch):
        valid, invalid = [], []
        for msg in batch:
            try:
                normalized = self.normalizer.normalize(msg)
                if not normalized:
                    invalid.append({'data': msg, 'error': 'Normalization failed',
                                    'source': msg.get('_source_system', 'unknown')})
                    continue
                norm_dict = normalized.model_dump()
                is_valid, errors = self.validator.validate(norm_dict)
                if is_valid:
                    valid.append(norm_dict)
                else:
                    invalid.append({'data': norm_dict, 'errors': errors,
                                    'source': msg.get('_source_system', 'unknown')})
            except Exception as e:
                invalid.append({'data': msg, 'error': str(e), 'source': 'unknown'})

        if valid:
            inserted = self.mongo_handler.batch_insert(valid)
            self.total_inserted += inserted
            self.processed_count += inserted
            self.transactions_processed.inc(inserted)               

        for rec in invalid:
            msg_text = rec.get('error') or ", ".join(rec.get('errors', []))
            self.mongo_handler.insert_bad_record(
                raw_data=rec['data'],
                error_message=msg_text[:500],
                source=rec.get('source', 'unknown'),
                error_type="VALIDATION_ERROR"
            )
            self.total_errors += 1
            self.transactions_errors.inc()                       

        self.queue_size.set(len(self.batch_queue))              

    def _performance_monitor(self):
        while self.running:
            sleep(30)
            now = time(); diff = now - self.last_report_time
            if diff > 0:
                tps = self.processed_count / diff
                print(f"[{datetime.utcnow().isoformat()}] TPS={tps:,.0f}, Inserted={self.total_inserted}, "
                      f"Errors={self.total_errors}, Queue={len(self.batch_queue)}", flush=True)
                self.processed_count = 0; self.last_report_time = now

    def shutdown(self, signum=None, frame=None):
        print("Shutting down...", flush=True)
        self.running = False; sleep(2)
        self.executor.shutdown(wait=True, cancel_futures=True)
        try: self.consumer.close()
        except: pass
        self.mongo_handler.close()
        print(f"Shutdown. Inserted={self.total_inserted}, Errors={self.total_errors}", flush=True)

if __name__ == "__main__":
    TransactionConsumer().start()