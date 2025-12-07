"""
Evaluator module: trains multiple models on a CSV and writes
model outputs to log files.

Usage:
    Import and call `run_all_models(...)` from the `run_eval.py` CLI.

Included models:
- LogisticRegression
- XGBoost (XGBClassifier)
- CatBoost (CatBoostClassifier)
- RandomForestClassifier
- IsolationForest (for anomaly detection)
- GaussianNB (Naive Bayes)

Metrics written to logs:
- sklearn classification_report
- Per-class accuracies
(accuracy for each class, equivalent to class-wise recall)
- Overall accuracy
- Confusion matrix
- ROC AUC (if applicable)
"""

from typing import Optional, Tuple
import os
import json
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.naive_bayes import GaussianNB
from sklearn.metrics import (
    classification_report,
    accuracy_score,
    confusion_matrix,
    roc_auc_score,
)

# Optional imports
try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

try:
    from catboost import CatBoostClassifier
except Exception:
    CatBoostClassifier = None

# Optional tqdm (fallback to identity function)
try:
    from tqdm import tqdm
except Exception:
    def tqdm(x, **kwargs):
        return x


def _preprocess(df: pd.DataFrame, target_col: str) -> Tuple[pd.DataFrame,
                                                            pd.Series]:
    """
    Preprocess a dataframe by:
    - Dropping rows with missing targets
    - Removing all-NA and constant-value columns
    - Filling numeric missing values with median
    - Filling non-numeric missing values with a sentinel ('__NA__')

    Returns:
        (X, y): cleaned feature matrix and target vector.
    """
    df = df.copy()
    df = df.dropna(subset=[target_col])
    y = df[target_col]
    X = df.drop(columns=[target_col], axis=1)

    X = X.loc[:, X.notna().any(axis=0)]  # remove all-NA columns
    nunique = X.nunique(dropna=True)
    for c in nunique[nunique <= 1].index:
        X = X.drop(columns=[c])

    for c in X.columns:
        if X[c].dtype.kind in "biufc":
            X[c] = X[c].fillna(X[c].median())
        else:
            X[c] = X[c].fillna("__NA__")

    return X, y


def _write_log(path: str, text: str) -> None:
    """Append log text to a file, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(text)
        f.write("\n")


def _per_class_accuracies(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """
    Compute per-class accuracies (recall for each class).
    Returns a dictionary mapping class labels to accuracy values.
    """
    cm = confusion_matrix(y_true, y_pred)
    per_class = {}
    classes = np.unique(np.concatenate([y_true, y_pred]))
    for idx, cls in enumerate(classes):
        total = cm[idx].sum()
        correct = cm[idx, idx]
        per_class[int(cls)] = float(correct) / \
            int(total) if total > 0 else None
    return per_class


def evaluate_supervised_model(
    model,
    X_train,
    X_test,
    y_train,
    y_test,
    log_file: str,
    model_name: str,
    extra_info: Optional[dict] = None,
):
    """Train and evaluate a supervised model, writing results to log."""
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    proba = None
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X_test)[:, 1]
        elif hasattr(model, "decision_function"):
            proba = model.decision_function(X_test)
    except Exception:
        proba = None

    report = classification_report(y_test, y_pred, digits=4)
    overall_acc = accuracy_score(y_test, y_pred)
    per_class = _per_class_accuracies(np.array(y_test), np.array(y_pred))
    cm = confusion_matrix(y_test, y_pred)

    lines = [
        f"Model: {model_name}",
    ]
    if extra_info:
        lines.append("Model info: " + json.dumps(extra_info))

    lines.append("--- Classification Report ---")
    lines.append(report)
    lines.append(f"Overall accuracy: {overall_acc:.6f}")
    lines.append("Per-class accuracies (accuracy for each true class):")
    lines.append(json.dumps(per_class))
    lines.append("Confusion matrix (rows=true, cols=pred):")
    lines.append(np.array2string(cm))

    if proba is not None:
        try:
            auc = roc_auc_score(y_test, proba)
            lines.append(f"ROC AUC: {auc:.6f}")
        except Exception:
            pass

    _write_log(log_file, "\n".join(lines))

    return {
        "model_name": model_name,
        "classification_report": report,
        "overall_accuracy": overall_acc,
        "per_class_accuracies": per_class,
        "confusion_matrix": cm.tolist(),
    }


def evaluate_isolation_forest(
    X_train,
    X_test,
    y_train,
    y_test,
    log_file: str,
    model_name: str,
    extra_info: Optional[dict] = None,
):
    """
    Train an IsolationForest on normal (label=0) samples and evaluate.
    Predictions are mapped from {-1, 1} to {1, 0} for consistency.
    """
    X_train_normal = X_train[y_train == 0]
    iso = IsolationForest(random_state=42, n_estimators=50)
    iso.fit(X_train_normal)
    iso_pred = iso.predict(X_test)
    y_pred = np.where(iso_pred == -1, 1, 0)

    report = classification_report(y_test, y_pred, digits=4)
    overall_acc = accuracy_score(y_test, y_pred)
    per_class = _per_class_accuracies(np.array(y_test), np.array(y_pred))
    cm = confusion_matrix(y_test, y_pred)

    lines = [
        f"Model: {model_name}",
    ]
    if extra_info:
        lines.append("Model info: " + json.dumps(extra_info))
    lines.append("--- IsolationForest (trained on label=0 samples) ---")
    lines.append(report)
    lines.append(f"Overall accuracy: {overall_acc:.6f}")
    lines.append("Per-class accuracies (accuracy for each true class):")
    lines.append(json.dumps(per_class))
    lines.append("Confusion matrix (rows=true, cols=pred):")
    lines.append(np.array2string(cm))

    _write_log(log_file, "\n".join(lines))

    return {
        "model_name": model_name,
        "classification_report": report,
        "overall_accuracy": overall_acc,
        "per_class_accuracies": per_class,
        "confusion_matrix": cm.tolist(),
    }


def run_all_models(
    csv_path: str,
    target_col: str,
    log_dir: str,
    test_size: float = 0.2,
    random_state: int = 42,
) -> dict:
    """
    Train and evaluate all supported models on the provided dataset.

    Args:
        csv_path: Path to the CSV file.
        target_col: Name of the target column.
        log_dir: Directory where logs are written.
        test_size: Fraction of data used for testing.
        random_state: Seed for reproducibility.

    Returns:
        Dictionary mapping model names to evaluation summaries.
    """
    df = pd.read_csv(csv_path)
    X, y = _preprocess(df, target_col)

    if y.dtype == "object" or str(y.dtype).startswith("category"):
        y = y.astype(str)
        uniq = sorted(y.unique())
        mapping = {v: i for i, v in enumerate(uniq)}
        y = y.map(mapping)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    os.makedirs(log_dir, exist_ok=True)
    results = {}

    lr = LogisticRegression(max_iter=200)
    rf = RandomForestClassifier(n_estimators=50, random_state=random_state)
    nb = GaussianNB()

    lr_log = os.path.join(log_dir, "logistic_regression.log")
    rf_log = os.path.join(log_dir, "random_forest.log")
    nb_log = os.path.join(log_dir, "naive_bayes.log")

    if XGBClassifier is not None:
        xgb = XGBClassifier(
            use_label_encoder=False, eval_metric="logloss",
            n_estimators=50, random_state=random_state
        )
        xgb_log = os.path.join(log_dir, "xgboost.log")
    else:
        xgb = None
        xgb_log = os.path.join(log_dir, "xgboost.log")

    if CatBoostClassifier is not None:
        cat = CatBoostClassifier(verbose=0, random_seed=random_state)
        cat_log = os.path.join(log_dir, "catboost.log")
    else:
        cat = None
        cat_log = os.path.join(log_dir, "catboost.log")

    iso_log = os.path.join(log_dir, "isolation_forest.log")

    def _job_supervised(key, model, Xtr, Xte, logpath, name):
        def _inner():
            return key, evaluate_supervised_model(
                model, Xtr, Xte, y_train, y_test, logpath, name)
        return _inner

    def _job_isolation():
        return "isolation_forest", evaluate_isolation_forest(
            X_train, X_test, y_train, y_test, iso_log, "IsolationForest"
        )

    jobs = [
        _job_supervised("logistic_regression", lr, X_train_scaled,
                        X_test_scaled, lr_log, "LogisticRegression"),
        _job_supervised("random_forest", rf, X_train,
                        X_test, rf_log, "RandomForest"),
        _job_supervised("naive_bayes", nb, X_train,
                        X_test, nb_log, "GaussianNB"),
    ]

    if xgb is not None:
        jobs.append(_job_supervised("xgboost", xgb,
                    X_train, X_test, xgb_log, "XGBoost"))
    else:
        _write_log(xgb_log, "XGBoost not installed or import failed.")
        results["xgboost"] = {"error": "xgboost not installed"}

    if cat is not None:
        jobs.append(_job_supervised("catboost", cat,
                    X_train, X_test, cat_log, "CatBoost"))
    else:
        _write_log(cat_log, "CatBoost not installed or import failed.")
        results["catboost"] = {"error": "catboost not installed"}

    jobs.append(_job_isolation)

    for job in tqdm(jobs, desc="Running models"):
        try:
            key, res = job()
            results[key] = res
        except Exception as e:
            err_msg = f"Job failed: {str(e)}"
            try:
                logpath = {
                    "logistic_regression": lr_log,
                    "random_forest": rf_log,
                    "naive_bayes": nb_log,
                    "xgboost": xgb_log,
                    "catboost": cat_log,
                    "isolation_forest": iso_log,
                }.get(key, os.path.join(log_dir, f"{key}.log"))
            except Exception:
                logpath = os.path.join(
                    log_dir, f"{getattr(key, '__name__', str(key))}.log")

            _write_log(logpath, err_msg)
            results[key] = {"error": err_msg}

    return results
