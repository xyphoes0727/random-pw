"""
Strict rule-only evaluator.
Rules:
    - amtOrigError = abs(amount - (oldbalanceOrg - newbalanceOrig)), map 1.0->0.0
    - destBalError = abs(amount - (newbalanceDest - oldbalanceDest))
    - origMoreSent = (amtOrigError > 0.7 * amount)
    - destMoreRec  = (destBalError > 0.7 * amount)
    - trust_low    = (trust_score < 0.2)
    - rule_fraud   = any(trust_low, origMoreSent, destMoreRec)
"""

import os
import sys
import traceback
from pathlib import Path
import logging
import pandas as pd
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

# add the dataset files in the same folder as this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_PATH = [
    os.path.join(BASE_DIR, "synthetic_financial_dataset_paysim.csv"),
]
OUTPUT_DIR = Path("./rule_outputs_enriched_only")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def cleanOrigDiff(diff):
    if diff == 1.0:
        return 0.0
    else:
        return diff


def apply_exact_provided_rules_half_amount(df):
    df = df.copy()

    required = [
        "amount", "oldbalanceOrg", "newbalanceOrig",
        "newbalanceDest", "oldbalanceDest", "trust_score"
    ]
    for c in required:
        if c not in df.columns:
            df[c] = 0.0
    for c in required:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    origBalDiff = df["oldbalanceOrg"] - df["newbalanceOrig"]
    amtOrigDiff = (df["amount"] - origBalDiff).abs().map(cleanOrigDiff)
    destBalDiff = df["newbalanceDest"] - df["oldbalanceDest"]
    amtDestDiff = (df["amount"] - destBalDiff).abs()

    df["amtOrigError"] = amtOrigDiff
    df["destBalError"] = amtDestDiff

    df["origMoreSent"] = (df["amtOrigError"] > (df["amount"] * 0.7)).astype(int)
    df["destMoreRec"] = (df["destBalError"] > (df["amount"] * 0.7)).astype(int)

    df["trust_low"] = (df["trust_score"] < 0.2).astype(int)

    df["rule_fraud"] = ((df["trust_low"] == 1) | (df["origMoreSent"] == 1) | (df["destMoreRec"] == 1)).astype(int)

    def reason_for_row(r):
        reasons = []
        if int(r["trust_low"]):
            reasons.append("trust_score<0.2")
        if int(r["origMoreSent"]):
            reasons.append("origMoreSent")
        if int(r["destMoreRec"]):
            reasons.append("destMoreRec")
        return ",".join(reasons) if reasons else "none"

    df["rule_reason"] = df.apply(reason_for_row, axis=1)

    summary = {
        "total_rows": int(len(df)),
        "flagged_by_trust_low": int(df["trust_low"].sum()),
        "flagged_by_origMoreSent": int(df["origMoreSent"].sum()),
        "flagged_by_destMoreRec": int(df["destMoreRec"].sum()),
        "total_flagged_any_rule": int(df["rule_fraud"].sum()),
    }

    return df, summary


def main():
    path = DATASET_PATH
    if not os.path.exists(path):
        logger.error("Enriched dataset missing: %s", path)
        sys.exit(2)

    try:
        logger.info("Loading enriched dataset: %s", path)
        df = pd.read_csv(path)
        logger.info("Loaded rows=%d cols=%d", df.shape[0], df.shape[1])

        df_rules, summary = apply_exact_provided_rules_half_amount(df)

        print("Total rows:", summary["total_rows"])
        print("Flagged by trust_score<0.2:", summary["flagged_by_trust_low"])
        print("Flagged by origMoreSent (>0.7*amount):", summary["flagged_by_origMoreSent"])
        print("Flagged by destMoreRec (>0.7*amount):", summary["flagged_by_destMoreRec"])
        print("Total flagged (any rule):", summary["total_flagged_any_rule"])
        print("Flagged pct:", f"{summary['total_flagged_any_rule'] / summary['total_rows'] if summary['total_rows'] > 0 else 0.0:.6f}")

        if "isFraud" in df.columns:
            try:
                y_true = pd.to_numeric(df["isFraud"], errors="coerce").fillna(0).astype(int).values
                y_pred = df_rules["rule_fraud"].astype(int).values
                print("\nClassification report (rules vs isFraud):")
                print(classification_report(y_true, y_pred, digits=4, zero_division=0))
                print("Confusion matrix:")
                print(confusion_matrix(y_true, y_pred))
            except Exception:
                logger.exception("Failed to compute classification report: %s", traceback.format_exc())
        else:
            print("\nNo 'isFraud' ground truth column found in dataset.")

        out_cols = ["rule_fraud", "rule_reason", "amtOrigError", "destBalError", "origMoreSent", "destMoreRec", "trust_low"]
        if "transactionId" in df_rules.columns:
            out_cols = ["transactionId"] + out_cols
        else:
            df_rules.insert(0, "row_index_for_join", df_rules.index)

        out_path = OUTPUT_DIR / "merged_enriched_all2.rule_results.csv"
        df_rules[out_cols].to_csv(out_path, index=False)
        logger.info("Saved rule-only outputs to %s", out_path)
        print("Saved rule outputs to:", out_path)

    except Exception:
        logger.exception("Fatal error while processing enriched dataset: %s", traceback.format_exc())
        sys.exit(3)


if __name__ == "__main__":
    main()
