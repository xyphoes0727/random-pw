import numpy as np
import pandas as pd
import os
from collections import deque
from typing import Any
from river import (
    ensemble,
    preprocessing,
    linear_model,
    compose,
    anomaly,
    metrics
)


class AnomalyToClassifier:
    """Wrapper to adapt a river anomaly detector for classifier-like behavior."""

    def __init__(self, model: Any, threshold: float = 0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        try:
            return self.model.learn_one(x, y)
        except TypeError:
            return self.model.learn_one(x)

    def predict_proba_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return {0: 1 - score, 1: float(score)}

    def predict_one(self, x):
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
        return int(score >= self.threshold)


class DynamicThresholdWrapper:
    """Adaptive threshold computed from recent model scores."""

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
        return self.ema_threshold
# --- Model Factories ---


def make_stacking_hst_svm():
    base_models = [
        ("hst", AnomalyToClassifier(
            anomaly.QuantileFilter(
                anomaly.HalfSpaceTrees(seed=42),
                q=0.95
            )
        )),
        ("svm", AnomalyToClassifier(anomaly.QuantileFilter(
            anomaly.OneClassSVM(nu=0.2),
            q=0.95
        ))),
    ]
    meta = linear_model.LogisticRegression()
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.StackingClassifier(models=[m for _, m in base_models],
                                    meta_classifier=meta,
                                    include_features=True),
    )


class StackingModel:
    """Wrapper around a river model that maintains adaptive threshold and online metrics."""

    def __init__(self):

        self.model = make_stacking_hst_svm()
        self.dynamic_threshold = DynamicThresholdWrapper()
        self.f1_metric = metrics.F1()
        self.recall_metric = metrics.Recall()
        self.auc = metrics.ROCAUC()
        self.precision_metric = metrics.Precision()
        self.tp = self.fp = self.tn = self.fn = 0

    def infer_one(self, data):
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
        """Perform inference, update model (if supported), and update metrics."""
        result = self.infer_one(data)
        y_hat = int(result["isFraud"])
        score = float(result["fraud_probability"])

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

        classification_report = {
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
            "ClassificationReport": classification_report,
        }
        return result, metrics_snapshot


base_csv = "synthetic_financial_datasets_paysim.csv"
input_path = os.path.join(os.getcwd(), base_csv)
df = pd.read_csv(input_path)

LOG_LINES = 2000

model = StackingModel()

for idx, row in df.iterrows():
    data = row.drop("isFraud").to_dict()

    ground_truth = row.get("isFraud")
    out, metrics_snapshot = model.update_and_metrics(data, ground_truth)

    if ((idx+1) % LOG_LINES == 0):  # type: ignore
        print(f"Processed {idx + 1:,} samples...")  # type: ignore
        print(metrics_snapshot)
