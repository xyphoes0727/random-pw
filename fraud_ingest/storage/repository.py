"""Repository helpers for storing raw transactions, ingest logs, and enriched records.

Provides thin wrappers around Django ORM operations to insert data into
TransactionRaw, IngestLog, and EnrichedData tables with consistent logging.
"""

from .models import TransactionRaw, IngestLog
from fraud_ingest.settings import logger
from storage.models import EnrichedData


def insert_transaction(
        record: dict
) -> TransactionRaw:
    """Insert a raw transaction record into the database.

    Args:
        record: Dict containing transaction fields such as transaction_id,
            user_id, amount, timestamp, and optional metadata (device_id, ip, etc.).

    Returns:
        The created ``TransactionRaw`` ORM instance.
    """
    return TransactionRaw.objects.create(
        transaction_id=record["transaction_id"],
        user_id=record["user_id"],
        from_account=record.get("from_account"),
        to_account=record.get("to_account"),
        amount=record["amount"],
        timestamp_ms=record["timestamp"],
        device_id=record.get("device_id"),
        ip=record.get("ip"),
        channel=record.get("channel"),
        geo_country=record.get("geo_country"),
        merchant_id=record.get("merchant_id"),
        status=record.get("status"),
    )


def log_ingest(topic, partition, offset, key, status, error=None):
    """Create an ingest log entry.

    Args:
        topic: Kafka topic name.
        partition: Kafka partition number.
        offset: Message offset.
        key: Message key.
        status: Status string (e.g., 'OK', 'ERROR').
        error: Optional error message.

    Returns:
        The created ``IngestLog`` ORM instance.
    """
    return IngestLog.objects.create(
        topic=topic,
        partition=partition,
        offset=offset,
        key=key,
        status=status,
        error=error,
    )


def insert_enriched_record(
        v: dict
        ) -> EnrichedData:
    """Upsert an enriched record by transaction_id.

    Args:
        v: Dict payload including ``transaction_id``, optional ``features``,
           and ``model_score``.

    Returns:
        The upserted ``EnrichedData`` ORM instance.
    """
    from storage.models import EnrichedData
    obj, _ = EnrichedData.objects.update_or_create(
        transaction_id=v["transaction_id"],
        defaults={
            "features": v.get("features", {}),
            "model_score": v.get("model_score"),
            "payload": v,
        },
    )
    logger.info(f"[ENRICHED-UPSERT] tx={v['transaction_id']}")
    return obj
