import numpy as np
import pandas as pd
import sys
import os
from tqdm.auto import tqdm
import logging
from imblearn.under_sampling import RandomUnderSampler
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix

from sklearn.linear_model import SGDClassifier, PassiveAggressiveClassifier
from sklearn.neural_network import MLPClassifier

LOG_LINES_SK = 200000

#add the dataset files in the same folder as this file
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


def build_and_init_models(X_train, y_train):
    classes = np.array([0, 1])
    sgd = SGDClassifier(loss="log_loss", max_iter=1, learning_rate="optimal", random_state=42)
    pa = PassiveAggressiveClassifier(random_state=42, max_iter=1)
    mlp = MLPClassifier(hidden_layer_sizes=(100,), max_iter=1, warm_start=False, random_state=42)
    try:
        sgd.partial_fit(X_train, y_train, classes=classes)
    except TypeError:
        sgd.partial_fit(X_train, y_train)
    try:
        pa.partial_fit(X_train, y_train, classes=classes)
    except TypeError:
        pa.partial_fit(X_train, y_train)
    try:
        mlp.partial_fit(X_train, y_train, classes=classes)
    except TypeError:
        mlp.partial_fit(X_train, y_train)
    base_models = {"sgd": sgd, "pa": pa, "mlp": mlp}
    return base_models


def init_stacking_meta(base_models, X_train, y_train):
    classes = np.array([0, 1])
    meta = SGDClassifier(loss="log_loss", max_iter=1, learning_rate="optimal", random_state=42)
    meta_initialized = False
    for i in range(X_train.shape[0]):
        x_vec = X_train[i].reshape(1, -1)
        preds = []
        for m in ("sgd", "pa", "mlp"):
            try:
                preds.append(int(base_models[m].predict(x_vec)[0]))
            except Exception:
                preds.append(0)
        meta_x = np.array(preds).reshape(1, -1)
        y_i = int(y_train[i])
        if not meta_initialized:
            try:
                meta.partial_fit(meta_x, [y_i], classes=classes)
            except TypeError:
                meta.partial_fit(meta_x, [y_i])
            meta_initialized = True
        else:
            try:
                meta.partial_fit(meta_x, [y_i])
            except TypeError:
                meta.partial_fit(meta_x, [y_i])
    return meta


def voting_predict(base_models, x_vec):
    votes = []
    for m in ("sgd", "pa", "mlp"):
        try:
            votes.append(int(base_models[m].predict(x_vec)[0]))
        except Exception:
            votes.append(0)
    s = sum(votes)
    return 1 if (s / len(votes)) >= 0.5 else 0


def stacking_predict(base_models, meta, x_vec):
    preds = []
    for m in ("sgd", "pa", "mlp"):
        try:
            preds.append(int(base_models[m].predict(x_vec)[0]))
        except Exception:
            preds.append(0)
    meta_x = np.array(preds).reshape(1, -1)
    try:
        return int(meta.predict(meta_x)[0])
    except Exception:
        s = sum(preds)
        return 1 if (s / len(preds)) >= 0.5 else 0


def stream_evaluate_ensembles(base_models, meta, X_test, y_test, basename):
    y_true_list_v = []
    y_pred_list_v = []
    y_true_list_s = []
    y_pred_list_s = []
    classes = np.array([0, 1])
    for idx in tqdm(range(X_test.shape[0]), desc=f"ensembles on {basename}"):
        x_vec = X_test[idx].reshape(1, -1)
        y_true = int(y_test[idx])
        y_hat_v = voting_predict(base_models, x_vec)
        y_hat_s = stacking_predict(base_models, meta, x_vec)
        y_true_list_v.append(y_true)
        y_pred_list_v.append(y_hat_v)
        y_true_list_s.append(y_true)
        y_pred_list_s.append(y_hat_s)
        if y_hat_v != y_true:
            for m in base_models.values():
                if hasattr(m, "partial_fit"):
                    try:
                        m.partial_fit(x_vec, [y_true], classes=classes)
                    except TypeError:
                        m.partial_fit(x_vec, [y_true])
        if y_hat_s != y_true:
            preds_for_meta = []
            for m in ("sgd", "pa", "mlp"):
                try:
                    preds_for_meta.append(int(base_models[m].predict(x_vec)[0]))
                except Exception:
                    preds_for_meta.append(0)
            meta_x = np.array(preds_for_meta).reshape(1, -1)
            try:
                meta.partial_fit(meta_x, [y_true], classes=classes)
            except TypeError:
                meta.partial_fit(meta_x, [y_true])
        if (idx + 1) % LOG_LINES_SK == 0:
            prefix_v = f"[voting | {basename} | seen={idx+1}]"
            _log_sklearn_reports(prefix_v, y_true_list_v, y_pred_list_v)
            prefix_s = f"[stacking | {basename} | seen={idx+1}]"
            _log_sklearn_reports(prefix_s, y_true_list_s, y_pred_list_s)
    prefix_v = f"[voting | {basename} | final]"
    _log_sklearn_reports(prefix_v, y_true_list_v, y_pred_list_v)
    prefix_s = f"[stacking | {basename} | final]"
    _log_sklearn_reports(prefix_s, y_true_list_s, y_pred_list_s)


def run_ensembles_on_df(df, dataset_name):
    basename, X_train, y_train, X_test, y_test = prepare_data_for_dataset(df, dataset_name)
    base_models = build_and_init_models(X_train, y_train)
    meta = init_stacking_meta(base_models, X_train, y_train)
    stream_evaluate_ensembles(base_models, meta, X_test, y_test, basename)


if __name__ == "__main__":
    for path in DATASETS:
        if not os.path.exists(path):
            logger.warning("Skipping missing dataset: %s", path)
            continue
        df = pd.read_csv(path)
        run_ensembles_on_df(df, path)
