from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path('ws/metrics', consumers.MetricConsumer.as_asgi()),
    re_path('ws/logs', consumers.LogsConsumer.as_asgi()),
    re_path('ws/traces', consumers.TraceConsumer.as_asgi()),
    re_path('ws/ambientlogs', consumers.AmbientAgentLogs.as_asgi()),
    re_path('ws/kafka', consumers.KafkaMLConsumer.as_asgi()),
    re_path("ws/transaction_time", consumers.TransactionTimeData.as_asgi()),
    re_path("ws/ml_health", consumers.MLHealth.as_asgi())

]
