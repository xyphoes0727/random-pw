"""Paysim streaming evaluation with HST+SVM stacking and adaptive thresholding.

This script:
- Trains a River stacking ensemble (HalfSpaceTrees + OneClassSVM with LogisticRegression meta).
- Uses an adaptive threshold based on weighted percentiles and EMA to improve recall.
- Saves the trained model and evaluates on the holdout split, reporting metrics.
"""

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
from imblearn.under_sampling import RandomUnderSampler
import numpy as np
from collections import deque
import pickle
import os
from pathlib import Path
import logging
import pandas as pd
from tqdm import tqdm
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

base_csv = "synthetic_financial_datasets_paysim.csv"
DATA_PATH = os.path.join(os.getcwd(), base_csv)
MODEL_NAME = "hst_svm_stacking.pkl"
TRAIN_FRACTION = 0.4


class AnomalyToClassifier:
    """Adapter to use River anomaly detectors as binary classifiers.

    Converts anomaly scores from ``score_one`` into probabilities and
    thresholded predictions via a configurable decision threshold.

    Args:
        model: River anomaly model implementing ``learn_one`` and ``score_one``.
        threshold: Decision threshold for class 1 (fraud). Defaults to 0.5.
    """
    def __init__(self, model, threshold=0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        """Incrementally update the wrapped anomaly model.

        Args:
            x: Feature mapping for a single sample.
            y: Optional label; ignored by anomaly models that don't use supervision.

        Returns:
            Self.
        """
        self.model.learn_one(x)
        return self

    def predict_proba_one(self, x):
        """Return probabilities {0, 1} derived from the anomaly score.

        Args:
            x: Feature mapping for a single sample.

        Returns:
            Dict with probabilities for non-fraud (0) and fraud (1).
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)

        # prob = 1 / (1 + np.exp(-score))
        return {0: 1 - score, 1: score}

    def predict_one(self, x):
        """Return binary prediction using the configured threshold.

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

    Maintains buffers of recent fraud/non-fraud scores, periodically computes a
    weighted percentile, and smooths the decision threshold via EMA with bounds
    and a grace period.

    Args:
        window_size: Size of the rolling window of stored scores.
        percentile: Percentile used for base threshold computation.
        ema_alpha: EMA smoothing factor in [0, 1].
        grace_period: Number of initial samples using neutral threshold 0.5.
        min_threshold: Minimum threshold bound.
        max_threshold: Maximum threshold bound.
        fraud_weight: Weight applied to fraud score percentile.
        nonfraud_weight: Weight applied to non-fraud score percentile.
        percentile_update_interval: Interval (in samples) to recompute percentile.
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
        """Compute a weighted percentile from fraud and non-fraud buffers.

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


def loadModel(modelName: str) -> compose.Pipeline:
    """Load a pickled River pipeline by name from the local savedModels folder.

    Args:
        modelName: Filename of the pickled model.

    Returns:
        The loaded River ``Pipeline``.
    """
    current_file_dir = Path(__file__).parent
    model_path = current_file_dir / "savedModels" / modelName
    with open(model_path, "rb") as f:
        model = pickle.load(f)
        return model


def make_stacking_ensemble():
    """Create HST + One-Class SVM stacking ensemble with Logistic meta-classifier.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``StackingClassifier``.
    """
    base_models = [
        ("hst", AnomalyToClassifier(anomaly.HalfSpaceTrees(seed=42))),
        ("svm", AnomalyToClassifier(anomaly.OneClassSVM(nu=0.2))),
    ]
    meta = linear_model.LogisticRegression()
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.StackingClassifier(
            models=[m for _, m in base_models],  # type: ignore
            meta_classifier=meta,
            include_features=True
        )
    )


class StackingModel:
    """Wrapper around the trained stacking model with adaptive thresholding.

    Provides single-sample inference and metric accumulation utilities.

    Args:
        modelName: Filename of the pickled model to load.
    """
    def __init__(self, modelName):
        self.modelName = modelName
        self.model = loadModel(modelName)
        self.dynamic_threshold = DynamicThresholdWrapper()
        # self.human_feedback = {} # Store recent human feedback
        # self.pending_feedback = ()
        # self.metrics_path = "./saved_metrics.json"
        self.f1_metric = metrics.F1()
        self.recall_metric = metrics.Recall()
        self.auc = metrics.ROCAUC()
        self.precision_metric = metrics.Precision()
        self.tp = 0
        self.fp = 0
        self.tn = 0
        self.fn = 0
        self.precision_metric_value = 0.0

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
        newbalanceDest
    ):
        """Infer fraud decision and probability for one Paysim transaction.

        Uses log-transformed amount and the adaptive threshold to produce a
        binary decision and a confidence score.

        Args:
            transactionId: Unique identifier for the transaction (unused in inference).
            step: Time step in the Paysim dataset.
            type: Transaction type.
            amount: Raw transaction amount.
            logamount: Log-transformed amount used for the model.
            oldbalanceOrg: Origin account balance before transaction.
            newbalanceOrig: Origin account balance after transaction.
            oldbalanceDest: Destination account balance before transaction.
            newbalanceDest: Destination account balance after transaction.

        Returns:
            Dict with keys: ``confidence_score``, ``fraud_probability``, ``isFraud``.
        """
        data = {
            "step": step,
            "type": type,
            "amount": logamount,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest
        }
        y_hat = 0
        score = 0.0
        if hasattr(self.model, "predict_proba_one"):
            y_proba = self.model.predict_proba_one(data)

            adaptive_thresh = self.dynamic_threshold.get_threshold()

            if isinstance(y_proba, dict):
                score = y_proba[True]
                y_hat = int(score >= adaptive_thresh)
            else:
                y_hat = int(y_proba >= adaptive_thresh)

        conf_score = 0.
        if (score > adaptive_thresh):
            conf_score = (score-adaptive_thresh)/(1-adaptive_thresh)
        else:
            conf_score = (adaptive_thresh-score)/adaptive_thresh
        return {"confidence_score": conf_score, "fraud_probability": score, "isFraud": y_hat}

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
        groundTruth
    ):
        """Update model and threshold with ground truth and return metrics snapshot.

        Performs supervised update on disagreement, updates streaming metrics
        and confusion counts.

        Args:
            transactionId: Transaction identifier.
            step: Time step in the Paysim dataset.
            transaction_type: Transaction type.
            amount: Raw transaction amount.
            logamount: Log-transformed amount.
            oldbalanceOrg: Origin account balance before transaction.
            newbalanceOrig: Origin account balance after transaction.
            oldbalanceDest: Destination account balance before transaction.
            newbalanceDest: Destination account balance after transaction.
            groundTruth: True label (0/1).

        Returns:
            Dict snapshot of metrics including F1, Recall, ROC, Precision, and confusion counts.
        """
        data = {
            "transactionId": transactionId,
            "step": step,
            "type": transaction_type,
            "amount": amount,
            "logamount": logamount,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest
        }
        data_learn = {
            "step": step,
            "type": transaction_type,
            "amount": logamount,
            "oldbalanceOrg": oldbalanceOrg,
            "newbalanceOrig": newbalanceOrig,
            "oldbalanceDest": oldbalanceDest,
            "newbalanceDest": newbalanceDest
        }
        result = self.inferModel(**data)
        y_hat = result["isFraud"]
        score = result["confidence_score"]

        y_true = groundTruth
        if y_true is not None:
            self.model.learn_one(data_learn, y_true)
            self.dynamic_threshold.update(score, y_true)
            self.f1_metric.update(y_true, y_hat)
            self.recall_metric.update(y_true, y_hat)
            self.auc.update(y_true, score)
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
            "ConfusionMatrix": {"TP": self.tp, "FP": self.fp, "TN": self.tn, "FN": self.fn}
        }


def train_and_save_model():
    """Train the stacking ensemble on a balanced subset and save the model.

    Shuffles, log-transforms amount, undersamples to balance classes, trains
    online, and pickles the model under ``savedModels``.

    Returns:
        Tuple of (full dataframe, number of training rows).
    """
    current_file_dir = Path(__file__).parent
    model_dir = current_file_dir / "savedModels"
    model_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(DATA_PATH)
    df = df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    if "logamount" not in df.columns:
        df["logamount"] = np.log1p(df["amount"])

    n_train = int(len(df) * TRAIN_FRACTION)
    train_df = df.iloc[:n_train].copy()

    feature_cols = [
        "step",
        "type",
        "logamount",
        "oldbalanceOrg",
        "newbalanceOrig",
        "oldbalanceDest",
        "newbalanceDest",
    ]

    X = train_df[feature_cols]
    y = train_df["isFraud"].astype(int)

    rus = RandomUnderSampler(random_state=42)
    X_res, y_res = rus.fit_resample(X, y)

    resampled_df = X_res.copy()
    resampled_df["isFraud"] = y_res.values

    model = make_stacking_ensemble()

    for _, row in tqdm(resampled_df.iterrows(), total=len(resampled_df)):
        x = {
            "step": row["step"],
            "type": row["type"],
            "amount": row["logamount"],
            "oldbalanceOrg": row["oldbalanceOrg"],
            "newbalanceOrig": row["newbalanceOrig"],
            "oldbalanceDest": row["oldbalanceDest"],
            "newbalanceDest": row["newbalanceDest"],
        }
        y_val = int(row["isFraud"])
        model.learn_one(x, y_val)

    model_path = model_dir / MODEL_NAME
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    return df, n_train


def test_with_stacking_wrapper(df, n_train):
    """Evaluate the saved stacking model on the holdout and print reports.

    Streams through the test split, collects predictions, prints periodic and
    final classification reports, and returns the last metrics snapshot.

    Args:
        df: Full dataframe including train/test splits.
        n_train: Number of rows used for training.

    Returns:
        The last metrics snapshot dict from the streaming evaluation.
    """
    test_df = df.iloc[n_train:].copy().reset_index(drop=True)
    stacking = StackingModel(MODEL_NAME)

    y_true_list = []
    y_pred_list = []

    last_metrics = None

    for idx, row in tqdm(test_df.iterrows(), total=len(test_df)):
        infer_out = stacking.inferModel(
            transactionId=int(idx),
            step=row["step"],
            type=row["type"],
            amount=row["amount"],
            logamount=row["logamount"],
            oldbalanceOrg=row["oldbalanceOrg"],
            newbalanceOrig=row["newbalanceOrig"],
            oldbalanceDest=row["oldbalanceDest"],
            newbalanceDest=row["newbalanceDest"]
        )

        y_hat = infer_out["isFraud"]
        y_true = int(row["isFraud"])

        last_metrics = stacking.get_metrics(
            transactionId=int(idx),
            step=row["step"],
            transaction_type=row["type"],
            amount=row["amount"],
            logamount=row["logamount"],
            oldbalanceOrg=row["oldbalanceOrg"],
            newbalanceOrig=row["newbalanceOrig"],
            oldbalanceDest=row["oldbalanceDest"],
            newbalanceDest=row["newbalanceDest"],
            groundTruth=y_true
        )

        y_true_list.append(y_true)
        y_pred_list.append(y_hat)

        if (idx + 1) % 10000 == 0:
            print(classification_report(y_true_list, y_pred_list, digits=4))
            print(confusion_matrix(y_true_list, y_pred_list))

    print(classification_report(y_true_list, y_pred_list, digits=4))
    print(confusion_matrix(y_true_list, y_pred_list))
    return last_metrics


if __name__ == "__main__":
    """Script entry point to train, save, and evaluate the Paysim model."""
    df_all, n_train_rows = train_and_save_model()
    final_metrics = test_with_stacking_wrapper(df_all, n_train_rows)
    print("Final metrics:")
    print(final_metrics)
