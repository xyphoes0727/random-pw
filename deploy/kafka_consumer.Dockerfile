FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    default-mysql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN opentelemetry-bootstrap -a install

COPY fraud_ingest/ ./fraud_ingest/

COPY ml_engine/ /app/ml_engine/

WORKDIR /app/fraud_ingest

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"
CMD ["sh", "-c", "python manage.py run_kafka_consumer"]
