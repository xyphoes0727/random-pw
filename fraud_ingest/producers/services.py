from confluent_kafka import SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from django.conf import settings
from fraud_ingest.schemas.registry import KEY_SCHEMA, VALUE_SCHEMA
from .config import PRODUCER_CONFIG


class ProducerService:
    def __init__(self):
        self.schema_registry = SchemaRegistryClient({
            "url": settings.SCHEMA_REGISTRY_URL
            })
        key_ser = AvroSerializer(self.schema_registry, KEY_SCHEMA)
        val_ser = AvroSerializer(self.schema_registry, VALUE_SCHEMA)

        self.producer = SerializingProducer({
            **PRODUCER_CONFIG,
            "key.serializer": key_ser,
            "value.serializer": val_ser,
        })

    def send(self, topic: str, key: dict, value: dict):
        def delivery(err, msg):
            if err:
                print(f"Delivery failed: {err}")
            else:
                print(f"Produced to {msg.topic()}")
                # better logger here for production ready

        self.producer.produce(
            topic=topic,
            key=key,
            value=value,
            on_delivery=delivery,
        )
        self.producer.poll(0)

    def flush(self):
        self.producer.flush()
