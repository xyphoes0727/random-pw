from logging.handlers import TimedRotatingFileHandler
import logging
from loguru import logger
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

USE_TZ = True
TIME_ZONE = "Asia/Kolkata"

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-not-secret")
DEBUG = os.getenv("DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]


INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # our apps
    "producers",
    "storage",
    "api",
    "telemetry_provider",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "channels",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ORIGIN_ALLOW_ALL = False
CORS_ORIGIN_WHITELIST = (
    'http://localhost:8081',
    'http://localhost:8080',
    'http://localhost:3000',
    'http://rabbitmq_consumer:8000'

)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


ASGI_APPLICATION = 'fraud_ingest.asgi.application'


DATABASES = {
    "default": {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('MYSQL_DATABASE'),
        'USER': os.environ.get('MYSQL_USER'),
        'PASSWORD': os.environ.get('MYSQL_PASSWORD'),
        'HOST': os.environ.get('MYSQL_HOST'),
    }
}

AUTH_USER_MODEL = 'api.User'
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

STATIC_URL = "static/"
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9095")
SCHEMA_REGISTRY_URL = os.getenv("SCHEMA_REGISTRY_URL", "http://localhost:8081")

# currently, by default no authentication is done (plaintext);
# will add it when needed


KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
KAFKA_SASL_MECHANISM = os.getenv("KAFKA_SASL_MECHANISM", "")
KAFKA_SASL_USERNAME = os.getenv("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD = os.getenv("KAFKA_SASL_PASSWORD", "")

# we can add more topics here by defining more strings or in a same string
# using dictionary
TOPIC_TRANSACTIONS = os.getenv("TOPIC_TRANSACTIONS", "transactions")
TOPIC_TRANSACTIONS_ENRICHED = os.getenv(
    "TOPIC_TRANSACTIONS_ENRICHED", "transactions_enriched")
# each consumer has a group id
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "fraud-consumers")
# dlt add idhar krenge
TOPICS_TRANSCATIONS_DLT = os.getenv(
    "TOPIC_TRANSACTIONS_DLT", "transactions_DLT")
CONSUMER_MAX_RETRIES = int(os.getenv("CONSUMER_MAX_RETRIES", "5"))
CONSUMER_BACKOFF_BASE_MS = int(os.getenv("CONSUMER_BACKOFF_BASE_MS", "500"))


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger.remove()

# Console log
logger.add(
    sink=lambda msg: print(msg, end=""),
    colorize=True,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level}</level> | <cyan>{message}</cyan>"
    ),
)

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },

    "handlers": {
        # Rotating file handler (daily rotation, retain 7 days, gzip old logs)
        "app_file": {
            "level": "INFO",
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "when": "midnight",
            "backupCount": 3,
            "encoding": "utf-8",
            "utc": False,
            "formatter": "standard",
        },

        # to print in console also
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "standard",
        },
    },

    "root": {
        "handlers": ["console", "app_file"],
        "level": "INFO",
    },

    "loggers": {
        "django": {
            "handlers": ["console", "app_file"],
            "level": "INFO",
        },
    },
}


# # File log (rotates daily, keeps 7 days)
# logger.add(
#     LOG_DIR / "app.log",
#     rotation="1 day",
#     retention="7 days",
#     compression="zip",
#     enqueue=True,
#     level="INFO",
#     format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
# )

ROOT_URLCONF = 'fraud_ingest.urls'

CELERY_BROKER_URL = "amqp://my_user:my_password@rabbitmq:5672/myvhost"
CELERY_RESULT_BACKEND = "rpc://"  # optional but recommended

INTERNAL_API_KEY = "super-secret-ml-key"
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_USE_TLS = True
EMAIL_PORT = 587
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')


CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://redis:6379/0",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379, 1)],  # use DB 1
        },
    },
}
    

# Optional: This is to ensure Django sessions are stored in Redis
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'
