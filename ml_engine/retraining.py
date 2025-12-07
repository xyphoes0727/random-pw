from google.cloud.bigquery_storage import BigQueryReadClient, types
from ml_engine.models_final import StackingModel
import pika
from logging import getLogger
from dotenv import load_dotenv
import pickle
import pandas as pd
import os
import wandb

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '.env')
load_dotenv(dotenv_path=dotenv_path)
logger = getLogger(__name__)

BROKER_URL = os.getenv("CELERY_BROKER_URL", "")

WANDB_NAME = os.getenv("WANDB_NAME", "Model")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pw-model")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "pw-versioning")
WANDB_KEY = os.getenv("WANDB_KEY")

PROJECT_ID = os.getenv("PROJECT_ID", "")
DATASET_ID = os.getenv("DATASET_ID", "")
TABLE_ID = os.getenv("TABLE_ID")


def batch_read_bigquery():
    client = BigQueryReadClient()
    table = f'projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables/{TABLE_ID}'

    requested_session = types.ReadSession()
    requested_session.table = table
    requested_session.data_format = types.DataFormat.AVRO

    requested_session.read_options.selected_fields = [
        "transactionId",
        "feature_timestamp",
        "diff",
        "step",
        "amount",
        "type",
        "oldbalanceOrg",
        "newbalanceOrig",
        "oldbalanceDest",
        "newbalanceDest",
        "isFraud",
        "mean_amount",
        "stddev_amount",
        "max_amount_seen",
        "min_amount_seen",

        "user_txn_count",
        "txn_count_in_step",
        "total_amount_in_step",
        "sender_out_degree",
        "sender_in_degree",
        "sender_fraud_ratio",
        "pagerank",
        "amount_to_profile_ratio",
        "amount_to_balance_ratio",
        "logamount",

        "origMoreSent",
        "destMoreRec",
        "origMoreSentFlag",
        "destMoreRecFlag",
    ]

    parent = f"projects/{PROJECT_ID}"

    session = client.create_read_session(
        parent=parent,
        read_session=requested_session,
        max_stream_count=1,
    )

    reader = client.read_rows(session.streams[0].name)
    rows = reader.rows(session)

    max_rows = 20000
    data = []

    try:
        for idx, row in enumerate(rows):
            if idx >= max_rows:
                break
            data.append(dict(row))
    except EOFError:
        pass

    print(f"Got {len(data)} data points for retraining.")
    return pd.DataFrame(data)


def retrain() -> bool:
    stacking_model = StackingModel()

    try:
        df = batch_read_bigquery()
    except Exception as e:
        print(f"Exception during BigQuery read: {e}")
        return False

    for idx, row in df.iterrows():
        try:
            ground_truth = int(row["isFraud"])
        except Exception:
            print("ERROR: isFraud missing or invalid")
            continue

        row_dict = row.to_dict()

        del row_dict["isFraud"]
        row_dict["transaction_type"] = row_dict.pop("type")

        row_dict["time"] = row_dict.pop("feature_timestamp")

        metrics_snapshot = stacking_model.get_metrics(
            **row_dict,
            groundTruth=ground_truth
        )

        if ((idx + 1) % 20000 == 0):
            print(f"Processed {idx + 1:,} samples")
            print(metrics_snapshot)

    try:
        saveModel(stacking_model)
    except Exception as e:
        print(f"Error saving model: {e}")
        return False

    return True


def start_rmq_consumer():
    try:
        connection = pika.BlockingConnection(pika.URLParameters(BROKER_URL))
        channel = connection.channel()

        trigger_queue = "trigger-retrain"
        channel.queue_declare(queue=trigger_queue, arguments={
            "x-max-length": 1,
            "x-overflow": "reject-publish"
        })

        update_queue = "model-update"
        channel.queue_declare(queue=update_queue)

        print(f"Retraining Service Started. Listening on '{trigger_queue}'...")

        def callback(ch, method, properties, body):
            print("Starting model retraining...")

            try:
                ok = retrain()
                if not ok:
                    print("Retrainer failed")
                    ch.basic_nack(
                        delivery_tag=method.delivery_tag, requeue=True)

                new_alias = "retrained"
                channel.basic_publish(
                    exchange='',
                    routing_key=update_queue,
                    body=new_alias
                )

                print(f"Retraining complete. Alias: {new_alias}")
                ch.basic_ack(delivery_tag=method.delivery_tag)

            except Exception as e:
                print(f"Retraining failed: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag)

        channel.basic_consume(
            queue=trigger_queue,
            on_message_callback=callback
        )
        channel.start_consuming()

    except Exception as e:
        print(f"RMQ Connection Error: {e}")


def saveModel(model: StackingModel):
    cwd = os.getcwd()
    print("Saving model. CWD:", cwd)

    _model = model.model

    try:
        with open(f"/app/ml_engine/savedModels/ARF.pkl", "wb") as f:
            pickle.dump(_model, f)
        print("Model saved successfully")
    except Exception as e:
        print(f"Error pickling model: {e}")

    wandb.login(key=WANDB_KEY)

    with wandb.init(project=WANDB_PROJECT) as run:
        artifact = wandb.Artifact(
            name="retrained-model",
            type="model"
        )
        artifact.add_file(
            local_path="/app/ml_engine/savedModels/ARF.pkl",
            name="ARF.pkl"
        )
        run.log_artifact(artifact, aliases=["retrained", "arf"])
