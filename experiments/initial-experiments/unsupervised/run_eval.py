"""
CLI runner for the evaluator.

Example:
python run_eval.py --csv ../data/fraud.csv --target_label Class --log_dir ./logs

"""
import argparse
import os
import json

from evaluate import run_all_models


def main():
    p = argparse.ArgumentParser(
        description='Run multiple models on a CSV and log outputs.')
    p.add_argument('--csv', required=True, help='Path to input CSV')
    p.add_argument('--target', required=True, help='Target column name')
    p.add_argument(
        '--log_dir', default='./logs',
        help='Directory to write model logs')
    p.add_argument(
        '--test_size', type=float, default=0.2,
        help='Test split fraction')
    p.add_argument('--random_state', type=int, default=42, help='Random seed')
    args = p.parse_args()

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"CSV not found: {csv_path}")
        return

    os.makedirs(args.log_dir, exist_ok=True)
    print(
        f"Running evaluation on {csv_path} (target={args.target}) -> logs in {args.log_dir}")

    results = run_all_models(
        csv_path, args.target,
        args.log_dir,
        test_size=args.test_size,
        random_state=args.random_state
    )

    summary_path = os.path.join(args.log_dir, 'summary.json')
    with open(summary_path, 'w') as sf:
        json.dump(results, sf, indent=2)

    print(f"Done. Summary written to {summary_path}")


if __name__ == '__main__':
    main()
