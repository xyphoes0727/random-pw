import numpy as np
import pandas as pd
import sys
import os
from tqdm.auto import tqdm
import logging
from imblearn.under_sampling import RandomUnderSampler
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.linear_model import (
    SGDClassifier,
    PassiveAggressiveClassifier,
    SGDOneClassSVM
)
from sklearn.neural_network import MLPClassifier

LOG_LINES_SK = 200000

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
)
logger = logging.getLogger(__name__)


def _log_sklearn_reports(prefix, y_true, y_pred):
    if len(y_true) == 0:
        return
    cr = classification_report(y_true, y_pred, digits=4, zero_division=0)
    cm = confusion_matrix(y_true, y_pred)
    logger.info("%s\nclassification_report:\n%s", prefix, cr)
    logger.info("%s\nconfusion_matrix:\n%s", prefix, cm)


def prepare_data_for_dataset(df, dataset_name):
    basename = os.path.basename(dataset_name)
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
    elif basename == "credit_card.csv":
        time_col = "Time"
        label_col = "Class"
        feature_cols = [
            "Time",
            "V1",
            "V2",
            "V3",
            "V4",
            "V5",
            "V6",
            "V7",
            "V8",
            "V9",
            "V10",
            "V11",
            "V12",
            "V13",
            "V14",
            "V15",
            "V16",
            "V17",
            "V18",
            "V19",
            "V20",
            "V21",
            "V22",
            "V23",
            "V24",
            "V25",
            "V26",
            "V27",
            "V28",
            "Amount",
        ]
    else:
        raise ValueError(f"Unknown dataset structure for {basename}")
    df = df.sort_values(time_col).reset_index(drop=True)
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=[label_col])
    n = len(df)
    train_end = int(0.3 * n)
    df_train = df.iloc[:train_end].copy()
    df_test = df.iloc[train_end:].copy()
    X_train = df_train[feature_cols].values
    y_train = df_train[label_col].values.astype(int)
    rus = RandomUnderSampler(random_state=42)
    _ = rus.fit_resample(X_train, y_train)
    selected_idx = rus.sample_indices_
    df_train_res = df_train.iloc[selected_idx].copy()
    df_train_res = df_train_res.sort_values(time_col).reset_index(drop=True)
    X_train_res = df_train_res[feature_cols].values
    y_train_res = df_train_res[label_col].values.astype(int)
    X_test = df_test[feature_cols].values
    y_test = df_test[label_col].values.astype(int)
    scaler = StandardScaler()
    X_train_res = scaler.fit_transform(X_train_res)
    X_test = scaler.transform(X_test)
    return basename, X_train_res, y_train_res, X_test, y_test


def build_and_init_model(model_name, X_train, y_train):
    classes = np.array([0, 1])
    if model_name == "sgd":
        model = SGDClassifier(loss="log_loss", max_iter=1, learning_rate="optimal", random_state=42)
        try:
            model.partial_fit(X_train, y_train, classes=classes)
        except TypeError:
            model.partial_fit(X_train, y_train)
        return model
    elif model_name == "passive_aggressive":
        model = PassiveAggressiveClassifier(random_state=42, max_iter=1)
        try:
            model.partial_fit(X_train, y_train, classes=classes)
        except TypeError:
            model.partial_fit(X_train, y_train)
        return model
    elif model_name == "mlp":
        # remove warm_start to avoid the warm_start / class-mismatch issues
        model = MLPClassifier(hidden_layer_sizes=(100,), max_iter=1, warm_start=False, random_state=42)
        # make sure initial partial_fit includes classes
        try:
            model.partial_fit(X_train, y_train, classes=classes)
        except TypeError:
            model.partial_fit(X_train, y_train)
        return model
    elif model_name == "sgd_oneclass_svm":
        model = SGDOneClassSVM(nu=0.5, max_iter=1, random_state=42)
        mask_normal = y_train == 0
        X_normal = X_train[mask_normal]
        if X_normal.shape[0] == 0:
            X_normal = X_train
        try:
            model.partial_fit(X_normal)
        except TypeError:
            model.partial_fit(X_normal)
        return model
    else:
        raise ValueError(f"Unknown model_name {model_name}")


def stream_evaluate_model(model_name, model, X_test, y_test, basename):
    y_true_list = []
    y_pred_list = []
    classes = np.array([0, 1])
    for idx in tqdm(range(X_test.shape[0]), desc=f"{model_name} on {basename}"):
        x_vec = X_test[idx].reshape(1, -1)
        y_true = int(y_test[idx])
        if model_name == "sgd_oneclass_svm":
            try:
                y_raw = model.predict(x_vec)[0]
                y_hat = 0 if int(y_raw) == 1 else 1
            except Exception:
                y_hat = 0
        else:
            try:
                y_hat = int(model.predict(x_vec)[0])
            except Exception:
                y_hat = 0
        y_true_list.append(y_true)
        y_pred_list.append(y_hat)
        if model_name == "sgd_oneclass_svm":
            if y_hat != y_true and y_true == 0:
                try:
                    model.partial_fit(x_vec)
                except TypeError:
                    model.partial_fit(x_vec)
        else:
            if hasattr(model, "partial_fit"):
                if y_hat != y_true:
                    # ensure MLP always receives the `classes` argument on updates
                    if isinstance(model, MLPClassifier):
                        try:
                            model.partial_fit(x_vec, [y_true], classes=classes)
                        except TypeError:
                            model.partial_fit(x_vec, [y_true], classes=classes)
                    else:
                        try:
                            model.partial_fit(x_vec, [y_true], classes=classes)
                        except TypeError:
                            model.partial_fit(x_vec, [y_true])
        if (idx + 1) % LOG_LINES_SK == 0:
            prefix = f"[{model_name} | {basename} | seen={idx+1}]"
            _log_sklearn_reports(prefix, y_true_list, y_pred_list)
    prefix = f"[{model_name} | {basename} | final]"
    _log_sklearn_reports(prefix, y_true_list, y_pred_list)


def run_sklearn_models_on_df(df, dataset_name):
    basename, X_train, y_train, X_test, y_test = prepare_data_for_dataset(df, dataset_name)
    models_to_run = [
        "mlp",
        "passive_aggressive",
        "sgd_oneclass_svm",
        "sgd",
    ]
    for model_name in models_to_run:
        logger.info("Dataset: %s | sklearn model: %s", dataset_name, model_name)
        model = build_and_init_model(model_name, X_train, y_train)
        stream_evaluate_model(model_name, model, X_test, y_test, basename)


if __name__ == "__main__":
    for path in DATASETS:
        if not os.path.exists(path):
            logger.warning("Skipping missing dataset: %s", path)
            continue
        df = pd.read_csv(path)
        run_sklearn_models_on_df(df, path)
