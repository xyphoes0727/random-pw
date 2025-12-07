from django.db import models
# from django.contrib.postgres.fields import JSONField


class TransactionRaw(models.Model):
    transaction_id = models.CharField(max_length=64, db_index=True)
    user_id = models.CharField(max_length=64, db_index=True)
    from_account = models.CharField(max_length=64, null=True, blank=True)
    to_account = models.CharField(max_length=64, null=True, blank=True)
    amount = models.FloatField()
    timestamp_ms = models.BigIntegerField(db_index=True)
    device_id = models.CharField(max_length=64, null=True, blank=True)
    ip = models.CharField(max_length=45, null=True, blank=True)
    channel = models.CharField(max_length=50, null=True, blank=True)
    geo_country = models.CharField(max_length=10, null=True, blank=True)
    merchant_id = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=50, null=True, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "transaction_raw"


class IngestLog(models.Model):
    topic = models.CharField(max_length=128)
    partition = models.IntegerField()
    offset = models.BigIntegerField()
    key = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=32)  # SUCCESS / FAIL
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingest_log"
        indexes = [models.Index(fields=["topic", "partition", "offset"])]


class EnrichedData(models.Model):
    transaction_id = models.CharField(max_length=255)
    features = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
