"""Streaming evaluation of HST+SVM River ensembles for fraud detection.

This module:
- Wraps River anomaly detectors to behave like binary classifiers.
- Maintains an adaptive decision threshold using weighted percentiles and EMA.
- Provides multiple River ensemble builders (Voting, ADWIN Bagging/Boosting, Stacking).
- Streams over datasets, computes metrics, and logs periodic and final reports.
"""

import numpy as np
import pandas as pd
from collections import deque
from typing import Any
import sys
from tqdm.auto import tqdm
import os
import pickle
import logging
from river import (
    ensemble,
    preprocessing,
    linear_model,
    compose,
    anomaly,
    metrics
)
from sklearn.metrics import (
    classification_report,
    confusion_matrix
)
LOG_LINES_RIVER = 50000
# add the dataset files in the same folder as this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASETS = [
    os.path.join(BASE_DIR, "credit_card.csv"),
    os.path.join(BASE_DIR, "synthetic_financial_datasets_paysim.csv"),
    os.path.join(BASE_DIR, "fraudulent_e-commerce_transactions.csv"),
    os.path.join(BASE_DIR, "financial_transactions_dataset.csv"),
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)
logger = logging.getLogger(__name__)


class AnomalyToClassifier:
    """Adapter to use River anomaly detectors as binary classifiers.

    Converts anomaly ``score_one`` outputs into probabilities and
    thresholded predictions.

    Args:
        model: River anomaly model implementing ``learn_one`` and ``score_one``.
        threshold: Decision threshold for class 1 (fraud). Defaults to 0.5.
    """

    def __init__(self, model: Any, threshold: float = 0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        """Incrementally update the wrapped anomaly model.

        Tries ``learn_one(x, y)``; falls back to ``learn_one(x)`` if the
        model ignores labels.

        Args:
            x: Feature mapping for one sample.
            y: Optional label.

        Returns:
            Result of the wrapped model update (often the model itself).
        """
        try:
            return self.model.learn_one(x, y)
        except TypeError:
            return self.model.learn_one(x)

    def clone(self):
        """Clone the wrapped model for use in ensemble base learners.

        Returns:
            A new ``AnomalyToClassifier`` wrapping a cloned inner model.
        """
        # ADWINBagging/Boosting call .clone() on the base model.
        # We simply clone the inner River model and wrap it again.
        if hasattr(self.model, "clone"):
            inner = self.model.clone()
        else:
            import copy
            inner = copy.deepcopy(self.model)
        return AnomalyToClassifier(model=inner, threshold=self.threshold)

    def predict_proba_one(self, x):
        """Return probabilities {0, 1} derived from the anomaly score.

        Args:
            x: Feature mapping for one sample.

        Returns:
            Dict with probabilities for non-fraud (0) and fraud (1).
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return {0: 1 - score, 1: float(score)}

    def predict_one(self, x):
        """Return binary prediction using the configured threshold.

        Args:
            x: Feature mapping for one sample.

        Returns:
            1 if score >= threshold else 0.
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


class DynamicThresholdWrapper:
    """Adaptive thresholding for streaming fraud probabilities.

    Maintains recent scores, computes a weighted percentile, and smooths the
    threshold via EMA with min/max bounds and a grace period.

    Args:
        window_size: Size of rolling buffers for recent scores.
        percentile: Percentile used for base threshold computation.
        ema_alpha: EMA smoothing factor in [0, 1].
        grace_period: Number of initial samples using neutral threshold 0.5.
        min_threshold: Minimum threshold bound.
        max_threshold: Maximum threshold bound.
        fraud_weight: Weight applied to fraud score percentile.
        nonfraud_weight: Weight applied to non-fraud score percentile.
        percentile_update_interval: Interval to recompute percentile threshold.
    """

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
        - fraud_weight/nonfraud_weight: Adjusted to give more weight
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
        """Update internal state and return current adaptive threshold.

        Args:
            y_proba_1: Probability of class 1 (fraud) for the current sample.
            y_true: Optional true label (0/1) to store per-class buffers.

        Returns:
            The EMA-smoothed threshold constrained within min/max bounds.
        """
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

        # Update threshold only once every percentile_update_interval samples
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
            # Clip the threshold to our defined min/max range
            self.ema_threshold = np.clip(
                self.ema_threshold, self.min_threshold, self.max_threshold
            )
        return self.ema_threshold

    def _compute_weighted_percentile(self):
        """Compute weighted percentile from fraud and non-fraud buffers.

        Returns:
            Weighted percentile; falls back to recent scores or 0.5 if empty.
        """
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
        """Return the latest adaptive threshold value."""
        return self.ema_threshold

    def is_anomaly(self, anomaly_score: float, is_fraud: int) -> bool:
        """Update threshold with the score and return anomaly decision.

        Args:
            anomaly_score: The score to compare against the adaptive threshold.
            is_fraud: Optional label for buffer updates; treated as 0 if None.

        Returns:
            True if ``anomaly_score >= current_threshold`` else False.
        """
        # If is_fraud is None, we are in inference mode.
        # Treat it as non-fraud (0) for score collection.
        label = 0 if is_fraud is None else int(is_fraud)
        _ = AnomalyToClassifier.predict_proba_one(self, anomaly_score)
        self.update(anomaly_score, label)

        if abs(self.ema_threshold - self.last_threshold) > 0.05:
            self.last_threshold = self.ema_threshold

        return anomaly_score >= self.ema_threshold  # type: ignore


class StreamingEnsembleModel:
    """Streaming wrapper providing inference and metric tracking for ensembles.

    Holds a River model, computes predictions per sample using an adaptive
    threshold, performs conditional online updates, and accumulates metrics.

    Args:
        model: A River estimator/pipeline implementing ``predict_*`` and
            optionally ``learn_one`` for online updates.
    """

    def __init__(self, model):
        self.model = model
        self.dynamic_threshold = DynamicThresholdWrapper()
        self.f1_metric = metrics.F1() if metrics is not None else None
        self.recall_metric = metrics.Recall() if metrics is not None else None
        self.auc = metrics.ROCAUC() if metrics is not None else None
        self.precision_metric = metrics.Precision() if metrics is not None else None
        self.tp = self.fp = self.tn = self.fn = 0
        self.y_true_list = []
        self.y_pred_list = []

    def infer_one(self, data):
        """Infer fraud probability and binary decision for one sample.

        Attempts ``predict_proba_one``; falls back to ``predict_one`` if needed.
        Confidence score reflects distance from the adaptive threshold.

        Args:
            data: Feature mapping for a single transaction.

        Returns:
            Dict with keys: ``confidence_score``, ``fraud_probability``, ``isFraud``.
        """
        y_hat = 0
        score = 0.0
        adaptive_thresh = self.dynamic_threshold.get_threshold()

        if hasattr(self.model, "predict_proba_one"):
            try:
                y_proba = self.model.predict_proba_one(data)
                if isinstance(y_proba, dict):
                    score = float(y_proba.get(1, y_proba.get(True, 0.0)))
                else:
                    score = float(y_proba)
                y_hat = int(score >= adaptive_thresh)
            except Exception:
                try:
                    y_hat = int(self.model.predict_one(data))
                except Exception:
                    y_hat = 0
                score = float(adaptive_thresh if y_hat else (
                    1 - adaptive_thresh))
        else:
            try:
                y_hat = int(self.model.predict_one(data))
            except Exception:
                y_hat = 0
            score = float(y_hat)

        if score > adaptive_thresh:
            conf_score = (score - adaptive_thresh) / \
                max(1 - adaptive_thresh, 1e-6)
        else:
            conf_score = (adaptive_thresh - score) / max(adaptive_thresh, 1e-6)

        return {
            "confidence_score": float(conf_score),
            "fraud_probability": float(score),
            "isFraud": int(y_hat)
        }

    def update_and_metrics(self, data, ground_truth):
        """Update model/threshold and compute streaming metrics for one sample.

        Performs inference, optional supervised update, threshold update, and
        updates classification metrics and confusion counts.

        Args:
            data: Feature mapping for a single transaction.
            ground_truth: True label (0/1) if available.

        Returns:
            Tuple of (result_dict, metrics_snapshot_dict).
        """
        result = self.infer_one(data)
        y_hat = int(result["isFraud"])
        score = float(result["fraud_probability"])

        if ground_truth is not None:
            self.y_true_list.append(int(ground_truth))
            self.y_pred_list.append(y_hat)

        if hasattr(self.model, "learn_one"):
            try:
                if ground_truth is not None and y_hat != int(ground_truth):
                    try:
                        self.model.learn_one(data, int(ground_truth))
                    except TypeError:
                        self.model.learn_one(data)
            except Exception:
                pass

        self.dynamic_threshold.update(score, ground_truth)

        if ground_truth is not None and self.f1_metric is not None:
            self.f1_metric.update(ground_truth, y_hat)
            self.recall_metric.update(ground_truth, y_hat)
            try:
                self.auc.update(ground_truth, score)
            except Exception:
                pass
            self.precision_metric.update(ground_truth, y_hat)

            if ground_truth == 1 and y_hat == 1:
                self.tp += 1
            elif ground_truth == 0 and y_hat == 1:
                self.fp += 1
            elif ground_truth == 0 and y_hat == 0:
                self.tn += 1
            elif ground_truth == 1 and y_hat == 0:
                self.fn += 1

        total = self.tp + self.fp + self.tn + self.fn
        acc = (self.tp + self.tn) / total if total > 0 else None
        class1_acc = self.tp / \
            (self.tp + self.fn) if (self.tp + self.fn) > 0 else None
        class0_acc = self.tn / \
            (self.tn + self.fp) if (self.tn + self.fp) > 0 else None

        precision_1 = self.tp / \
            (self.tp + self.fp) if (self.tp + self.fp) > 0 else None
        recall_1 = self.tp / \
            (self.tp + self.fn) if (self.tp + self.fn) > 0 else None
        f1_1 = (2 * precision_1 * recall_1 / (precision_1 + recall_1)
                if precision_1 and recall_1 and (precision_1 + recall_1) > 0 else None)

        precision_0 = self.tn / \
            (self.tn + self.fn) if (self.tn + self.fn) > 0 else None
        recall_0 = self.tn / \
            (self.tn + self.fp) if (self.tn + self.fp) > 0 else None
        f1_0 = (2 * precision_0 * recall_0 / (precision_0 + recall_0)
                if precision_0 and recall_0 and (precision_0 + recall_0) > 0 else None)

        classification_report_dict = {
            "0": {"precision": precision_0, "recall": recall_0, "f1": f1_0, "accuracy": class0_acc},
            "1": {"precision": precision_1, "recall": recall_1, "f1": f1_1, "accuracy": class1_acc},
            "overall": {
                "accuracy": acc,
                "macro_f1": np.nanmean([f1_0, f1_1]) if f1_0 is not None and f1_1 is not None else None,
            },
        }

        metrics_snapshot = {
            "F1": self.f1_metric.get() if self.f1_metric else None,
            "Recall": self.recall_metric.get() if self.recall_metric else None,
            "ROC": self.auc.get() if self.auc else None,
            "Precision": self.precision_metric.get() if self.precision_metric else None,
            "ConfusionMatrix": {"TP": self.tp, "FP": self.fp, "TN": self.tn, "FN": self.fn},
            "PerClassAccuracy": {"Class0": class0_acc, "Class1": class1_acc},
            "ClassificationReport": classification_report_dict,
        }
        return result, metrics_snapshot


def _hst_svm_base_models():
    """Create base anomaly models wrapped for classification.

    Returns:
        List of ``AnomalyToClassifier`` wrapping HST and One-Class SVM.
    """
    return [
        AnomalyToClassifier(
            model=anomaly.HalfSpaceTrees(seed=42)
        ),
        AnomalyToClassifier(
            model=anomaly.OneClassSVM()
        ),
    ]


def make_voting_hst_svm():
    """Build a VotingClassifier pipeline using HST and One-Class SVM.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``VotingClassifier``.
    """
    base_models = _hst_svm_base_models()
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.VotingClassifier(
            models=base_models,
            use_probabilities=True
        ),
    )


def make_adwin_bagging_hst():
    """Build an ADWINBaggingClassifier pipeline with HST base model.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``ADWINBaggingClassifier``.
    """
    base = AnomalyToClassifier(
        model=anomaly.HalfSpaceTrees(seed=42)
    )
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.ADWINBaggingClassifier(
            model=base,
            n_models=5,
            seed=42
        ),
    )


def make_adwin_boosting_hst():
    """Build an ADWINBoostingClassifier pipeline with HST base model.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``ADWINBoostingClassifier``.
    """
    base = AnomalyToClassifier(
        model=anomaly.HalfSpaceTrees(seed=42)
    )
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.ADWINBoostingClassifier(
            model=base,
            n_models=5,
            seed=42
        ),
    )


def make_stacking_hst_svm():
    """Build a StackingClassifier pipeline with HST and One-Class SVM.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``StackingClassifier``
        using Logistic Regression as meta-classifier.
    """
    base_models = [
        AnomalyToClassifier(model=anomaly.HalfSpaceTrees(seed=42)),
        AnomalyToClassifier(model=anomaly.OneClassSVM()),
    ]
    meta = linear_model.LogisticRegression()
    stacking_core = ensemble.StackingClassifier(
        models=base_models,
        meta_classifier=meta,
        include_features=True,
    )
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        stacking_core,
    )


def _log_sklearn_reports(prefix, y_true, y_pred):
    """Log sklearn classification report and confusion matrix if any labels exist.

    Args:
        prefix: Message prefix for logs.
        y_true: List of true labels.
        y_pred: List of predicted labels.
    """
    if len(y_true) == 0:
        return
    cr = classification_report(y_true, y_pred, digits=4, zero_division=0)
    cm = confusion_matrix(y_true, y_pred)
    logger.info("%s\nclassification_report:\n%s", prefix, cr)
    logger.info("%s\nconfusion_matrix:\n%s", prefix, cm)


def run_river_ensembles_on_df(df, dataset_name):
    """Run River ensemble models on a dataframe and log metrics.

    Builds several ensemble variants, streams over rows, updates the
    adaptive threshold and metrics, and prints interval/final summaries.

    Args:
        df: pandas dataframe with the dataset.
        dataset_name: Path or name of the dataset (used for logging).
    """
    river_models = {
        "stacking_hst_svm": make_stacking_hst_svm,
        "adwinbagging_hst": make_adwin_bagging_hst,
        "adwinboost_hst": make_adwin_boosting_hst,
    }

    basename = os.path.basename(dataset_name)

    for model_name, builder in river_models.items():
        logger.info("Dataset: %s | River model: %s", dataset_name, model_name)
        model = StreamingEnsembleModel(builder())
        metrics_snapshot = None

        for idx, row in tqdm(
            df.iterrows(),
            total=len(df),
            desc=f"{model_name} on {os.path.basename(dataset_name)}",
        ):
            if basename == "financial_transactions_dataset.csv":
                data = {
                    "card_client_id": row["card_client_id"],
                    "card_id": row["card_id"],
                    "amount": row["amount"],
                    "use_chip": row["use_chip"],
                    "merchant_id": row["merchant_id"],
                    "card_brand": row["card_brand"],
                    "card_type": row["card_type"],
                    "num_cards_issued": row["num_cards_issued"],
                    "credit_limit": row["credit_limit"],
                    "total_debt": row["total_debt"],
                    "credit_score": row["credit_score"],
                    "num_credit_cards": row["num_credit_cards"],
                    "Time": row["timestamp"],
                    "Amount": row["amount"],
                }
                ground_truth = row["is_fraud"]
            elif basename == "synthetic_financial_datasets_paysim.csv":
                data = {
                    "step": row["step"],
                    "type": row["type"],
                    "amount": row["amount"],
                    "oldbalanceOrg": row["oldbalanceOrg"],
                    "newbalanceOrig": row["newbalanceOrig"],
                    "oldbalanceDest": row["oldbalanceDest"],
                    "newbalanceDest": row["newbalanceDest"],
                    "diffOrg": row["diffOrg"],
                    "diffDest": row["diffDest"],
                    "Time": row["step"],
                    "Amount": row["amount"],
                }
                ground_truth = row["isFraud"]
            elif basename == "fraudulent_e-commerce_transactions.csv":
                data = {
                    "transaction_id": row["transaction_id"],
                    "customer_id": row["customer_id"],
                    "transaction_amount": row["transaction_amount"],
                    "transaction_date": row["transaction_date"],
                    "payment_method": row["payment_method"],
                    "product_category": row["product_category"],
                    "quantity": row["quantity"],
                    "customer_age": row["customer_age"],
                    "customer_location": row["customer_location"],
                    "device_used": row["device_used"],
                    "ip_address": row["ip_address"],
                    "shipping_address": row["shipping_address"],
                    "billing_address": row["billing_address"],
                    "account_age_days": row["account_age_days"],
                    "transaction_hour": row["transaction_hour"],
                    "Time": row["transaction_date"],
                    "Amount": row["transaction_amount"],
                }
                ground_truth = row["is_fraudulent"]
            else:
                data = {f"V{i+1}": row[f"V{i+1}"] for i in range(28)}
                data["Time"] = row["Time"]
                data["Amount"] = row["Amount"]
                ground_truth = row.get("Class")

            _, metrics_snapshot = model.update_and_metrics(data, ground_truth)

            if ((idx + 1) % LOG_LINES_RIVER == 0):
                prefix = f"[{model_name} | {os.path.basename(dataset_name)} | seen={idx+1}]"
                logger.info("%s metrics_snapshot: %s", prefix, metrics_snapshot)
                _log_sklearn_reports(prefix, model.y_true_list, model.y_pred_list)

        if metrics_snapshot is not None:
            prefix = f"[{model_name} | {os.path.basename(dataset_name)} | final]"
            logger.info("%s FINAL metrics_snapshot: %s", prefix, metrics_snapshot)
            _log_sklearn_reports(prefix, model.y_true_list, model.y_pred_list)


if __name__ == "__main__":
    """Script entry point: iterate configured datasets and evaluate ensembles."""
    for path in DATASETS:
        if not os.path.exists(path):
            logger.warning("Skipping missing dataset: %s", path)
            continue
        df = pd.read_csv(path)
        run_river_ensembles_on_df(df, path)
