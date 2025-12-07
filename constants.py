# DeltaLake
TOPIC_TRANSACTIONS = 'transactions'
# KAFKA_DLT_TOPIC = 'transactions.DLT'
KAFKA_SOURCE_TOPIC = 'transactions'
# TOPIC_TRANSACTIONS_DLT = 'transactions_DLT'

# Consumer/Producer tuning
CONSUMER_GROUP = 'fraud-consumer'
CONSUMER_MAX_RETRIES = 3
CONSUMER_BACKOFF_BASE_MS = 200

# S3 AWS
AWS_S3_REGION_NAME = 'ap-south-1'
AWS_STORAGE_BUCKET_NAME = 'shapreport'
AWS_S3_SIGNATURE_VERSION = 's3v4m'  # For boto3
BUCKET_NAME = "graph-data-and-enriched-features"

# Security Settings
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# API Rate Limiting
THROTTLE_ANON = '100/hour'
THROTTLE_USER = '1000/hour'

# Neo4j
NEO4J_URI = 'bolt://localhost:7687'
SYNC_INTERVAL_HOURS = 6
ANALYSIS_INTERVAL_HOURS = 4

# Kafka Settings
KAFKA_BOOTSTRAP = 'kafka:9093'
SCHEMA_REGISTRY_URL = 'http://localhost:8081'
TOPIC_TRANSACTIONS = 'transactions'
TOPIC_TRANSACTIONS_ENRICHED = 'transactions_enriched'
CONSUMER_GROUP = 'fraud-consumers'
KAFKA_SECURITY_PROTOCOL = 'PLAINTEXT'
KAFKA_SASL_MECHANISM = ''
KAFKA_SASL_USERNAME = ''
KAFKA_SASL_PASSWORD = ''

# Cache Configuration (Redis)
CACHE_BACKEND = 'django_redis.cache.RedisCache'
CACHE_LOCATION = 'redis: // 127.0.0.1: 6380/1'

# Database Configuration
DB_ENGINE = 'django.db.backends.mysql'
DB_NAME = 'fraud_detection'
DB_USER = 'mysql'
DB_PASSWORD = 'hello'
DB_HOST = 'localhost'
DB_PORT = 5432
DB_CONN_MAX_AGE = 60

# Django
DJANGO_SETTINGS_MODULE = 'fraud_ingest.settings'
ALLOWED_HOSTS = ['*']
DJANGO_DEBUG_LEVEL = 1
DJANGO_DEBUGGING = True
