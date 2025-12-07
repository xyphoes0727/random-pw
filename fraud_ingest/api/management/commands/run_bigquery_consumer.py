"""
Django management command to consume messages from Kafka and batch-insert
them into a Google BigQuery table.

The consumer is configured to listen to the 'enriched' Kafka topic.
It uses a batching mechanism based on size (BATCH_SIZE) or time
(BATCH_INTERVAL_SECS) to efficiently upload data to BigQuery.
"""


import json
from django.core.management.base import BaseCommand
from confluent_kafka import Consumer, KafkaError
from google.cloud import bigquery
import os
from dotenv import load_dotenv
import time
from typing import List, Dict, Any

from .log_config.log_config import get_logger
logger = get_logger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)


KAFKA_TOPICS = ['enriched']
KAFKA_CONFIG_BIGQUERY = {
    'bootstrap.servers': os.environ.get(
        'KAFKA_BOOTSTRAP_SERVERS', 'pk_kafka:9093'),
    'group.id': 'bigquery',
    'auto.offset.reset': 'earliest'
}

BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
BATCH_INTERVAL_SECS = float(os.environ.get("BATCH_INTERVAL_SECS", "5"))

GCP_PROJECT = os.environ.get("GCP_PROJECT")
if not GCP_PROJECT:
    client = None
    table_id = "error.placeholder"
else:
    try:
        client = bigquery.Client(project=GCP_PROJECT)
        table_id = f"{GCP_PROJECT}.pathway.enriched-data"
        logger.info(f"BigQuery client initialized for project: {GCP_PROJECT}")
        logger.info(f"Target BigQuery table: {table_id}")

    except Exception as e:
        logger.error(f"Failed to initialize BigQuery client: {e}")
        client = None


class Command(BaseCommand):
    """
    Custom Django management command to run the BigQuery Kafka consumer.

    The command initializes a Kafka consumer, subscribes to configured topics,
    and runs an infinite loop to poll for messages, batch them, and flush
    the batch to BigQuery.
    """

    def handle(self, *args, **options):
        if not client:
            logger.error("BigQuery client is not properly initialized.")
            return

        consumer = Consumer(KAFKA_CONFIG_BIGQUERY)
        consumer.subscribe(KAFKA_TOPICS)
        logger.info(f"Subscribed to Kafka topics for BigQuery: {KAFKA_TOPICS}")

        batch_rows: List[Dict[str, Any]] = []
        last_flush_time = time.time()

        def flush_batch(reason: str = "timer"):
            nonlocal batch_rows, last_flush_time
            if not batch_rows:
                return
            start = time.time()
            rows_to_insert = batch_rows
            batch_count = len(rows_to_insert)

            try:
                errors = client.insert_rows_json(table_id, rows_to_insert)
                elapsed = time.time() - start
                if errors:
                    logger.error(
                        f"BigQuery batch insert failed ({reason}). "
                        f"Rows: {batch_count}. Errors: {errors}"
                    )
                else:
                    logger.info(
                        f"BigQuery batch insert succeeded ({reason}). "
                        f"Rows: {batch_count}. Table: {table_id}."
                        f"Time: {elapsed:.3f}s"
                    )
                    try:
                        consumer.commit()
                    except Exception as e:
                        logger.warning(f"Failed to commit Kafka offsets"
                                       f" after batch insert: {e}")

            except Exception as e:
                logger.error(
                    f"Unexpected error during BigQuery batch insert: {e}",
                    exc_info=True)
            finally:
                batch_rows = []
                last_flush_time = time.time()

        try:
            while True:
                msg = consumer.poll(timeout=1.0)

                current_time = time.time()
                if ((current_time - last_flush_time) >= BATCH_INTERVAL_SECS
                        and batch_rows):
                    flush_batch(reason="interval")

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(f"Kafka error: {msg.error()}")
                        time.sleep(5)
                        continue

                topic = msg.topic()
                try:
                    raw = msg.value()
                    if isinstance(raw, bytes):
                        payload = raw.decode('utf-8')
                    else:
                        payload = raw

                    data = json.loads(payload)

                    row = self._transform_message(data)

                    if row is None:
                        continue

                    batch_rows.append(row)
                    if len(batch_rows) >= BATCH_SIZE:
                        flush_batch(reason="size")

                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode JSON from "
                                   f"topic {topic}: {msg.value()}")
                except Exception as e:
                    logger.error("General error message for BigQuery: "
                                 f"{e}", exc_info=True)

        except KeyboardInterrupt:
            logger.info("Stopping BigQuery consumer")
            try:
                flush_batch(reason="shutdown")
            except Exception as e:
                logger.error(f"Error while flushing during shutdown: {e}",
                             exc_info=True)
        except Exception as e:
            logger.exception(f"Unexpected exception in consumer loop: {e}")
            try:
                flush_batch(reason="exception")
            except Exception as e2:
                logger.exception(f"Error flushing after exception: {e2}")
        finally:
            logger.info("Closing Kafka consumer for BigQuery.")
            consumer.close()

    def _transform_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row = dict(data)

            row['origMoreSentFlag'] = (
                1 if row.get('origMoreSentFlag') is True else 0)
            row['destMoreRecFlag'] = (
                1 if row.get('destMoreRecFlag') is True else 0)

            if "time" in row:
                try:
                    ts_val = row["time"]
                    if isinstance(ts_val, str):
                        ts_val = float(ts_val)
                    feature_ts = int(ts_val * 1e-9)
                except Exception:
                    logger.warning(f"Failed to convert 'time' to "
                                   f"feature_timestamp for row:"
                                   f"{row.get('id', '<no id>')}")
                    return None
                del row["time"]
                row["feature_timestamp"] = feature_ts
            else:
                logger.warning(f"Message missing 'time' field; dropping"
                               f"row: {row.get('id', '<no id>')}")
                return None

            return row

        except Exception as e:
            logger.error(f"Error transforming message for BigQuery: {e}",
                         exc_info=True)
            return None
