
from django.db import models


class EnrichedData(models.Model):
    transaction_id = models.CharField(
        max_length=255, unique=True, db_index=True)
    features = models.JSONField()   
    model_score = models.FloatField(null=True)
    payload = models.JSONField()    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enriched_data"

    def __str__(self):
        return f"EnrichedData({self.transaction_id})"
