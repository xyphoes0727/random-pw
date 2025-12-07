FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    default-mysql-client \
    curl \
    unzip \
    zip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements2.txt .

RUN pip install --no-cache-dir beartype==0.15.0

RUN pip install --no-cache-dir pathway==0.26.4
RUN pip install --no-cache-dir py-key-value-shared==0.3.0
RUN pip install --no-cache-dir py-key-value-aio==0.3.0
RUN pip install --no-cache-dir fastmcp==2.13.2

RUN pip install --no-cache-dir -r requirements2.txt

COPY ./fraud_ingest/api .
ENV PYTHONUNBUFFERED=1

CMD ["python", "mcpagent.py"]
