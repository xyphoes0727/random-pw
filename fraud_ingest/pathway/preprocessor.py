import os
import math
import sys
import time
from dotenv import load_dotenv
from functools import lru_cache
from typing import Any, Dict
from loguru import logger

import pathway as pw
from fraud_ingest.pathway.schemas import Transaction
from fraud_ingest.pathway.redis import (
    get_user_profile,
    get_step_velocity,
    update_redis_state
)
from fraud_ingest.pathway.neo4j.streaming_connector import (
    init_neo4j_connector,
    fetch_graph_features as raw_fetch_features,
)


def map_kyc(tier):
    try:
        t = int(tier)
    except Exception:
        return 0.1
    mapping = {0: 0.1, 1: 0.3, 2: 0.7, 3: 0.9, 4: 1.0}
    return mapping.get(t, 0.1)


def compute_D(fraud_count, txn_count):
    alpha = 9.8
    beta = 0.2
    if txn_count is None or txn_count <= 0:
        return alpha / (alpha + beta)
    n_total = float(txn_count)
    n_success = float(max(0.0, n_total - float(fraud_count or 0.0)))
    return (alpha + n_success) / (alpha + beta + n_total)


def synth_trust(s, k, d):
    w_d = 0.5
    w_k = 0.3
    w_s = 0.2
    s = max(1e-6, float(s or 0.0))
    k = max(1e-6, float(k or 0.0))
    d = max(1e-6, float(d or 0.0))
    trust = 100.0 * ((s ** w_s) * (k ** w_k) * (d ** w_d))
    return float(max(0.0, min(100.0, trust)))


def safe_log(x: float) -> float:
    return math.log(1 + x)


def init_environment():
    start = time.time()
    logger.info("Initializing environment variables and Pathway license.")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(current_dir, '..', '..', '.env')
    load_dotenv(dotenv_path=dotenv_path)
    pw.set_license_key(os.getenv("PW_LICENSE_KEY"))
    pw.set_monitoring_config(server_endpoint="http://otel-collector:4317")
    logger.info(f"Environment initialized in {time.time() - start:.3f}s")


@lru_cache(maxsize=2048)
def cached_graph_features(user_id: str):
    try:
        return raw_fetch_features(user_id)
    except Exception:
        return {'out_degree': 0, 'in_degree': 0,
                'fraud_ratio': 0.0, 'pagerank': 0.0}


def get_graph_features(user_id: str):
    return cached_graph_features(user_id)


def fetch_redis_profile_udf(user_id: str) -> Dict[str, Any]:
    return get_user_profile(user_id)


def fetch_redis_velocity_udf(user_id: str, step: int) -> Dict[str, Any]:
    return get_step_velocity(user_id, step)


def push_to_redis_udf(user_id: str, step: int, amount: float,
                      is_fraud: int) -> int:
    return update_redis_state(user_id, step, amount, is_fraud)


def load_kafka_transactions() -> pw.Table:
    logger.info("Loading transactions from Kafka.")
    instance_id = os.getenv("INSTANCE_ID", "0")
    rdkafka_settings = {
        "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                            "kafka:9093"),
        "group.id": "fraud-detection-pipeline-redis",
        "auto.offset.reset": "earliest",
        "security.protocol": "plaintext",
        "group.instance.id": f"fraud-worker-redis-{instance_id}",
    }
    return pw.io.kafka.read(
        rdkafka_settings=rdkafka_settings,
        topic="transactions-raw",
        schema=Transaction,
        format="json",
        autocommit_duration_ms=5000,
    )


def build_graph_edges(transactions: pw.Table) -> pw.Table:
    return transactions.filter(
        pw.this.nameOrig.is_not_none() & pw.this.nameDest.is_not_none()
    ).select(
        from_user=pw.this.nameOrig,
        to_user=pw.this.nameDest,
        amount=pw.this.amount,
        is_fraud=pw.this.isFraud,
        step=pw.this.step,
    )


def enrich_transactions_redis(transactions: pw.Table) -> pw.Table:
    logger.info("Starting enrichment pipeline (Redis-backed)...")

    enriched = transactions.select(
        *pw.this,
        profile_data=pw.apply_with_type(
            fetch_redis_profile_udf, pw.Json, pw.this.nameOrig),
        velocity_data=pw.apply_with_type(
            fetch_redis_velocity_udf, pw.Json, pw.this.nameOrig, pw.this.step),
        neo4j_features=pw.apply_with_type(
            get_graph_features, pw.Json, pw.this.nameOrig),
    )

    enriched = enriched.select(
        *pw.this,
        hist_count=pw.apply_with_type(
            lambda x: x["count"].as_int(), int, pw.this.profile_data),
        hist_sum=pw.apply_with_type(
            lambda x: x["sum"].as_float(), float, pw.this.profile_data),
        hist_sum_sq=pw.apply_with_type(
            lambda x: x["sum_sq"].as_float(), float, pw.this.profile_data),
        hist_max=pw.apply_with_type(
            lambda x: x["max"].as_float(), float, pw.this.profile_data),
        hist_min=pw.apply_with_type(
            lambda x: x["min"].as_float(), float, pw.this.profile_data),
        hist_fraud_count=pw.apply_with_type(
            lambda x: x["fraud_count"].as_int(), int, pw.this.profile_data),

        step_hist_count=pw.apply_with_type(
            lambda x: x["count"].as_int(), int, pw.this.velocity_data),
        step_hist_sum=pw.apply_with_type(
            lambda x: x["sum"].as_float(), float, pw.this.velocity_data),

        sender_out_degree=pw.apply_with_type(
            lambda x: x["out_degree"].as_int(), int, pw.this.neo4j_features),
        sender_in_degree=pw.apply_with_type(
            lambda x: x["in_degree"].as_int(), int, pw.this.neo4j_features),
        sender_fraud_ratio=pw.apply_with_type(
            lambda x: x["fraud_ratio"].as_float(), float,
            pw.this.neo4j_features),
        pagerank=pw.apply_with_type(
            lambda x: x["pagerank"].as_float(), float, pw.this.neo4j_features),
    )

    enriched = enriched.select(
        *pw.this,
        new_count=pw.this.hist_count + 1,
        new_sum=pw.this.hist_sum + pw.this.amount,
        new_sum_sq=pw.this.hist_sum_sq + (pw.this.amount * pw.this.amount),

        new_fraud_count=pw.this.hist_fraud_count + pw.this.isFraud,

        txn_count_in_step=pw.this.step_hist_count + 1,
        total_amount_in_step=pw.this.step_hist_sum + pw.this.amount,

        max_amount_seen=pw.apply_with_type(
            lambda h, c: max(h, c), float, pw.this.hist_max, pw.this.amount),
        min_amount_seen=pw.apply_with_type(
            lambda h, c: min(h, c) if h > 0 or h < 0 else c,
            float, pw.this.hist_min, pw.this.amount),
    )

    enriched = enriched.select(
        *pw.this,
        mean_amount=pw.this.new_sum / pw.this.new_count,
        variance=(pw.this.new_sum_sq / pw.this.new_count) -
                 ((pw.this.new_sum / pw.this.new_count) ** 2),
        user_txn_count=pw.this.new_count,
        user_fraud_count=pw.this.new_fraud_count,
    ).select(
        *pw.this,
        stddev_amount=pw.apply_with_type(
            lambda v: math.sqrt(max(0.0, v)), float, pw.this.variance),
    ).select(
        *pw.this,
        cv=pw.apply_with_type(
            lambda std, mean: (std / (mean + 1e-9)) if mean > 0 else float(
                'inf'),
            float, pw.this.stddev_amount, pw.this.mean_amount
        )
    )

    enriched = enriched.select(
        *pw.this,
        stability_S=pw.apply_with_type(
            lambda cv: 1.0/(1.0 + cv) if (cv is not None and cv != float(
                'inf')) else 0.0,
            float, pw.this.cv
        ),
        kyc_K=pw.apply_with_type(map_kyc, float, pw.this.kyc_tier),
        default_D=pw.apply_with_type(
            compute_D, float, pw.this.user_fraud_count, pw.this.user_txn_count
        )
    )

    enriched = enriched.select(
        *pw.this,
        trust_score=pw.apply_with_type(
            lambda s, k, d: int(synth_trust(s, k, d)), int,
            pw.this.stability_S, pw.this.kyc_K, pw.this.default_D
        ),
        amount_to_profile_ratio=pw.this.amount / (pw.this.mean_amount + 1),
        amount_to_balance_ratio=pw.this.amount / (pw.this.oldbalanceOrg + 1),
        logamount=pw.apply_with_type(safe_log, float, pw.this.amount),
        transaction_type=pw.this.type
    )

    enriched = enriched.select(
        *pw.this,
        _redis_update=pw.apply_with_type(
            push_to_redis_udf, int,
            pw.this.nameOrig, pw.this.step, pw.this.amount, pw.this.isFraud
        )
    )

    final = enriched.without(
        pw.this.profile_data, pw.this.velocity_data, pw.this.neo4j_features,
        pw.this.hist_count, pw.this.hist_sum, pw.this.hist_sum_sq,
        pw.this.hist_max, pw.this.hist_min, pw.this.hist_fraud_count,
        pw.this.new_count, pw.this.new_sum, pw.this.new_sum_sq,
        pw.this.new_fraud_count,
        pw.this.step_hist_count, pw.this.step_hist_sum, pw.this.variance,
        pw.this.cv, pw.this.stability_S, pw.this.kyc_K, pw.this.default_D,
        pw.this.user_fraud_count, pw.this.type
    )

    return final


def rule_based_features(enriched: pw.Table) -> pw.Table:
    enriched_rules = enriched.select(
        *pw.this,
        origMoreSent=pw.this.newbalanceOrig + pw.this.amount -
        pw.this.oldbalanceOrg,
        destMoreRec=pw.this.oldbalanceDest + pw.this.amount -
        pw.this.newbalanceDest,
    )
    return enriched_rules.select(
        *pw.this,
        origMoreSentFlag=pw.apply_with_type(
            lambda x: 1 if x > 0 else 0, int, pw.this.origMoreSent),
        destMoreRecFlag=pw.apply_with_type(
            lambda x: 1 if x > 0 else 0, int, pw.this.destMoreRec),
    )


def write_to_deltalake(
        enriched_table: pw.Table, edges: pw.Table, INSTANCE_ID: int):
    logger.info("Configuring Delta Lake output.")
    BUCKET_NAME = os.getenv("BUCKET_NAME", "")
    REGION = os.getenv("REGION", "us-east-1")
    AWS_S3_ACCESS_KEY = os.getenv("AWS_S3_ACCESS_KEY", "")
    AWS_S3_SECRET_ACCESS_KEY = os.getenv("AWS_S3_SECRET_ACCESS_KEY", "")

    base_enriched = os.getenv("ENRICHED_TABLE_PATH")
    base_graph = os.getenv("USER_USER_GRAPH_PATH")

    ENRICHED_TABLE_PATH = f"{base_enriched}_{INSTANCE_ID}"
    USER_USER_GRAPH_PATH = f"{base_graph}_{INSTANCE_ID}"

    credentials = pw.io.s3.AwsS3Settings(
        access_key=AWS_S3_ACCESS_KEY,
        secret_access_key=AWS_S3_SECRET_ACCESS_KEY,
        bucket_name=BUCKET_NAME,
        region=REGION,
    )

    enriched_with_partition = enriched_table.select(
        *pw.this, instance_id=INSTANCE_ID
    ).without(pw.this._redis_update)

    edges_with_partition = edges.select(
        *pw.this, instance_id=INSTANCE_ID
    )

    pw.io.deltalake.write(
        enriched_with_partition,
        ENRICHED_TABLE_PATH,
        s3_connection_settings=credentials,
    )

    pw.io.csv.write(
        enriched_with_partition,
        f"{INSTANCE_ID}-enriched.csv"
    )

    pw.io.deltalake.write(
        edges_with_partition,
        USER_USER_GRAPH_PATH,
        s3_connection_settings=credentials,
    )
    logger.info("Delta Lake writers configured.")


def write_to_kafka(enriched: pw.Table):
    logger.info("Configuring Kafka output.")
    rdkafka_settings = {
        "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS",
                                            "kafka:9093"),
        "security.protocol": "plaintext",
    }

    out = enriched.without(pw.this._redis_update, pw.this.kyc_tier)
    pw.io.kafka.write(
        out, rdkafka_settings, topic_name="enriched", format="json"
    )


def build_pipeline(use_kafka=True):
    pipeline_start = time.time()
    init_environment()
    init_neo4j_connector()

    if use_kafka:
        transactions = load_kafka_transactions()
    else:
        logger.warning("Using static data (NOT IMPLEMENTED IN THIS SNIPPET)")
        sys.exit(1)

    INSTANCE_ID = int(os.getenv("INSTANCE_ID", "0"))

    edges = build_graph_edges(transactions)

    enriched = enrich_transactions_redis(transactions)

    enriched_rules = rule_based_features(enriched)

    write_to_kafka(enriched_rules)
    write_to_deltalake(enriched_rules, edges, INSTANCE_ID)

    logger.info(
        f"Pipeline built in {time.time() - pipeline_start:.3f}s. Starting runtime...")

    pw.run(monitoring_level=pw.MonitoringLevel.NONE)


if __name__ == "__main__":
    use_kafka = "--static" not in sys.argv
    build_pipeline(use_kafka=use_kafka)
