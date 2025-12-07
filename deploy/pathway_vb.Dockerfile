FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y \
        g++ \
        curl \
        tesseract-ocr \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libde265-dev \
        libheif1 \
    && rm -rf /var/lib/apt/lists/*


COPY requirements_h.txt .
RUN pip install --no-cache-dir -r requirements_h.txt

COPY requirements_l.txt .
RUN pip install --no-cache-dir -r requirements_l.txt

COPY fraud_ingest /app/fraud_ingest
COPY .env /app/.env

RUN mkdir -p /app/data

ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "fraud_ingest.pathway_vb.runVectorStore"]
