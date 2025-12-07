"""Django management command to stream transactions from a CSV to Kafka.

Reads a CSV, partitions messages deterministically by sender ID, and produces
JSON records to the configured Kafka topic with backpressure handling and
progress logging.
"""

from django.core.management.base import BaseCommand
from confluent_kafka import Producer
import pandas as pd
import json
import time
import os
import hashlib
from loguru import logger


def user_partitioner(key, partition_count):
    """Deterministic partitioner based on MD5 of the message key.

    Args:
        key: The message key (string). If None, defaults to partition 0.
        partition_count: Total number of Kafka partitions.

    Returns:
        Integer partition index in ``[0, partition_count)``.
    """
    if key is None:
        return 0
    hash_val = int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16)
    return hash_val % partition_count


class Command(BaseCommand):
    """Produce Kafka messages from a CSV file.

    Usage:
        python manage.py produce_from_csv --file path/to/file.csv

    The command reads the CSV, builds JSON payloads per row, and enqueues them
    to Kafka with periodic progress and final throughput reporting.
    """

    def add_arguments(self, parser):
        """Define CLI arguments for the command."""
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="test_paysim.csv",
        )

    def handle(self, *args, **options):
        """Execute the producer flow.

        Steps:
        - Read the CSV file.
        - Initialize Kafka Producer.
        - Produce JSON messages with deterministic partitioning.
        - Handle local queue backpressure via polling.
        - Flush and report throughput.
        """
        logger.info("Starting CSV reading")
        file_path = options["file"]

        try:
            load_start = time.time()    
            df = pd.read_csv(file_path)
            load_end = time.time()
            logger.info(f"Loaded CSV file in {load_end - load_start:.2f} seconds.")
        except Exception as e:
            logger.error(f"Failed to read CSV: {e}")
            self.stdout.write(self.style.ERROR(f"Failed to read CSV: {e}"))
            return

        start_time = time.time()
        logger.info("Initializing Kafka producer...")

        json_producer_conf = {
            'bootstrap.servers': os.environ.get(
                                    "KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"),
        }
        json_producer = Producer(json_producer_conf)
        num_rows = len(df)
        logger.info(f"Producing {num_rows} rows messages to Kafka")

        for i, (_, row) in enumerate(df.iterrows()):
            txn_id = str(row["transactionId"])
            name_orig = str(row["nameOrig"])

            value = {
                "transactionId": txn_id,
                "step": int(row["step"]),
                "type": int(row["type"]),
                "amount": float(row["amount"]),
                "nameOrig": name_orig,
                "oldbalanceOrg": float(row["oldbalanceOrg"]),
                "newbalanceOrig": float(row["newbalanceOrig"]),
                "nameDest": str(row["nameDest"]),
                "oldbalanceDest": float(row["oldbalanceDest"]),
                "newbalanceDest": float(row["newbalanceDest"]),
                "isFraud": int(row["isFraud"]),
            }

            partition = user_partitioner(name_orig, partition_count=9)

            while True:
                try:
                    json_producer.produce(
                        topic='transactions-raw',
                        key=name_orig.encode('utf-8'),
                        value=json.dumps(value).encode('utf-8'),
                        partition=partition,
                    )
                    break
                except BufferError:
                    logger.warning(
                        f"Producer queue full at message {i}. "
                        "Polling for 1s..."
                    )
                    self.stdout.write(self.style.WARNING(
                        f"Local queue full at message {i}. Polling for 1s..."))
                    json_producer.poll(1)

            if i % 50000 == 0 and i > 0:
                self.stdout.write(self.style.SUCCESS(
                    f"Progress: {i}/{num_rows} messages queued..."))

        logger.info("All messages queued. Flushing final messages...")
        self.stdout.write(self.style.SUCCESS(
            "All messages queued. Flushing final messages..."))
        flush_start = time.time()
        json_producer.flush()
        logger.info(f"Flush completed in {time.time() - flush_start:.2f}s")

        total_time = time.time() - start_time
        thru = len(df) / total_time if total_time > 0 else 0

        self.stdout.write(self.style.SUCCESS(
            f"Produced {len(df)} records to topic in {total_time:.2f}"
            f"seconds ({thru:.2f} records/sec)."
        ))
        logger.info(
            f"Produced {len(df)} records to topic in {total_time:.2f}"
            f"seconds ({thru:.2f} records/sec)."
        )
