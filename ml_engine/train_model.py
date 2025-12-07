import os
import sys
import traceback
import logging
import pickle
from pathlib import Path
from collections import deque, defaultdict

import numpy as np
import pandas as pd
from tqdm.auto import tqdm
from sklearn.metrics import classification_report, confusion_matrix

from river import ensemble, preprocessing, linear_model, compose, optim, metrics, forest

# ----------------- CONFIG ----------------- #

DATASET_PATH = ""
MODEL_SAVE_DIR = Path("./savedModels")
MODEL_SAVE_DIR.mkdir(parents=True, exist_ok=True)
MODEL_FILENAME = "ARF_Ensemble_50k.pkl"
MAX_TRAIN_SAMPLES = 50000
LOG_EVERY = 50000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# ----------------- SUPPORT CLASSES / FUNCS ----------------- #


class DynamicThresholdWrapper:
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
        save_path='./last_10k_data_50k.pkl',
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
                    pickle.dump({
                        'y_probas': list(self.y_probas),
                        'y_true': list(self.y_labels)
                    }, f)
            except Exception:
                logger.debug(
                    "Failed to save last 10k dynamic threshold data", exc_info=True)

        if self.samples_seen - self.last_percentile_update >= self.percentile_update_interval:
            self.cached_percentile_threshold = self._compute_weighted_percentile()
            self.last_percentile_update = self.samples_seen

        if self.samples_seen < self.grace_period:
            self.ema_threshold = 0.5
        else:
            self.ema_threshold = (
                self.ema_alpha * self.cached_percentile_threshold +
                (1 - self.ema_alpha) * self.ema_threshold
            )
            self.ema_threshold = np.clip(
                self.ema_threshold, self.min_threshold, self.max_threshold)

        return self.ema_threshold

    def _compute_weighted_percentile(self):
        weighted = []
        total_weight = 0

        if self.fraud_scores:
            fraud_arr = np.array(self.fraud_scores)
            fraud_p = np.percentile(fraud_arr, self.percentile)
            weighted.append(fraud_p * self.fraud_weight)
            total_weight += self.fraud_weight

        if self.nonfraud_scores:
            nonfraud_arr = np.array(self.nonfraud_scores)
            nonfraud_p = np.percentile(nonfraud_arr, self.percentile)
            weighted.append(nonfraud_p * self.nonfraud_weight)
            total_weight += self.nonfraud_weight

        if not weighted:
            if self.recent_scores:
                return np.percentile(np.array(self.recent_scores), self.percentile)
            return 0.5

        return sum(weighted) / total_weight

    def get_threshold(self):
        return self.ema_threshold


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

FEATURE_COLS = [
    "type", "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
    "mean_amount", "stddev_amount", "max_amount_seen", "min_amount_seen",
    "user_txn_count", "txn_count_in_step", "total_amount_in_step",
    "sender_out_degree", "sender_in_degree", "sender_fraud_ratio", "pagerank",
    "amount_to_profile_ratio", "amount_to_balance_ratio",
    "logamount", "origMoreSent", "destMoreRec", "origMoreSentFlag", "destMoreRecFlag"
]


def to_feature_dict(row, cols):
    d = {}
    for c in cols:
        val = row[c]
        try:
            v = float(val)
            if np.isnan(v) or np.isinf(v):
                v = 0.0
            d[c] = v
            continue
        except Exception:
            pass

        try:
            d[c] = label_encoders[c].encode(str(val))
        except Exception:
            pass

    return d


def build_stacking_pipeline():
    arf = forest.ARFClassifier(seed=42, n_models=10)
    lr1 = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))
    lr2 = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))
    meta = linear_model.LogisticRegression(optimizer=optim.SGD(0.01))

    stacking = compose.Pipeline(
        preprocessing.StandardScaler(),
        ensemble.StackingClassifier(
            models=[arf, lr1, lr2],
            meta_classifier=meta,
            include_features=True
        ),
    )
    return stacking


def save_model(model):
    path = MODEL_SAVE_DIR / MODEL_FILENAME
    with open(path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Saved 50k model → %s", path)
    return path


def load_dataset(path):
    logger.info("Loading dataset: %s", path)
    df = pd.read_csv(path)
    logger.info("Loaded rows=%d cols=%d", df.shape[0], df.shape[1])
    return df


def dataset_spec_for_paysim():
    return "step", "isFraud", FEATURE_COLS


# ----------------- MAIN TRAIN LOOP ----------------- #

def train_50k():
    df = load_dataset(DATASET_PATH)
    basename = os.path.basename(DATASET_PATH)

    time_col, label_col, feature_cols = dataset_spec_for_paysim()

    if time_col in df.columns:
        try:
            df = df.sort_values(time_col).reset_index(drop=True)
        except Exception as e:
            logger.warning("Could not sort by %s: %s", time_col, e)
            df = df.reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    model = build_stacking_pipeline()
    dyn_thresh = DynamicThresholdWrapper()

    f1 = metrics.F1()
    recall = metrics.Recall()
    auc = metrics.ROCAUC()
    precision = metrics.Precision()

    tp = fp = tn = fn = 0
    class_totals = defaultdict(int)
    class_correct = defaultdict(int)

    y_true_list, y_pred_list = [], []

    iterator = tqdm(
        df.iterrows(),
        total=min(len(df), MAX_TRAIN_SAMPLES),
        desc=f"Training ARF_Ensemble 50k on {basename}",
    )

    for idx, (_, row) in enumerate(iterator):
        if idx >= MAX_TRAIN_SAMPLES:
            break

        try:
            y = int(row[label_col])
        except Exception:
            continue

        x = to_feature_dict(row, feature_cols)

        try:
            p = model.predict_proba_one(x)
            score = float(p.get(1, p.get(True, 0.0))) if isinstance(
                p, dict) else float(p)
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

        y_b = bool(y)
        dyn_thresh.update(score, y)
        f1.update(y_b, y_hat)
        recall.update(y_b, y_hat)
        auc.update(y_b, score)
        precision.update(y_b, y_hat)

        if y == 1 and y_hat == 1:
            tp += 1
        elif y == 0 and y_hat == 1:
            fp += 1
        elif y == 0 and y_hat == 0:
            tn += 1
        elif y == 1 and y_hat == 0:
            fn += 1

        if y_hat != y:
            try:
                model.learn_one(x, y)
            except TypeError:
                try:
                    model.learn_one(x)
                except Exception:
                    logger.debug(
                        "safe_learn_one fallback failed", exc_info=True)

        y_true_list.append(y)
        y_pred_list.append(y_hat)

        if (idx + 1) % LOG_EVERY == 0:
            logger.info(
                "[%s - 50k] %d samples | F1=%.4f Recall=%.4f Precision=%.4f ROC=%.4f TP=%d FP=%d TN=%d FN=%d",
                basename, idx + 1,
                f1.get(), recall.get(), precision.get(), auc.get(),
                tp, fp, tn, fn
            )

    print("\n=== FINAL RESULTS ===")
    if len(y_true_list) > 0:
        print(classification_report(y_true_list,
              y_pred_list, digits=4, zero_division=0))
        print("Confusion matrix:\n", confusion_matrix(y_true_list, y_pred_list))
        print("Per-class accuracy:", {
            cls: (class_correct.get(cls, 0) / class_totals[cls])
            for cls in class_totals
        })

    save_model(model)


def main():
    try:
        train_50k()
    except Exception:
        logger.exception("Fatal error in 50k training: %s",
                         traceback.format_exc())


if __name__ == "__main__":
    main()
