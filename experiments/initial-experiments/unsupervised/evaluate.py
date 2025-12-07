import os
import json
import pandas as pd
import numpy as np
from tqdm import tqdm
from river import anomaly, metrics, preprocessing
from sklearn.metrics import classification_report, precision_recall_fscore_support


def _preprocess(df: pd.DataFrame, target_col: str):
    df = df.copy()
    df = df.dropna(subset=[target_col])
    y = df[target_col]
    X = df.drop(columns=[target_col])

    # Encode categorical columns
    obj_cols = [c for c in X.columns if X[c].dtype ==
                'object' or str(X[c].dtype).startswith('category')]
    for c in obj_cols:
        X[c] = X[c].fillna('__NA__').astype(str)
        X[c], _ = pd.factorize(X[c], sort=True)

    # Fill numeric/non-numeric NaNs
    for c in X.columns:
        if X[c].dtype.kind in 'biufc':
            X[c] = X[c].fillna(X[c].median())
        else:
            X[c] = X[c].fillna(-1)

    return X, y


def _per_class_accuracies(y_true, y_pred):
    cm = np.zeros((2, 2), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[int(t)][int(p)] += 1
    per_class = {}
    for i in range(2):
        total = cm[i].sum()
        correct = cm[i, i]
        per_class[i] = float(correct) / total if total > 0 else None
    return cm, per_class


def run_all_models(csv_path: str, target_col: str, log_dir: str, test_size: float = 0.2, random_state: int = 42):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'uns.log')

    print(f"\nLoading dataset: {csv_path}")
    df = pd.read_csv(csv_path)
    print(
        f"Dataset loaded with {len(df):,} rows and {len(df.columns)} columns")

    X, y = _preprocess(df, target_col)
    X = X.to_dict(orient='records')
    y = y.values

    scaler = preprocessing.MinMaxScaler()

    models = {
        'GaussianScorer': anomaly.GaussianScorer(),
        'HalfSpaceTrees': anomaly.HalfSpaceTrees(seed=random_state),
        'OneClassSVM': anomaly.OneClassSVM()
    }

    results = {}

    for name, model in models.items():
        print(f"\nRunning {name}...")
        scores, preds, trues = [], [], []
        auc = metrics.ROCAUC()

        for xi, yi in tqdm(zip(X, y), total=len(y), desc=f"{name} training", miniters=10000):
            scaler.learn_one(xi)
            xi_scaled = scaler.transform_one(xi)

            if name == "GaussianScorer":
                if "amount" in xi_scaled:
                    y_val = xi_scaled["amount"]
                elif "logamount" in xi_scaled:
                    y_val = xi_scaled["logamount"]
                else:
                    y_val = list(xi_scaled.values())[0]

                score = model.score_one(xi_scaled, y_val)
                model.learn_one(xi_scaled, y_val)
            else:
                score = model.score_one(xi_scaled)
                model.learn_one(xi_scaled)

            pred = 1 if score > 0.5 else 0
            scores.append(score)
            preds.append(pred)
            trues.append(yi)
            auc.update(yi, score)

        cm, per_class = _per_class_accuracies(trues, preds)
        acc = np.mean(np.array(trues) == np.array(preds))

        # Generate classification report
        class_report = classification_report(
            trues, preds,
            target_names=['Class 0', 'Class 1'],
            output_dict=True,
            zero_division=0
        )
        class_report_str = classification_report(
            trues,
            preds,
            target_names=['Class 0', 'Class 1'],
            zero_division=0
        )

        # Calculate precision, recall, f1 for each class
        precision, recall, f1, support = precision_recall_fscore_support(
            trues, preds, average=None, zero_division=0
        )

        report = {
            'model_name': name,
            'overall_accuracy': float(acc),
            'per_class_accuracies': per_class,
            'confusion_matrix': cm.tolist(),
            'roc_auc': auc.get(),
            'precision': precision.tolist(),
            'recall': recall.tolist(),
            'f1_score': f1.tolist(),
            'support': support.tolist(),
            'classification_report': class_report
        }
        results[name] = report

        # Print classification report to console
        print(f"\n{name} Classification Report:")
        print(class_report_str)
        print(f"ROC-AUC: {auc.get():.4f}")
        print(f"Overall Accuracy: {acc:.4f}")

        # Write to log file
        with open(log_file, 'a') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"=== {name} ===\n")
            f.write(f"{'='*60}\n\n")
            f.write("Classification Report:\n")
            f.write(class_report_str)
            f.write(f"\n\nROC-AUC: {auc.get():.4f}\n")
            f.write(f"Overall Accuracy: {acc:.4f}\n\n")
            f.write("Full Report (JSON):\n")
            f.write(json.dumps(report, indent=2))
            f.write("\n\n")

        print(f"{name} results logged in uns.log")

    summary_path = os.path.join(log_dir, 'summary.json')
    with open(summary_path, 'w') as sf:
        json.dump(results, sf, indent=2)

    print(f"\nAll models complete. Summary written to {summary_path}")
    return results
