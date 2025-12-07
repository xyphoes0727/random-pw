import json
import logging
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from confluent_kafka import Consumer, KafkaError
from api.models import Enriched, UserProfile, MLPrediction
import os

logger = logging.getLogger(__name__)

KAFKA_TOPICS = ['enriched', 'user_profiles', 'ml_prediction']
KAFKA_CONFIG = {
    'bootstrap.servers': os.environ.get('KAFKA_BOOTSTRAP_SERVERS',
                                        'pk_kafka:9093'),
    'group.id': 'db',
    'auto.offset.reset': 'earliest'
}


class Command(BaseCommand):
    help = 'Runs the Kafka consumer to write data to the database via the ORM'

    def handle(self, *args, **options):
        consumer = Consumer(KAFKA_CONFIG)
        consumer.subscribe(KAFKA_TOPICS)
        logger.info(f"Subscribed to Kafka topics: {KAFKA_TOPICS}")

        try:
            while True:
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(f"Kafka error: {msg.error()}")
                        break

                topic = msg.topic()
                try:
                    data = json.loads(msg.value().decode('utf-8'))
                    self.process_message(topic, data)

                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode JSON: {msg.value()}")
                except IntegrityError as e:
                    logger.warning(f"DB IntegrityError: {e}. Data: {data}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except KeyboardInterrupt:
            logger.info("Stopping consumer...")
        finally:
            logger.info("Closing Kafka consumer.")
            consumer.close()

    def process_message(self, topic, data):
        if topic == 'enriched':
            if 'type' in data and 'transaction_type' not in data:
                data['transaction_type'] = data.pop('type')

            Enriched.objects.update_or_create(**data)
            logger.info(f"Created Enriched: {data.get('transactionId')}")

        elif topic == 'user_profiles':
            account = data.pop('account')

            UserProfile.objects.update_or_create(account=account,
                                                 defaults=data)
            logger.info(f"Updated/Created UserProfile: {account}")

        elif topic == 'ml_prediction':
            if 'transactionId' in data and 'transaction_id' not in data:
                data['transaction_id'] = data.pop('transactionId')

            MLPrediction.objects.create(**data)
            logger.info(
                "Created MLPrediction for: %s", data.get("transaction_id")
            )
