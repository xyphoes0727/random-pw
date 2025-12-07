from pathlib import Path

AVRO_DIR = Path(__file__).resolve().parent / "avro"


def _read_schema_str(name: str) -> str:
    return (AVRO_DIR / name).read_text(encoding="utf-8")

# Confluent AvroSerializer/AvroDeserializer expect schema strings


KEY_SCHEMA = _read_schema_str("transactions-key.avsc")
VALUE_SCHEMA = _read_schema_str("transactions-value.avsc")

VALUE_ENRICHED_SCHEMA = _read_schema_str("transactions-enriched-value.avsc")

__all__ = ["KEY_SCHEMA", "VALUE_SCHEMA", "VALUE_ENRICHED_SCHEMA"]