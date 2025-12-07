"""
Real-Time Machine Learning Pipeline for Fraud Detection using Pathway.

This script implements a stateful, streaming machine learning (ML) pipeline
using the Pathway framework to classify transactions as fraudulent or
legitimate. It integrates a dynamically updatable model (`StackingModel`) and
handles continuous model saving, hot-swapping via RabbitMQ (RMQ) listeners,
and asynchronous model retraining via a separate process.

Data Flow:
1. Ingest: Reads enriched transaction features from the 'enriched' Kafka topic.
2. Predict: Applies the current `StackingModel` to calculate fraud probability
and confidence.
3. Transform: Cleans the prediction output and labels transactions
('fraud', 'suspected', 'legitimate').
4. Feedback/Metrics: Reads ground truth labels from 'ground-truth' Kafka topic
to continuouslycalculate and stream ML performance metrics (F1, Recall,
Confusion Matrix).
5. Output: Streams predictions and metrics to their respective Kafka topics
('ml_prediction', 'ml_metrics').

Model Management:
- Hot Swap: A RabbitMQ listener thread monitors the 'model-update' queue for
signals to hot-swap to a newer model version.
- Persistence/Versioning: The model is periodically saved to a pickle file
and versioned using Weights & Biases (WandB).
- Asynchronous Retraining: A separate multiprocessing process
(`start_rmq_consumer`) handles the retraining workflow, triggered
by ground truth data.

This pipeline is designed for high-availability and continuous learning in a
production environment.
"""

import pathway as pw
import os
from dotenv import load_dotenv
from ml_engine.models_final import StackingModel
from ml_engine.log_config.log_config import get_logger
import threading
import pika

import multiprocessing
from ml_engine.retraining import start_rmq_consumer
from datetime import datetime, timedelta
import pickle
from apscheduler.schedulers.background import BackgroundScheduler
import wandb
logger = get_logger(__name__)
current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

WANDB_NAME = os.getenv("WANDB_NAME", "Model")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pw-model")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "pw-versioning")
WANDB_KEY = os.getenv("WANDB_KEY")

X_API_KEY = os.getenv("X_API_KEY")
DUMMY_MAIL = os.getenv("DUMMY_MAIL")
pw.set_license_key(os.getenv("PW_LICENSE_KEY"))
BROKER_URL = os.getenv("CELERY_BROKER_URL", "")


class input_schema(pw.Schema):
    transactionId: str
    step: int
    type: int
    amount: float
    logamount: float
    oldbalanceOrg: float
    newbalanceOrig: float
    oldbalanceDest: float
    newbalanceDest: float

    mean_amount: float                   # engineered features start
    stddev_amount: float
    max_amount_seen: float
    min_amount_seen: float
    user_txn_count: int
    txn_count_in_step: int
    total_amount_in_step: float
    sender_out_degree: int
    sender_in_degree: int
    sender_fraud_ratio: float
    pagerank: float
    amount_to_profile_ratio: float
    amount_to_balance_ratio: float
    origMoreSent: float
    destMoreRec: float
    origMoreSentFlag: bool
    destMoreRecFlag: bool

    time: int
    diff: int


class ground_truth_schema(pw.Schema):
    transactionId: str
    step: int
    transaction_type: int
    amount: float
    logamount: float
    oldbalanceOrg: float
    newbalanceOrig: float
    oldbalanceDest: float
    newbalanceDest: float
    groundTruth: int


class AnomalyToClassifier:
    """
    A wrapper class to adapt the `river` (or similar incremental) model
    interface (`learn_one`, `score_one`) into a standard classifier
    interface that returns prediction probabilities and binary predictions.

    Attributes:
        model: The underlying incremental ML model (e.g., HST-SVM).
        threshold: The scoring threshold for binary classification.
    """

    def __init__(self, model, threshold=0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        self.model.learn_one(x)
        return self

    def predict_proba_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)

        return {0: 1 - score, 1: score}

    def predict_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


def saveModel(model: StackingModel):
    """
    Periodically saves the current state of the ML model to disk (pickle)
    and uploads it to Weights & Biases (WandB) for version control.

    Args:
        model: The currently active `StackingModel` instance.
    """
    cwd = os.getcwd()
    print(cwd)
    _model = model.model
    try:
        with open(f"/app/ml_engine/savedModels/ARF.pkl", "wb") as f:
            pickle.dump(_model, f)
        print("Model pickled and saved successfully")
    except Exception as e:
        print(f"Error during pickling of model: {e}")

    wandb.login(key=WANDB_KEY)
    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(
            name=COLLECTION_NAME,
            type="model",
        )
        artifact.add_file(local_path="/app/ml_engine/savedModels/ARF.pkl",
                          name="ARF.pkl")
        run.log_artifact(artifact)


model = StackingModel()

scheduler = BackgroundScheduler()
scheduler.add_job(saveModel, "interval",
                  seconds=1800,
                  args=[model],
                  next_run_time=datetime.now() + timedelta(seconds=1800))
scheduler.start()


def start_rmq_listener():
    """
    Starts a dedicated thread to listen for model hot-swap signals from 
    RabbitMQ.

    Upon receiving a message (which is expected to contain an artifact alias),
    it calls `model.hot_swap()` to switch to the new model version.
    """
    def callback(ch, method, properties, body):
        try:
            alias = ""
            if (isinstance(body, bytes)):
                alias = body.decode()
            elif (isinstance(body, str)):
                alias = body
            else:
                logger.info(
                    f"Message recv: {body} but unknown dtype: {type(body)}. Skipping hot swap.")

            logger.debug(f"alias is: {alias}, body is: {body}")
            logger.info(f"Received message to hot swap. Now hot-swapping.")

            ok = model.hot_swap(alias)
            if (ok):
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                ch.basic_nack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.error(f"Error during callback: {e}")

    try:
        logger.info(f"Trying to connect to rmq.")
        logger.debug(f"Broker URL: {BROKER_URL}")

        conn = pika.BlockingConnection(pika.URLParameters(BROKER_URL))
        channel = conn.channel()
        queueName = "model-update"
        channel.queue_declare(queueName)

        channel.basic_consume(queueName, callback)
        logger.info(f"Started RabbitMQ Listener")
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Error during init of RMQ Listener. {e}")


th = threading.Thread(target=start_rmq_listener, daemon=True)
th.start()

prc = multiprocessing.Process(target=start_rmq_consumer, daemon=True)
prc.start()
rdkafka_settings = {
    "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"
                                        ),
    "group.id": "ml",
    "auto.offset.reset": "earliest",
    "security.protocol": "plaintext",
    "group.instance.id": "ml-engine-0",
    "session.timeout.ms": "300000",
    "enable.auto.commit": "false"
}

rdkafka_settings_feedback = {
    "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"
                                        ),
    "group.id": "ml-feedback",
    "auto.offset.reset": "earliest",
    "security.protocol": "plaintext",
    "group.instance.id": "ml-feedback-0",
    "session.timeout.ms": "300000",
    "enable.auto.commit": "false"
}

t = pw.io.kafka.read(
    rdkafka_settings=rdkafka_settings,
    topic="enriched",
    schema=input_schema,
    format="json",
    name="enriched"
)

t_ground = pw.io.kafka.read(
    rdkafka_settings=rdkafka_settings_feedback,
    topic="ground-truth",
    schema=ground_truth_schema,
    format="json",
    name="ground_truth_source"
)

output = t.with_columns(
    ml_output=pw.apply_with_type(model.inferModel, dict, **t)
)

result = output.with_columns(
    confidence_score=pw.apply(lambda d: pw.Json.as_dict(
        d).get("confidence_score"), pw.this.ml_output),
    fraud_probability=pw.apply(lambda d: pw.Json.as_dict(
        d).get("fraud_probability"), pw.this.ml_output),
    isFraud_raw=pw.apply(lambda d: pw.Json.as_dict(
        d).get("isFraud"), pw.this.ml_output),
    isUncertain_raw=pw.apply(lambda d: pw.Json.as_dict(
        d).get("isUncertain", 0), pw.this.ml_output),
).select(
    transactionId=pw.this.transactionId,
    amount=pw.this.amount,
    confidence_score=pw.this.confidence_score,
    fraud_probability=pw.this.fraud_probability,
    isFraud_raw=pw.this.isFraud_raw,
    isUncertain_raw=pw.this.isUncertain_raw
)

clean = result.with_columns(
    confidence_score=pw.apply_with_type(lambda v: float
                                        (v or 0.0), float,
                                        pw.this.confidence_score),
    fraud_probability=pw.apply_with_type(lambda v: float
                                         (v or 0.0), float,
                                         pw.this.fraud_probability),
    isFraud=pw.apply_with_type(lambda v: int(
        v or 0), int, pw.this.isFraud_raw),
    isUncertain=pw.apply_with_type(lambda v: int(
        v or 0), int, pw.this.isUncertain_raw)
).select(
    transactionId=pw.this.transactionId,
    amount=pw.this.amount,
    confidence_score=pw.this.confidence_score,
    fraud_probability=pw.this.fraud_probability,
    isFraud=pw.this.isFraud,
    isUncertain=pw.this.isUncertain
)

# Add label column
clean = clean.with_columns(
    label=pw.apply_with_type(
        lambda p: (
            "fraud" if p > 0.8 else
            "suspected" if 0.5 < p < 0.8 else
            "legitimate"
        ),
        str,
        pw.this.fraud_probability
    )
)

# Streams
fraud_stream = clean.filter(
    pw.this.isFraud == 1
).select(
    transactionId=pw.this.transactionId,
    isFraud=pw.this.isFraud,
    amount=pw.this.amount,
    confidence_score=pw.this.confidence_score,
    fraud_probability=pw.this.fraud_probability
)

uncertain_stream = clean.filter(
    pw.this.isUncertain == 1
).select(
    transactionId=pw.this.transactionId,
    isFraud=pw.this.isFraud
)


# email_payload = (
#     '{'
#     f'"address": "{DUMMY_MAIL}", '
#     '"subject": "Fraud Detected - {table.transactionId}", '
#     '"message": "A fraud was detected. Details:\\n'
#     'Transaction Id: {table.transactionId}\\n'
#     'Amount: {table.amount}\\n'
#     'Fraud Probability: {table.fraud_probability}\\n'
#     'ML Model Prediction: {table.isFraud}\\n'
#     'Model Confidence: {table.confidence_score}'
#     '}'
# )


email_payload = (
    '{'
    f'"address": "{DUMMY_MAIL}", '
    '"subject": "Fraud Detected", '
    '"message": "A fraud was detected on your account."'
    '}'
)

pw.io.http.write(
    fraud_stream,
    url="http://fraud-ingest-api:8000/send_email/",
    method="POST",
    format="custom",
    request_payload_template=email_payload,
    headers={
        "Content-Type": "application/json",
        "X-API-Key": X_API_KEY
    }  # type: ignore
)


metrics = t_ground.with_columns(
    metrics_output=pw.apply_with_type(model.get_metrics, dict, **t_ground)
)

metrics_final = metrics.select(
    transactionId=pw.this.transactionId,
    F1=pw.this.metrics_output["F1"],
    Recall=pw.this.metrics_output["Recall"],
    ROC=pw.this.metrics_output["ROC"],
    Precision=pw.this.metrics_output["Precision"],
    ConfusionMatrix=pw.this.metrics_output["ConfusionMatrix"]
)

clean = clean.select(
    transactionId=pw.this.transactionId,
    amount=pw.this.amount,
    confidence_score=pw.this.confidence_score,
    fraud_probability=pw.this.fraud_probability,
    isFraud=pw.this.isFraud,
)

pw.io.kafka.write(
    clean,
    rdkafka_settings,
    topic_name="ml_prediction",
    format="json"
)

pw.io.kafka.write(
    metrics_final,
    rdkafka_settings,
    topic_name="ml_metrics",
    format="json"
)

persistence_backend = pw.persistence.Backend.filesystem(
    "/app/persistence/ml_state/")
persistence_config = pw.persistence.Config(
    persistence_backend,
    snapshot_interval_ms=60000
)


llm_reanalysis_payload = (
    '{'
    '"transactionId": "{table.transactionId}", '
    '"isFraud": "{table.isFraud}"'
    '}'
)


pw.io.http.write(
    uncertain_stream,
    url="http://fraud-ingest-api:8000/api/llm_reanalysis/",
    method="POST",
    format="custom",
    request_payload_template=llm_reanalysis_payload,
    headers={
        "Content-Type": "application/json",
        "X-API-Key": X_API_KEY
    }  # type: ignore
)

pw.run(
    monitoring_level=pw.MonitoringLevel.NONE,
    persistence_config=persistence_config
)
