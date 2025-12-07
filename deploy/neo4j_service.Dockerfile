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

COPY neo4j_service/ ./neo4j_service/

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "neo4j_service.main"]
