FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y wget xz-utils fontconfig libfreetype6 libjpeg62-turbo libpng16-16 \
    && wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && apt-get install -y ./wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && rm wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && rm -rf /var/lib/apt/lists/*


RUN apt-get update \
    && apt-get install -y g++ default-mysql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


RUN opentelemetry-bootstrap -a install
COPY fraud_ingest/ /app/
WORKDIR /app

RUN mkdir -p data

COPY ml_engine/ /app/ml_engine/

ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# CMD ["uvicorn","fraud_ingest.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
CMD ["opentelemetry-instrument","gunicorn", "fraud_ingest.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--workers", "4","--bind", "0.0.0.0:8000"]

