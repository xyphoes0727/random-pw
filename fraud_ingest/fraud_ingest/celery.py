from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fraud_ingest.settings")

app = Celery("fraud_ingest")
# Load Django settings (EMAIL_BACKEND, DATABASES, etc.)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks from the "api" app
app.autodiscover_tasks(['api'])

# Celery settings (broker, backend)
app.conf.update(
    broker_url="amqp://my_user:my_password@rabbitmq:5672/myvhost",
    result_backend="rpc://",
)

app.conf.beat_schedule = {
    "run-model-health-every-10-seconds": {
        "task": "api.tasks.model_health_task",
        "schedule": 10.0,
    },
}
