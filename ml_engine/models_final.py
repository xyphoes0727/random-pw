from tqdm import tqdm
import random
from pinecone.grpc import PineconeGRPC, GRPCClientConfig
from river import metrics
import wandb
from river.compose import pipeline
import numpy as np
from logging import getLogger
from dotenv import load_dotenv
from collections import deque, defaultdict
import pickle
import os
import threading
import sys

pc = PineconeGRPC(api_key="pclocal")

index = pc.Index(host="dense-index:5081",
                 grpc_config=GRPCClientConfig(secure=False))

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '.env')
load_dotenv(dotenv_path=dotenv_path)
logger = getLogger(__name__)


WANDB_NAME = os.getenv("WANDB_NAME", "Model")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pw-model")
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "pw-versioning")
WANDB_KEY = os.getenv("WANDB_KEY")


VECTOR_FEATURES = [
    "type", "oldbalanceOrg", "newbalanceOrig",
            "oldbalanceDest", "newbalanceDest",
            "mean_amount", "stddev_amount", "max_amount_seen", "min_amount_seen",
            "user_txn_count", "txn_count_in_step", "total_amount_in_step",
            "sender_out_degree", "sender_in_degree", "sender_fraud_ratio", "pagerank",
            "amount_to_profile_ratio", "amount_to_balance_ratio",
            "logamount", "origMoreSent", "destMoreRec",
            "origMoreSentFlag", "destMoreRecFlag"
]


class AnomalyToClassifier:
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

        # prob = 1 / (1 + np.exp(-score))
        return {0: 1 - score, 1: score}

    def predict_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


def loadModel(alias="") -> pipeline.Pipeline:
    if (alias == ""):
        alias = "latest"

    if (alias == "latest"):
        model_artifact_name = f"{WANDB_NAME}/{WANDB_PROJECT}/{COLLECTION_NAME}:{alias}"
    else:
        model_artifact_name = f"{WANDB_NAME}/{WANDB_PROJECT}/retrained-model:{alias}"

    wandb.login(key=WANDB_KEY)
    with wandb.init(project=WANDB_PROJECT) as run:
        registry_model = run.use_artifact(artifact_or_name=model_artifact_name)
        local_artifact_path = registry_model.download()
        local_model_path = f"{local_artifact_path}/ARF.pkl"

    with open(local_model_path, "rb") as f:
        model = None
        print(__name__)

        try:
            model = CustomUnpickler(f).load()
            return model
        except Exception as e:
            print(f"Model: error on pickle: {e}")


class CustomUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        logger.debug(f"Unpickling in load model: {module}.{name}")

        if module == "ml_engine.train_model":
            import ml_engine.train_model as real_mod
            return getattr(real_mod, name)

        if module == "ml_engine.models_final":
            import ml_engine.models_final as real_mod
            return getattr(real_mod, name)

        if module == "ml_engine.retraining":
            import ml_engine.retraining as real_mod
            return getattr(real_mod, name)

        if module == "__main__":
            return AnomalyToClassifier

        return super().find_class(module, name)


class DynamicThresholdWrapper:
    def __init__(
        self,
        window_size=10000,
        percentile=50,  # MODIFIED: Lowered from 70 to 50
        ema_alpha=0.1,  # MODIFIED: Increased from 0.06 for faster reaction
        grace_period=250,
        min_threshold=0.15,  # MODIFIED: Lowered from 0.25
        max_threshold=0.92,
        fraud_weight=0.70,  # MODIFIED: Decreased from 0.95
        nonfraud_weight=0.30,  # MODIFIED: Increased from 0.05
        percentile_update_interval=50
    ):
        """
        Initialize the wrapper with parameters tuned for HIGHER RECALL.

        - percentile: Lowered to calculate a lower score threshold.
        - min_threshold: Lowered to allow the threshold to drop further.
        - fraud_weight/nonfraud_weight: Adjusted to give more weight \
            to the non-fraud score distribution, pulling the threshold down.
        - ema_alpha: Increased slightly to react faster to new percentile data.
        """
        self.window_size = window_size
        self.percentile = percentile
        self.ema_alpha = ema_alpha
        self.grace_period = grace_period
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold

        self.fraud_weight = fraud_weight
        self.nonfraud_weight = nonfraud_weight

        self.recent_scores = deque(maxlen=window_size)
        self.fraud_scores = deque(maxlen=window_size)
        self.nonfraud_scores = deque(maxlen=window_size)

        self.samples_seen = 0
        self.ema_threshold = 0.5  # Initial threshold
        self.last_threshold = 0.5

        self.percentile_update_interval = percentile_update_interval
        self.last_percentile_update = 0

        self.cached_percentile_threshold = 0.5
        self.y_probas = deque(maxlen=window_size)
        self.y_labels = deque(maxlen=window_size)
        self.save_path = './last_10k_data.pkl'
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

    def update(self, y_proba_1, y_true=None):
        self.samples_seen += 1

        if y_true is not None:
            self.recent_scores.append(y_proba_1)
            if y_true:
                self.fraud_scores.append(y_proba_1)
            else:
                self.nonfraud_scores.append(y_proba_1)
            self.y_probas.append(y_proba_1)
            self.y_labels.append(y_true)

        if self.samples_seen % 10000 == 0:
            with open(self.save_path, 'wb') as f:
                pickle.dump({'y_probas': list(self.y_probas),
                            'y_true': list(self.y_labels)}, f)

        # Update threshold every percentile_update_interval samples
        if self.samples_seen - self.last_percentile_update >= self.percentile_update_interval:
            self.cached_percentile_threshold = self._compute_weighted_percentile()
            self.last_percentile_update = self.samples_seen

        # Smooth with EMA
        if self.samples_seen < self.grace_period:
            self.ema_threshold = 0.5  # default warmup threshold
        else:
            self.ema_threshold = (
                self.ema_alpha * self.cached_percentile_threshold
                + (1 - self.ema_alpha) * self.ema_threshold
            )
            self.ema_threshold = np.clip(
                self.ema_threshold, self.min_threshold, self.max_threshold
            )
        return self.ema_threshold

    # Compute weighted percentile candidates
    def _compute_weighted_percentile(self):
        weighted_thresholds = []
        total_weight = 0

        if self.fraud_scores:
            fraud_arr = np.array(self.fraud_scores)
            fraud_p = np.percentile(fraud_arr, self.percentile)
            weighted_thresholds.append(fraud_p * self.fraud_weight)
            total_weight += self.fraud_weight

        if self.nonfraud_scores:
            nonfraud_arr = np.array(self.nonfraud_scores)
            nonfraud_p = np.percentile(nonfraud_arr, self.percentile)
            weighted_thresholds.append(nonfraud_p * self.nonfraud_weight)
            total_weight += self.nonfraud_weight

        if not weighted_thresholds:
            # Fallback if we have no fraud or non-fraud scores yet
            if self.recent_scores:
                return np.percentile(np.array(self.recent_scores), self.percentile)
            return 0.5  # Default starting percentile

        return sum(weighted_thresholds) / total_weight

    def get_threshold(self):
        return self.ema_threshold

    def is_anomaly(self, anomaly_score: float, is_fraud: int) -> bool:
        # If is_fraud is None, treat as non-fraud for score collection.
        label = 0 if is_fraud is None else int(is_fraud)
        y_proba = AnomalyToClassifier.predict_proba_one(self, anomaly_score)
        self.update(anomaly_score, label)

        if abs(self.ema_threshold - self.last_threshold) > 0.05:
            self.last_threshold = self.ema_threshold

        return anomaly_score >= self.ema_threshold  # type: ignore


class StreamingLabelEncoder:
    def __init__(self):
        self.mapping = {}
        self.counter = 0

    def encode(self, value):
        if value not in self.mapping:
            self.mapping[value] = self.counter
            self.counter += 1
        return float(self.mapping[value])


label_encoders = defaultdict(StreamingLabelEncoder)


def to_feature_dict(row, feature_cols):
    d = {}
    for c in feature_cols:
        val = row[c]

        # Case 1: numeric
        try:
            v = float(val)
            if np.isnan(v) or np.isinf(v):
                v = 0.0
            d[c] = v
            continue
        except Exception:
            pass

        # Case 2: categorical
        try:
            d[c] = label_encoders[c].encode(str(val))
        except Exception:
            pass

    return d


FEATURE_COLS = [
    "type", "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
    "mean_amount", "stddev_amount", "max_amount_seen", "min_amount_seen",
    "user_txn_count", "txn_count_in_step", "total_amount_in_step",
    "sender_out_degree", "sender_in_degree", "sender_fraud_ratio", "pagerank",
    "amount_to_profile_ratio", "amount_to_balance_ratio",
    "logamount", "origMoreSent", "destMoreRec", "origMoreSentFlag", "destMoreRecFlag"
]


class StackingModel():
    def __init__(self):
        self.model = loadModel()
        self.dynamic_threshold = DynamicThresholdWrapper()
        self.f1_metric = metrics.F1()
        self.recall_metric = metrics.Recall()
        self.auc = metrics.ROCAUC()
        self.precision_metric = metrics.Precision()
        self.tp = 0
        self.fp = 0
        self.tn = 0
        self.fn = 0
        self.precision_metric_value = 0.0

        self.write_lock = threading.Lock()

    def fetch_from_wandb(self, alias: str = ""):
        return loadModel(alias)

    def hot_swap(self, alias: str) -> bool:
        print(f"Attempting to switch to new model with alias: {alias}")
        try:
            new_model = self.fetch_from_wandb(alias=alias)
            with self.write_lock:
                self.model = new_model

            logger.info(f"Model swapping successful.")
            return True

        except Exception as e:
            logger.error(f"Error during fetching or RWMutex: {e}")
            return False

    def inferModel(
        self,
        transactionId,
        step,
        type,
        amount,
        logamount,
        oldbalanceOrg,
        newbalanceOrig,
        oldbalanceDest,
        newbalanceDest,

        mean_amount,
        stddev_amount,
        max_amount_seen,
        min_amount_seen,
        user_txn_count,
        txn_count_in_step,
        total_amount_in_step,
        sender_out_degree,
        sender_in_degree,
        sender_fraud_ratio,
        pagerank,
        amount_to_profile_ratio,
        amount_to_balance_ratio,
        origMoreSent,
        destMoreRec,
        origMoreSentFlag,
        destMoreRecFlag,

        time=0,
        diff=0,
    ):

        local_ref = self.model

        data = {
            "step": step,
            "amount": amount,
            "type": type,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest,
            "mean_amount": mean_amount,
            "stddev_amount": stddev_amount,
            "max_amount_seen": max_amount_seen,
            "min_amount_seen": min_amount_seen,
            "user_txn_count": user_txn_count,
            "txn_count_in_step": txn_count_in_step,
            "total_amount_in_step": total_amount_in_step,
            "sender_out_degree": sender_out_degree,
            "sender_in_degree": sender_in_degree,
            "sender_fraud_ratio": sender_fraud_ratio,
            "pagerank": pagerank,
            "amount_to_profile_ratio": amount_to_profile_ratio,
            "amount_to_balance_ratio": amount_to_balance_ratio,
            "logamount": logamount,
            "origMoreSent": origMoreSent,
            "destMoreRec": destMoreRec,
            "origMoreSentFlag": origMoreSentFlag,
            "destMoreRecFlag": destMoreRecFlag,
            # "time": time,
            # "diff": diff,
        }

        feature = [data.get(x, 0) for x in VECTOR_FEATURES]

        # print(len(feature))
        retrieved_vector = index.query(
            vector=feature,
            top_k=1,
            include_values=False,
            include_metadata=False
        )

        similarity_score = retrieved_vector['matches'][0]['score'] if retrieved_vector['matches'] else 0.0

        similarity_score = 0.
        y_hat = 0
        score = 0.0
        weight = 0.
        if hasattr(self.model, "predict_proba_one"):
            y_proba = local_ref.predict_proba_one(data)

            adaptive_thresh = self.dynamic_threshold.get_threshold()

            if isinstance(y_proba, dict):
                score = y_proba.get(1) or y_proba.get(True) or 0.0
                score = (score * (1 - weight)) + (similarity_score * weight)
                y_hat = int(score >= adaptive_thresh)
            else:
                score = (y_proba * (1 - weight)) + (similarity_score * weight)
                y_hat = int(y_proba >= adaptive_thresh)

        conf_score = 0.
        if (score > adaptive_thresh):
            conf_score = (score-adaptive_thresh)/(1-adaptive_thresh)
        else:
            conf_score = (adaptive_thresh-score)/score

        isUncertain = 0
        if (score < (adaptive_thresh + 0.05) and (score > adaptive_thresh - 0.05)):
            isUncertain = 1

        return {"confidenfce_score": conf_score,
                "fraud_probability": score,
                "isFraud": y_hat,
                "isUncertain": isUncertain, }

    def get_metrics(
        self,
        transactionId,
        step,
        transaction_type,
        amount,
        logamount,
        oldbalanceOrg,
        newbalanceOrig,
        oldbalanceDest,
        newbalanceDest,
        groundTruth,
        mean_amount,
        stddev_amount,
        max_amount_seen,
        min_amount_seen,
        user_txn_count,
        txn_count_in_step,
        total_amount_in_step,
        sender_out_degree,
        sender_in_degree,
        sender_fraud_ratio,
        pagerank,
        amount_to_profile_ratio,
        amount_to_balance_ratio,
        origMoreSent,
        destMoreRec,
        origMoreSentFlag,
        destMoreRecFlag,

        time,
        diff,
    ):
        local_ref = self.model

        data = {
            "transactionId": transactionId,
            "step": step,
            "type": transaction_type,
            "amount": amount,
            "logamount": logamount,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest,
            "mean_amount": mean_amount,
            "stddev_amount": stddev_amount,
            "max_amount_seen": max_amount_seen,
            "min_amount_seen": min_amount_seen,
            "user_txn_count": user_txn_count,
            "txn_count_in_step": txn_count_in_step,
            "total_amount_in_step": total_amount_in_step,
            "sender_out_degree": sender_out_degree,
            "sender_in_degree": sender_in_degree,
            "sender_fraud_ratio": sender_fraud_ratio,
            "pagerank": pagerank,
            "amount_to_profile_ratio": amount_to_profile_ratio,
            "amount_to_balance_ratio": amount_to_balance_ratio,
            "origMoreSent": origMoreSent,
            "destMoreRec": destMoreRec,
            "origMoreSentFlag": origMoreSentFlag,
            "destMoreRecFlag": destMoreRecFlag,
            "time": time,
            "diff": diff,
        }

        data_learn = {
            "type": transaction_type,
            "amount": amount,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest,
            "mean_amount": mean_amount,
            "stddev_amount": stddev_amount,
            "max_amount_seen": max_amount_seen,
            "min_amount_seen": min_amount_seen,
            "user_txn_count": user_txn_count,
            "txn_count_in_step": txn_count_in_step,
            "total_amount_in_step": total_amount_in_step,
            "sender_out_degree": sender_out_degree,
            "sender_in_degree": sender_in_degree,
            "sender_fraud_ratio": sender_fraud_ratio,
            "pagerank": pagerank,
            "amount_to_profile_ratio": amount_to_profile_ratio,
            "amount_to_balance_ratio": amount_to_balance_ratio,
            "logamount": logamount,
            "origMoreSent": origMoreSent,
            "destMoreRec": destMoreRec,
            "origMoreSentFlag": origMoreSentFlag,
            "destMoreRecFlag": destMoreRecFlag,
        }

        result = self.inferModel(**data)
        y_hat = result["isFraud"]
        fraud_proba = result["fraud_probability"]

        y_true = groundTruth
        features = [data.get(x, 0) for x in VECTOR_FEATURES]
        if (y_true == 1):
            index.upsert([
                {
                    "id": f"vec_{transactionId}",
                    "values": features
                }])

        if y_true is not None:
            features_for_learning = to_feature_dict(data_learn, FEATURE_COLS)
            local_ref.learn_one(features_for_learning, y_true)
            self.dynamic_threshold.update(fraud_proba, y_true)
            self.f1_metric.update(y_true, y_hat)
            self.recall_metric.update(y_true, y_hat)
            self.auc.update(y_true, fraud_proba)
            self.precision_metric.update(y_true, y_hat)

            if y_true == 1 and y_hat == 1:
                self.tp += 1
            elif y_true == 0 and y_hat == 1:
                self.fp += 1
            elif y_true == 0 and y_hat == 0:
                self.tn += 1
            elif y_true == 1 and y_hat == 0:
                self.fn += 1

        return {
            "F1": self.f1_metric.get(),
            "Recall": self.recall_metric.get(),
            "ROC": self.auc.get(),
            "Precision": self.precision_metric.get(),
            "ConfusionMatrix": {
                "TP": self.tp,
                "FP": self.fp,
                "TN": self.tn,
                "FN": self.fn,
            },
        }
