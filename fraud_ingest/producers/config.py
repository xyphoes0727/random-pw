from django.conf import settings


PRODUCER_CONFIG = {
    "bootstrap.servers": settings.KAFKA_BOOTSTRAP,
}
if settings.KAFKA_SECURITY_PROTOCOL != "PLAINTEXT":
    PRODUCER_CONFIG.update(
        {
            "security.protocol": settings.KAFKA_SECURITY_PROTOCOL,
            "sasl.mechanism": settings.KAFKA_SASL_MECHANISM,
            "sasl.username": settings.KAFKA_SASL_USERNAME,
            "sasl.password": settings.KAFKA_SASL_PASSWORD,
        }
    )
