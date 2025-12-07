"""Streaming evaluation of ARF-based ensembles and logistic regression using River.

This module:
- Defines utilities for encoding features and building River pipelines.
- Implements an adaptive threshold wrapper for streaming fraud probabilities.
- Processes multiple datasets in a single pass, logs interval reports, and saves/loads models incrementally.
"""

import os
import sys
import traceback
import numpy as np
import pandas as pd
from tqdm.auto import tqdm
import logging
import pickle
from pathlib import Path
from collections import deque, defaultdict
from river import (
    ensemble,
    preprocessing,
    linear_model,
    compose,
    optim,
    metrics
)
from river import forest

from sklearn.metrics import (
    classification_report,
    confusion_matrix
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASETS = [
    os.path.join(BASE_DIR, "credit_card.csv"),
    os.path.join(BASE_DIR, "synthetic_financial_datasets_paysim.csv"),
    os.path.join(BASE_DIR, "fraudulent_e-commerce_transactions.csv"),
    os.path.join(BASE_DIR, "financial_transactions_dataset.csv"),
]

MODEL_SAVE_DIR = Path("./savedModels")
MODEL_SAVE_DIR.mkdir(parents=True, exist_ok=True)

LOG_EVERY = 50000


class AnomalyToClassifier:
    """Adapter to use anomaly detectors as binary classifiers.

    Converts anomaly scores from ``score_one`` into probabilities and thresholded
    predictions.

    Args:
        model: A River anomaly model exposing ``learn_one`` and ``score_one``.
        threshold: Decision threshold for class 1 (fraud). Defaults to 0.5.
    """
    def __init__(self, model, threshold=0.5):
        self.model = model
        self.threshold = threshold

    def learn_one(self, x, y=None):
        """Incrementally update the wrapped anomaly model.

        Tries supervised update if supported; otherwise falls back to unsupervised
        ``learn_one(x)``.

        Args:
            x: Feature mapping for a single sample.
            y: Optional label; ignored if the model does not accept it.

        Returns:
            Self.
        """
        try:
            self.model.learn_one(x)
        except TypeError:
            try:
                self.model.learn_one(x, y)
            except TypeError:
                pass
        return self

    def predict_proba_one(self, x):
        """Return probabilities for non-fraud and fraud classes.

        Args:
            x: Feature mapping for a single sample.

        Returns:
            Dict {0: p(non-fraud), 1: p(fraud)} derived from anomaly score.
        """
        try:
            score = self.model.score_one(x)
        except TypeError:
            score = self.model.score_one(x, 1)
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
    """Adaptive thresholding over streaming probabilities.

    Maintains buffers of recent fraud/non-fraud scores, periodically computes a
    weighted percentile, and smooths the decision threshold via EMA with bounds
    and a grace period. Optionally persists recent probabilities/labels.

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
        save_path: Path to persist last window of probabilities and labels.
    """
    def __init__(
        self,
        window_size=10000,
        percentile=50,
        ema_alpha=0.1,
        grace_period=250,
        min_threshold=0.15,
        max_threshold=0.92,
        fraud_weight=0.70,
        nonfraud_weight=0.30,
        percentile_update_interval=50,
        save_path='./last_10k_data.pkl',
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
        self.last_threshold = 0.5

        self.percentile_update_interval = percentile_update_interval
        self.last_percentile_update = 0

        self.cached_percentile_threshold = 0.5
        self.y_probas = deque(maxlen=window_size)
        self.y_labels = deque(maxlen=window_size)
        self.save_path = save_path
        os.makedirs(os.path.dirname(self.save_path) or '.', exist_ok=True)

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
            try:
                with open(self.save_path, 'wb') as f:
                    pickle.dump({'y_probas': list(self.y_probas), 'y_true': list(self.y_labels)}, f)
            except Exception:
                logger.debug("Failed to save last data for dynamic threshold", exc_info=True)

        if self.samples_seen - self.last_percentile_update >= self.percentile_update_interval:
            self.cached_percentile_threshold = self._compute_weighted_percentile()
            self.last_percentile_update = self.samples_seen

        if self.samples_seen < self.grace_period:
            self.ema_threshold = 0.5
        else:
            self.ema_threshold = (
                self.ema_alpha * self.cached_percentile_threshold
                + (1 - self.ema_alpha) * self.ema_threshold
            )
            self.ema_threshold = np.clip(self.ema_threshold, self.min_threshold, self.max_threshold)
        return self.ema_threshold

    def _compute_weighted_percentile(self):
        """Compute a weighted percentile from fraud/non-fraud buffers.

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
            if self.recent_scores:
                return np.percentile(np.array(self.recent_scores), self.percentile)
            return 0.5

        return sum(weighted_thresholds) / total_weight

    def get_threshold(self):
        """Return the latest adaptive threshold value."""
        return self.ema_threshold


def dataset_spec(basename):
    """Return dataset-specific column names and features.

    Args:
        basename: Filename of the dataset (without directory).

    Returns:
        Tuple (time_col, label_col, feature_cols).
    """
    if basename == "financial_transactions_dataset.csv":
        time_col = "timestamp"
        label_col = "is_fraud"
        feature_cols = [
            "card_client_id",
            "card_id",
            "amount",
            "use_chip",
            "merchant_id",
            "card_brand",
            "card_type",
            "num_cards_issued",
            "credit_limit",
            "total_debt",
            "credit_score",
            "num_credit_cards",
            "timestamp",
        ]
    elif basename == "synthetic_financial_datasets_paysim.csv":
        time_col = "step"
        label_col = "isFraud"
        feature_cols = [
            "step",
            "type",
            "amount",
            "oldbalanceOrg",
            "newbalanceOrig",
            "oldbalanceDest",
            "newbalanceDest",
            "diffOrg",
            "diffDest",
        ]
    elif basename in ("fraudulent_e-commerce_transactions.csv"):
        time_col = "transaction_date"
        label_col = "is_fraudulent"
        feature_cols = [
            "transaction_id",
            "customer_id",
            "transaction_amount",
            "transaction_date",
            "payment_method",
            "product_category",
            "quantity",
            "customer_age",
            "customer_location",
            "device_used",
            "ip_address",
            "shipping_address",
            "billing_address",
            "account_age_days",
            "transaction_hour",
        ]
    else:
        time_col = "Time"
        label_col = "Class"
        feature_cols = [f"V{i+1}" for i in range(28)] + ["Amount"]
    return time_col, label_col, feature_cols


class StreamingLabelEncoder:
    """Simple streaming label encoder for categorical features.

    Assigns incremental numeric IDs to unseen categorical values per feature.
    """
    def __init__(self):
        self.mapping = {}
        self.counter = 0

    def encode(self, value):
        """Encode a categorical value into a float ID.

        Args:
            value: The categorical value to encode.

        Returns:
            Float representation of the assigned numeric ID.
        """
        if value not in self.mapping:
            self.mapping[value] = self.counter
            self.counter += 1
        return float(self.mapping[value])


LABEL_ENCODERS = defaultdict(StreamingLabelEncoder)


def to_feature_dict(row, feature_cols):
    """Convert a dataframe row to a feature dictionary for River models.

    Attempts to parse numeric values; falls back to streaming label encoding for
    categorical fields. NaN/Inf numeric values are replaced by 0.0.

    Args:
        row: A pandas Series representing one record.
        feature_cols: List of feature column names to extract.

    Returns:
        Dict[str, float] suitable for River ``learn_one``/``predict_*`` methods.
    """
    d = {}
    for c in feature_cols:
        val = row[c]

        # Case 1: Try numeric
        try:
            v = float(val)
            if np.isnan(v) or np.isinf(v):
                v = 0.0
            d[c] = v
            continue
        except Exception:
            pass  # not numeric → treat as category

        # Case 2: Categorical value (string/object)
        try:
            d[c] = LABEL_ENCODERS[c].encode(str(val))
        except Exception:
            pass
    return d


def build_stacking_pipeline():
    """Create a stacking pipeline with ARF and logistic regression base models.

    Returns:
        A River ``Pipeline`` combining ``StandardScaler`` and ``StackingClassifier``
        with Logistic Regression meta-classifier.
    """
    arf = forest.ARFClassifier(seed=42, n_models=10)
    lr1 = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))
    lr2 = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))
    meta = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))
    base_models = [arf, lr1, lr2]
    stacking = compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.StackingClassifier(models=base_models, meta_classifier=meta, include_features=True),
    )
    return stacking


def build_basic_logistic():
    """Create a basic standardized logistic regression pipeline.

    Returns:
        River ``Pipeline`` with ``StandardScaler`` and ``LogisticRegression``.
    """
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LogisticRegression(optimizer=optim.SGD(0.01)),
    )


def load_model_if_exists(path: Path):
    """Load a pickled model if the path exists.

    Args:
        path: Filesystem path to the saved model.

    Returns:
        The loaded model instance or ``None`` if unavailable or failed.
    """
    if path.exists():
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            logger.debug("Failed to load model %s", path, exc_info=True)
    return None


def save_model(path: Path, model):
    """Persist a model to disk via pickle.

    Args:
        path: Destination path.
        model: The model object to pickle.
    """
    try:
        with open(path, 'wb') as f:
            pickle.dump(model, f)
    except Exception:
        logger.exception("Failed to save model %s", path)


def safe_learn_one(model, x, y):
    """Safely call ``learn_one`` supporting both supervised and unsupervised APIs.

    Args:
        model: River model.
        x: Feature mapping for a single sample.
        y: Label for supervised update.
    """
    try:
        model.learn_one(x, y)
    except TypeError:
        try:
            model.learn_one(x)
        except Exception:
            logger.debug("safe_learn_one final fallback failed", exc_info=True)


def process_model_on_dataset(df, dataset_path, model_name, model_builder):
    """Process a dataset with a given model builder in streaming fashion.

    Handles sorting by time column, building/loading the model, adaptive
    thresholding, periodic reports, and returns a final metrics summary.

    Args:
        df: Loaded pandas dataframe.
        dataset_path: Path to the dataset file.
        model_name: Identifier for the model (used for logging and saving).
        model_builder: Callable that returns a River model/pipeline.

    Returns:
        Dict containing final metric values and counts (F1, Recall, ROC, etc.).
    """
    basename = os.path.basename(dataset_path)
    time_col, label_col, feature_cols = dataset_spec(basename)
    logger.info("Processing dataset=%s model=%s | time_col=%s label=%s", basename, model_name, time_col, label_col)
    if (time_col in df.columns):
        try:
            df = df.sort_values(time_col).reset_index(drop=True)
        except Exception as e:
            logger.warning("Could not sort by %s: %s", time_col, e)
            df = df.reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)
    model_save_path = MODEL_SAVE_DIR / f"{basename}.{model_name}.pkl"
    model = load_model_if_exists(model_save_path)
    if model is None:
        model = model_builder()
    dyn_thresh = DynamicThresholdWrapper()
    f1 = metrics.F1()
    recall = metrics.Recall()
    auc = metrics.ROCAUC()
    precision = metrics.Precision()
    tp = fp = tn = fn = 0
    class_totals = defaultdict(int)
    class_correct = defaultdict(int)
    y_true_list = []
    y_pred_list = []
    scores_list = []
    updates = 0
    for idx, (_, row) in enumerate(tqdm(df.iterrows(), total=len(df), desc=f"{model_name} on {basename}")):
        x = to_feature_dict(row, feature_cols)
        try:
            y = int(row[label_col])
        except Exception:
            continue
        try:
            p = model.predict_proba_one(x)
            if isinstance(p, dict):
                score = float(p.get(1, p.get(True, 0.0)))
            else:
                score = float(p)
        except Exception:
            try:
                pred_aux = model.predict_one(x)
                score = 1.0 if pred_aux else 0.0
            except Exception:
                score = 0.0
        adaptive_thresh = dyn_thresh.get_threshold()
        y_hat = 1 if score >= adaptive_thresh else 0
        class_totals[y] += 1
        if y == y_hat:
            class_correct[y] += 1
        dyn_thresh.update(score, y)
        f1.update(y, y_hat)
        recall.update(y, y_hat)
        auc.update(y, score)
        precision.update(y, y_hat)
        if y == 1 and y_hat == 1:
            tp += 1
        elif y == 0 and y_hat == 1:
            fp += 1
        elif y == 0 and y_hat == 0:
            tn += 1
        elif y == 1 and y_hat == 0:
            fn += 1
        if y_hat != y:
            safe_learn_one(model, x, y)
            updates += 1
        y_true_list.append(y)
        y_pred_list.append(y_hat)
        scores_list.append(score)
        if (idx + 1) % LOG_EVERY == 0:
            logger.info("[%s - %s] processed %d samples", basename, model_name, idx + 1)
            try:
                if len(y_true_list) > 0:
                    print(f"--- Interval report after {idx+1} samples for dataset={basename} model={model_name} ---")
                    print(classification_report(y_true_list, y_pred_list, digits=4, zero_division=0))
                    print("Confusion matrix:", confusion_matrix(y_true_list, y_pred_list))
                    per_class_accuracy = {}
                    for cls, tot in class_totals.items():
                        acc = class_correct.get(cls, 0) / tot if tot > 0 else 0.0
                        per_class_accuracy[cls] = acc
                    print("Per-class accuracy:", per_class_accuracy)
            except Exception:
                logger.exception("Failed to print interval sklearn report: %s", traceback.format_exc())
    save_model(model_save_path, model)
    report = {
        "F1": f1.get(),
        "Recall": recall.get(),
        "ROC": auc.get(),
        "Precision": precision.get(),
        "ConfusionMatrix": {"TP": tp, "FP": fp, "TN": tn, "FN": fn},
        "PerClassAccuracy": {
            cls: (class_correct.get(cls, 0) / class_totals[cls]) if class_totals[cls] > 0 else 0.0 for cls in class_totals
        },
        "Updates": updates
    }
    print(f"RESULTS for dataset={basename} model={model_name}")
    if len(y_true_list) > 0:
        print(classification_report(y_true_list, y_pred_list, digits=4, zero_division=0))
        print("Confusion matrix:", confusion_matrix(y_true_list, y_pred_list))
        print("Per-class accuracy:", report["PerClassAccuracy"])
        print("Total conditional updates:", report["Updates"])
    else:
        print("No predictions collected.")
    return report


def main():
    """Entry point to run streaming evaluations over configured datasets.

    Loads datasets if present, builds models, and processes each to print
    interval and final reports.
    """
    models = {
        "stacking": build_stacking_pipeline,
        "basic_logistic": build_basic_logistic,
    }
    for path in DATASETS:
        if not os.path.exists(path):
            logger.warning("Skipping missing dataset: %s", path)
            continue
        try:
            logger.info("Loading dataset: %s", path)
            df = pd.read_csv(path)
            logger.info("Loaded rows=%d cols=%d", df.shape[0], df.shape[1])
            for model_name, builder in models.items():
                process_model_on_dataset(df, path, model_name, builder)
        except Exception:
            logger.exception("Fatal error processing %s:%s", path, traceback.format_exc())


if __name__ == "__main__":
    main()
