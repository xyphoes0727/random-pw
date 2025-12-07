#!/bin/bash

# This is a fast check script to verify the pipeline works.
# It runs on 4 GPUs with minimal data and steps.

export OMP_NUM_THREADS=1
export NANOCHAT_BASE_DIR="$HOME/.cache/nanochat_check"
mkdir -p $NANOCHAT_BASE_DIR

# -----------------------------------------------------------------------------
# Python venv setup with uv

command -v uv &> /dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d ".venv" ] || uv venv
uv sync --extra gpu
source .venv/bin/activate

# -----------------------------------------------------------------------------
# wandb setup
if [ -z "$WANDB_RUN" ]; then
    WANDB_RUN=run1
fi

# -----------------------------------------------------------------------------
# Reset report
python -m nanochat.report reset

# -----------------------------------------------------------------------------
# Tokenizer

# Install Rust / Cargo
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# Build the rustbpe Tokenizer
uv run maturin develop --release --manifest-path rustbpe/Cargo.toml

# Download minimal data (2 shards)
python -m nanochat.dataset -n 2

# Train tokenizer on small data
python -m scripts.tok_train --max_chars=20000000

# Evaluate tokenizer
python -m scripts.tok_eval

# -----------------------------------------------------------------------------
# Base model (pretraining)

export CUDA_VISIBLE_DEVICES=0,1,
NPROC_PER_NODE=2

# Pretrain for 20 steps
# total_batch_size=65536 (4 GPUs * 4 batch * 1024 seq * 4 accum steps)
echo "Starting base training..."
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.base_train -- --depth=10 --device_batch_size=4 --total_batch_size=65536 --num_iterations=10 --eval_every=100 --core_metric_every=100 --save_every=100 --run=$WANDB_RUN
echo "Base training completed."

echo "Starting base evaluation..."
# Evaluate loss (small split)
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.base_loss -- --device_batch_size=4 --split_tokens=1048576
echo "Base evaluation completed."

echo "Starting CORE evaluation..."
# Evaluate CORE tasks
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.base_eval
echo "CORE evaluation completed."

# -----------------------------------------------------------------------------
# Midtraining

echo "Downloading identity conversations..."
# Download identity conversations
curl -L -o $NANOCHAT_BASE_DIR/identity_conversations.jsonl https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl

echo "Starting midtraining..."
# Midtrain for 10 steps
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.mid_train -- --device_batch_size=4 --total_batch_size=65536 --num_iterations=10 --eval_every=5 --run=$WANDB_RUN
echo "Midtraining completed."

echo "Starting mid evaluation..."
# Eval mid
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.chat_eval -- -i mid
echo "Mid evaluation completed."

# -----------------------------------------------------------------------------
# Supervised Finetuning

echo "Starting SFT..."
# SFT for 10 steps
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.chat_sft -- --device_batch_size=4 --target_examples_per_step=32 --num_iterations=10 --run=$WANDB_RUN
echo "SFT completed."

echo "Starting SFT evaluation..."
# Eval SFT
torchrun --standalone --nproc_per_node=$NPROC_PER_NODE -m scripts.chat_eval -- -i sft
echo "SFT evaluation completed."

# -----------------------------------------------------------------------------
# Generate report
echo "Generating report..."
python -m nanochat.report generate
