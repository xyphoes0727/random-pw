"""
CLI runner for the evaluator module.

Example:
    python run_eval.py --csv ../data/fraud.csv --target Class --log_dir ./logs
"""

import argparse
import os
import json

from evaluator import run_all_models


def main():
    parser = argparse.ArgumentParser(
        description="Run multiple models on a CSV file and log outputs."
    )
    parser.add_argument("--csv", required=True,
                        help="Path to the input CSV file.")
    parser.add_argument("--target", required=True, help="Target column name.")
    parser.add_argument(
        "--log_dir",
        default="./logs",
        help="Directory where model logs will be saved.",
    )
    parser.add_argument(
        "--test_size",
        type=float,
        default=0.2,
        help="Fraction of data used for the test split.",
    )
    parser.add_argument(
        "--random_state",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    os.makedirs(args.log_dir, exist_ok=True)
    print(f"Starting model evaluation:")
    print(f"  Input file: {csv_path}")
    print(f"  Target column: {args.target}")
    print(f"  Logs directory: {args.log_dir}")

    results = run_all_models(
        csv_path,
        args.target,
        args.log_dir,
        test_size=args.test_size,
        random_state=args.random_state,
    )

    summary_path = os.path.join(args.log_dir, "summary.json")
    with open(summary_path, "w") as sf:
        json.dump(results, sf, indent=2)

    print(f"\nEvaluation completed. Summary written to {summary_path}")


if __name__ == "__main__":
    main()
