"""Streaming fraud detection evaluation using River.

This module:
- Wraps anomaly detectors as binary classifiers.
- Uses a dynamic threshold driven by weighted percentiles and EMA.
- Builds a stacking ensemble with Logistic Regression meta-classifier.
- Tracks streaming metrics and logs periodic snapshots.
"""

import numpy as np
import pandas as pd
import os
import json
from collections import deque
from typing import Any
from river import anomaly, metrics, preprocessing
from river import ensemble, linear_model, compose
import logging

base_log = "logs.txt"
log_path = os.path.join(os.getcwd(), base_log)
os.makedirs(os.path.dirname(log_path), exist_ok=True)
logging.basicConfig(filename=log_path, level=logging.INFO, format="%(message)s")


class AnomalyToClassifier:
    """Adapter to treat River anomaly detectors as binary classifiers.

    Converts anomaly scores to probabilities and binary predictions using a
    decision threshold.

    Args:
        model: A River anomaly detector implementing ``learn_one`` and ``score_one``.
        threshold: Decision threshold for class 1 (fraud). Defaults to 0.5.
    """

    def __init__(self, model: Any, threshold: float = 0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        """Incrementally update the wrapped anomaly model.

        Tries ``learn_one(x, y)`` and falls back to ``learn_one(x)`` for models
        that ignore labels.

        Args:
            x: Feature mapping for a single sample.
            y: Optional label; ignored by models that don't support supervision.

        Returns:
            The result of the wrapped model's update (often the model itself).
        """
        try:
            return self.model.learn_one(x, y)
        except TypeError:
            return self.model.learn_one(x)

    def predict_proba_one(self, x):
        """Return probabilities for classes {0, 1} from the anomaly score.

        Args:
            x: Feature mapping for a single sample.

        Returns:
            A dict with probabilities for non-fraud (0) and fraud (1).
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return {0: 1 - score, 1: float(score)}

    def predict_one(self, x):
        """Return a binary prediction using the configured threshold.

        Args:
            x: Feature mapping for a single sample.

        Returns:
            1 if score >= threshold else 0.
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


class DynamicThresholdWrapper:
    """Adaptive thresholding over streaming fraud probabilities.

    Maintains recent fraud/non-fraud scores, computes a weighted percentile,
    and smooths the threshold via EMA with min/max bounds and a grace period.

    Args:
        window_size: Size of the rolling window of stored scores.
        percentile: Percentile used to compute the base threshold.
        ema_alpha: EMA smoothing factor in [0, 1].
        grace_period: Number of initial samples to keep a neutral threshold.
        min_threshold: Minimum allowed threshold.
        max_threshold: Maximum allowed threshold.
        fraud_weight: Weight of fraud scores in percentile computation.
        nonfraud_weight: Weight of non-fraud scores in percentile computation.
        percentile_update_interval: Interval to recompute percentile threshold.
    """

    def __init__(
        self,
        window_size: int = 10000,
        percentile: float = 50,
        ema_alpha: float = 0.1,
        grace_period: int = 250,
        min_threshold: float = 0.15,
        max_threshold: float = 0.92,
        fraud_weight: float = 0.7,
        nonfraud_weight: float = 0.3,
        percentile_update_interval: int = 50,
    ):
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
        self.ema_threshold = 0.5
        self.cached_percentile_threshold = 0.5
        self.percentile_update_interval = percentile_update_interval
        self.last_percentile_update = 0

    def update(self, y_proba_1, y_true=None):
        """Update internal state and return the current adaptive threshold.

        Args:
            y_proba_1: Probability of class 1 (fraud) for the current sample.
            y_true: Optional true label (0/1) to store per-class scores.

        Returns:
            The current EMA-smoothed threshold constrained within bounds.
        """
        self.samples_seen += 1
        if y_true is not None:
            self.recent_scores.append(y_proba_1)
            if int(y_true) == 1:
                self.fraud_scores.append(y_proba_1)
            else:
                self.nonfraud_scores.append(y_proba_1)
        if (self.samples_seen - self.last_percentile_update) >= self.percentile_update_interval:
            self.cached_percentile_threshold = self._compute_weighted_percentile()
            self.last_percentile_update = self.samples_seen
        if self.samples_seen < self.grace_period:
            self.ema_threshold = 0.5
        else:
            self.ema_threshold = (
                self.ema_alpha * self.cached_percentile_threshold
                + (1 - self.ema_alpha) * self.ema_threshold
            )
            self.ema_threshold = float(
                np.clip(self.ema_threshold, self.min_threshold, self.max_threshold))
        return self.ema_threshold

    def _compute_weighted_percentile(self):
        """Compute weighted percentile over fraud and non-fraud score buffers.

        Returns:
            Weighted percentile value; falls back to recent scores or 0.5.
        """
        weighted = []
        total_weight = 0.0
        if self.fraud_scores:
            arr = np.array(self.fraud_scores)
            p = float(np.percentile(arr, self.percentile))
            weighted.append(p * self.fraud_weight)
            total_weight += self.fraud_weight
        if self.nonfraud_scores:
            arr = np.array(self.nonfraud_scores)
            p = float(np.percentile(arr, self.percentile))
            weighted.append(p * self.nonfraud_weight)
            total_weight += self.nonfraud_weight
        if not weighted:
            if self.recent_scores:
                return float(np.percentile(np.array(self.recent_scores), self.percentile))
            return 0.5
        return float(sum(weighted) / total_weight)

    def get_threshold(self):
        """Return the latest adaptive threshold value."""
        return self.ema_threshold


def make_stacking_hst_svm():
    """Create a stacking pipeline combining HST and One-Class SVM.

    Returns:
        A River ``Pipeline`` with standard scaling and a ``StackingClassifier``
        using Logistic Regression as the meta-classifier.
    """
    base_models = [
        ("hst", AnomalyToClassifier(anomaly.HalfSpaceTrees(seed=42))),
        ("svm", AnomalyToClassifier(anomaly.OneClassSVM(nu=0.2))),
    ]
    meta = linear_model.LogisticRegression()
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.StackingClassifier(
            models=[m for _, m in base_models],
            meta_classifier=meta,
            include_features=True
        ),
    )


class StackingModel:
    """Streaming stacking model with adaptive threshold and metric tracking.

    Builds the ensemble, keeps an adaptive threshold, and provides methods to
    infer on single samples and update streaming metrics.
    """

    def __init__(self):
        self.model = make_stacking_hst_svm()
        self.dynamic_threshold = DynamicThresholdWrapper()
        self.f1_metric = metrics.F1()
        self.recall_metric = metrics.Recall()
        self.auc = metrics.ROCAUC()
        self.precision_metric = metrics.Precision()
        self.tp = self.fp = self.tn = self.fn = 0

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
                score = float(adaptive_thresh if y_hat else (1 - adaptive_thresh))
        else:
            try:
                y_hat = int(self.model.predict_one(data))
            except Exception:
                y_hat = 0
            score = float(y_hat)
        if score > adaptive_thresh:
            conf_score = (score - adaptive_thresh) / max(1 - adaptive_thresh, 1e-6)
        else:
            conf_score = (adaptive_thresh - score) / max(adaptive_thresh, 1e-6)
        return {
            "confidence_score": float(conf_score),
            "fraud_probability": float(score),
            "isFraud": int(y_hat)
        }

    def update_and_metrics(self, data, ground_truth):
        """Update model/threshold and compute streaming metrics.

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
        try:
            if ground_truth is not None and y_hat != int(ground_truth):
                self.model.learn_one(data, int(ground_truth))
        except Exception:
            pass
        self.dynamic_threshold.update(score, ground_truth)
        if ground_truth is not None:
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
        class1_acc = self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else None
        class0_acc = self.tn / (self.tn + self.fp) if (self.tn + self.fp) > 0 else None
        precision_1 = self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else None
        recall_1 = self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else None
        f1_1 = (2 * precision_1 * recall_1 / (precision_1 + recall_1)
                if precision_1 and recall_1 and (precision_1 + recall_1) > 0 else None)
        precision_0 = self.tn / (self.tn + self.fn) if (self.tn + self.fn) > 0 else None
        recall_0 = self.tn / (self.tn + self.fp) if (self.tn + self.fp) > 0 else None
        f1_0 = (2 * precision_0 * recall_0 / (precision_0 + recall_0)
                if precision_0 and recall_0 and (precision_0 + recall_0) > 0 else None)
        classification_report = {
            "0": {"precision": precision_0, "recall": recall_0, "f1": f1_0, "accuracy": class0_acc},
            "1": {"precision": precision_1, "recall": recall_1, "f1": f1_1, "accuracy": class1_acc},
            "overall": {
                "accuracy": acc,
                "macro_f1": np.nanmean([f1_0, f1_1]) if f1_0 is not None and f1_1 is not None else None,
            },
        }
        metrics_snapshot = {
            "F1": self.f1_metric.get(),
            "Recall": self.recall_metric.get(),
            "ROC": self.auc.get(),
            "Precision": self.precision_metric.get(),
            "ConfusionMatrix": {"TP": self.tp, "FP": self.fp, "TN": self.tn, "FN": self.fn},
            "PerClassAccuracy": {"Class0": class0_acc, "Class1": class1_acc},
            "ClassificationReport": classification_report,
        }
        return result, metrics_snapshot


base_csv = "fraudulent_e-commerce_transactions.csv"
input_path = os.path.join(os.getcwd(), base_csv)
df = pd.read_csv(input_path)

LOG_LINES = 2000
model = StackingModel()

for idx, row in df.iterrows():
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
        "transaction_hour": row["transaction_hour"]
    }

    ground_truth = int(row["is_fraudulent"])

    out, metrics_snapshot = model.update_and_metrics(data, ground_truth)

    if ((idx + 1) % LOG_LINES == 0):
        logging.info(f"Processed {idx + 1:,} samples")
        logging.info(json.dumps(metrics_snapshot))
