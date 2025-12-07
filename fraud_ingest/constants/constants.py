# DeltaLake
TOPIC_TRANSACTIONS = 'transactions'
KAFKA_DLT_TOPIC = 'transactions.DLT'
KAFKA_SOURCE_TOPIC = 'transactions'
TOPIC_TRANSACTIONS_DLT = 'transactions_DLT'

# Consumer/Producer tuning
CONSUMER_MAX_RETRIES = 3
CONSUMER_BACKOFF_BASE_MS = 200

# S3 AWS RCA
RCA_REGION_NAME = 'ap-south-1'
RCA_BUCKET_NAME = 'shapreport'

# S3 AWS GRAPH
DELTALAKE_BUCKET_NAME = "graph-data-and-enriched-features"
DELTALAKE_REGION = "ap-south-1"

# # Security Settings
# SECURE_SSL_REDIRECT = False
# SESSION_COOKIE_SECURE = False
# CSRF_COOKIE_SECURE = False

# # API Rate Limiting
# THROTTLE_ANON = '100/hour'
# THROTTLE_USER = '1000/hour'

# Neo4j
NEO4J_URI = 'bolt://neo4j:7687'
NEO4J_USER = 'neo4j'
NEO4J_PASSWORD = 'frauddetection'
NEO_AWS_REGION = "ap-south-1"
SYNC_INTERVAL_HOURS = 6
ANALYSIS_INTERVAL_HOURS = 4

# Kafka Settings
TOPIC_TRANSACTIONS_ENRICHED = 'transactions_enriched'
TOPIC_TRANSACTIONS = 'transactions'
KAFKA_FEEDBACK_TOPIC = 'ground-truth'
CONSUMER_GROUP = 'fraud-consumers'

KAFKA_BROKER = 'kafka:9093'
KAFKA_BOOTSTRAP = 'kafka:9093'
SCHEMA_REGISTRY_URL = 'http://localhost:8081'

KAFKA_SECURITY_PROTOCOL = 'PLAINTEXT'
KAFKA_SASL_MECHANISM = ''
KAFKA_SASL_USERNAME = ''
KAFKA_SASL_PASSWORD = ''

# Cache Configuration (Redis)
CACHE_BACKEND = 'django_redis.cache.RedisCache'
CACHE_LOCATION = 'redis: // 127.0.0.1: 6379/1'

# Django
DJANGO_SETTINGS_MODULE = 'fraud_ingest.settings'
ALLOWED_HOSTS = ['*']
