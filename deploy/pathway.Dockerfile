FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libjemalloc2 \
    default-mysql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt  

COPY fraud_ingest/ ./fraud_ingest/

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "fraud_ingest.pathway.preprocessor"]
