"""
Midtrain the model. Same as pretraining but simpler.
Run as:

python -m scripts.mid_train

Or torchrun for training:

torchrun --standalone --nproc_per_node=8 -m scripts.mid_train -- --device_batch_size=16
"""

from collections import deque
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import time
import wandb
from torch.nn.parallel import DistributedDataParallel as DDP
import torch
from contextlib import nullcontext
from nanochat.common import compute_init, compute_cleanup, print0, DummyWandb, get_base_dir, autodetect_device_type
from nanochat.tokenizer import get_token_bytes
from nanochat.checkpoint_manager import save_checkpoint
from nanochat.loss_eval import evaluate_bpb
from nanochat.checkpoint_manager import load_model
import torch.distributed as dist

from tasks.common import TaskMixture
from tasks.gsm8k import GSM8K
from tasks.mmlu import MMLU
from tasks.smoltalk import SmolTalk
from tasks.customjson import CustomJSON
from tasks.spellingbee import SimpleSpelling, SpellingBee

# -----------------------------------------------------------------------------
run = "dummy" # wandb run name default ("dummy" is special - we won't log to wandb)
device_type = "" # cuda|cpu|mps (empty => autodetect)
model_tag = None # model tag to load the model from (base model or midtrained model)
step = None # step to load the model from (base model or midtrained model)
dtype = "bfloat16" # float16|bfloat16|float32
num_iterations = -1 # explicit number of steps of the optimization (-1 = disable)
max_seq_len = 2048
device_batch_size = 16 #changed from 32 to 8
unembedding_lr = 0.004
embedding_lr = 0.002
matrix_lr = 0.02
init_lr_frac = 1.0 
weight_decay = 0.1 # Changed from 0.0 to 0.1 (matches working script)
grad_clip = 1.0    # Added gradient clipping

# --- FIX 2: BATCH SIZE ---
# Lowered total_batch_size to reduce accumulation latency.
# 65536 ensures frequent updates (Accumulation ~2 on single GPU, ~1 on multi-GPU)
total_batch_size = 65536 

eval_every = 150 # -1 = disable
eval_tokens = 20*524288

dry_run = 0 
config_keys = [k for k,v in globals().items() if not k.startswith('_') and isinstance(v, (int, float, bool, str))]
exec(open(os.path.join('nanochat', 'configurator.py')).read()) # overrides from command line or config file
user_config = {k: globals()[k] for k in config_keys} # possibly useful for logging
# -----------------------------------------------------------------------------

# Compute init
device_type = autodetect_device_type() if device_type == "" else device_type
ddp, ddp_rank, ddp_local_rank, ddp_world_size, device = compute_init(device_type)
master_process = ddp_rank == 0
autocast_ctx = torch.amp.autocast(device_type=device_type, dtype=torch.bfloat16) if device_type == "cuda" else nullcontext()
synchronize = torch.cuda.synchronize if device_type == "cuda" else lambda: None
get_max_memory = torch.cuda.max_memory_allocated if device_type == "cuda" else lambda: 0

# --- FIX 3: SCALER INIT ---
# Initialize GradScaler for stability
scaler = torch.amp.GradScaler(device='cuda', enabled=(dtype == 'float16'))

# wandb logging init
use_dummy_wandb = run == "dummy" or not master_process
wandb_run = DummyWandb() if use_dummy_wandb else wandb.init(project="nanochat-mid", name=run, config=user_config)

# Load the model and tokenizer
model, tokenizer, meta = load_model("base", device, phase="train", model_tag=model_tag, step=step)
pretrain_batch_size = meta.get("device_batch_size", None)
if pretrain_batch_size is not None and device_batch_size > pretrain_batch_size:
    print0(f"FOOTGUN WARNING: base model training used device_batch_size {pretrain_batch_size}, did you pass in a good --device_batch_size to this script?")
orig_model = model
if ddp:
    # 1. Wrap model to enable gradient syncing across GPUs
    model = DDP(model, device_ids=[ddp_local_rank])

model = torch.compile(model, dynamic=False)

# 2. Create a reference to the inner model to access custom methods (setup_optimizers)
#    and config attributes. 
#    If DDP is on, the inner model is at model.module.
#    If DDP is off, the model is just the model.
raw_model = model.module if ddp else model

depth = orig_model.config.n_layer
num_flops_per_token = orig_model.estimate_flops()
tokens_per_fwdbwd = device_batch_size * max_seq_len # tokens per iteration for a single rank
world_tokens_per_fwdbwd = tokens_per_fwdbwd * ddp_world_size # total tokens per iteration for all ranks
assert total_batch_size % world_tokens_per_fwdbwd == 0
grad_accum_steps = total_batch_size // world_tokens_per_fwdbwd
print0(f"Tokens / micro-batch / rank: {device_batch_size} x {max_seq_len} = {tokens_per_fwdbwd:,}")
print0(f"Tokens / micro-batch: {world_tokens_per_fwdbwd:,}")
print0(f"Total batch size {total_batch_size:,} => gradient accumulation steps: {grad_accum_steps}")
token_bytes = get_token_bytes(device=device)

# Initialize the Optimizer (Muon for Linear layers, AdamW for embedding and lm_head)
optimizers = model.setup_optimizers(unembedding_lr=unembedding_lr, embedding_lr=embedding_lr, matrix_lr=matrix_lr, weight_decay=weight_decay)
adamw_optimizer, muon_optimizer = optimizers
# adamw_optimizer = optimizers[0]

# Override the initial learning rate as a fraction of the base learning rate
for opt in optimizers:
    for group in opt.param_groups:
        group["lr"] = group["lr"] * init_lr_frac
        group["initial_lr"] = group["lr"] # save the initial learning so we can decay easily later

# Midtraining data mixture and DataLoader
base_dir = get_base_dir()
identity_conversations_filepath = os.path.join(base_dir, "identity_conversations.jsonl")
train_dataset = TaskMixture([
    SmolTalk(split="train"), 
    MMLU(subset="auxiliary_train", split="train"), 
    GSM8K(subset="main", split="train"), 
    CustomJSON(filepath=identity_conversations_filepath), 
    CustomJSON(filepath=identity_conversations_filepath), 
    SimpleSpelling(size=200000, split="train"), 
    SpellingBee(size=80000, split="train"), 
]) 
val_dataset = TaskMixture([
    SmolTalk(split="test"), 
    MMLU(subset="all", split="test", stop=5200), 
    GSM8K(subset="main", split="test", stop=420), 
]) 

last_step = False 
approx_progress = 0.0 
def mid_data_generator(split):
    global last_step, approx_progress
    assert split in {"train", "val"}, "split must be 'train' or 'val'"
    dataset = train_dataset if split == "train" else val_dataset
    dataset_size = len(dataset)
    assert dataset_size > 0
    needed_tokens = device_batch_size * max_seq_len + 1 
    token_buffer = deque()
    scratch = torch.empty(needed_tokens, dtype=torch.int64, pin_memory=(device_type == "cuda"))
    cursor = ddp_rank 
    it = 0 
    while True:
        while len(token_buffer) < needed_tokens:
            conversation = dataset[cursor]
            ids, _ = tokenizer.render_conversation(conversation)
            token_buffer.extend(ids)
            cursor += ddp_world_size
            if cursor >= dataset_size:
                cursor -= dataset_size 
                if split == "train":
                    last_step = True 
        it += 1
        if num_iterations > 0 and it >= num_iterations:
            last_step = True 
        for i in range(needed_tokens):
            scratch[i] = token_buffer.popleft()
        inputs_cpu = scratch[:-1].to(dtype=torch.int32)
        targets_cpu = scratch[1:]
        inputs = inputs_cpu.view(device_batch_size, max_seq_len).to(device=device, dtype=torch.int32, non_blocking=True)
        targets = targets_cpu.view(device_batch_size, max_seq_len).to(device=device, dtype=torch.int64, non_blocking=True)
        if split == "train":
            if num_iterations > 0:
                approx_progress = it / num_iterations 
            else:
                approx_progress = cursor / dataset_size 
        yield inputs, targets

train_loader = mid_data_generator("train")
build_val_loader = lambda: mid_data_generator("val")
progress = 0 

# --- FIX 4: WARMUP SCHEDULER ---
# Added 3% warmup to prevent shocking the model
def get_lr_multiplier(progress):
    warmup_pct = 0.03
    if progress < warmup_pct:
        return progress / warmup_pct
    # decay after 80%
    elif progress < 0.8:
        return 1.0
    else:
        return 1.0 - (progress - 0.8) / 0.2

def get_muon_momentum(it):
    frac = min(it / 300, 1)
    momentum = (1 - frac) * 0.85 + frac * 0.95
    return momentum

# -----------------------------------------------------------------------------
# Training loop
x, y = next(train_loader) 
min_val_bpb = float("inf")
smooth_train_loss = 0 
ema_beta = 0.9 
total_training_time = 0 
step = 0

while True:
    flops_so_far = num_flops_per_token * total_batch_size * step

    if ddp:
        last_step_tensor = torch.tensor(last_step, dtype=torch.int32, device=device)
        dist.all_reduce(last_step_tensor, op=dist.ReduceOp.MAX)
        last_step = bool(last_step_tensor.item())

    # once in a while: evaluate the val bpb
    if eval_every > 0 and (last_step or step % eval_every == 0):
        val_bpb = 0.0
        # model.eval()
        # val_loader = build_val_loader()
        # eval_steps = eval_tokens // (device_batch_size * max_seq_len * ddp_world_size)
        # with autocast_ctx:
        #     val_bpb = evaluate_bpb(model, val_loader, eval_steps, token_bytes)
        # print0(f"Step {step:05d} | Validation bpb: {val_bpb:.4f}")
        # if val_bpb < min_val_bpb:
        #     min_val_bpb = val_bpb
        # wandb_run.log({
        #     "step": step,
        #     "total_training_flops": flops_so_far,
        #     "total_training_time": total_training_time,
        #     "val/bpb": val_bpb,
        # })
        model.train()

    # save checkpoint
    if master_process and last_step and not dry_run:
        output_dirname = f"d{depth}" 
        checkpoint_dir = os.path.join(base_dir, "mid_checkpoints", output_dirname)
        save_checkpoint(
            checkpoint_dir,
            step,
            orig_model.state_dict(),
            [opt.state_dict() for opt in optimizers], 
            {
                "step": step,
                "val_bpb": val_bpb, 
                "model_config": {
                    "sequence_len": max_seq_len,
                    "vocab_size": tokenizer.get_vocab_size(),
                    "n_layer": depth,
                    "n_head": orig_model.config.n_head,
                    "n_kv_head": orig_model.config.n_kv_head,
                    "n_embd": orig_model.config.n_embd,
                },
                "user_config": user_config, 
            }
        )

    if last_step:
        break

    # -------------------------------------------------------------------------
    # single training step
    synchronize()
    t0 = time.time()
    for micro_step in range(grad_accum_steps):
        with autocast_ctx:
            _, loss = model(x, y)
        train_loss = loss.detach() 
        loss = loss / grad_accum_steps 
        
        # --- FIX 5: SCALED BACKWARD ---
        scaler.scale(loss).backward()
        
        x, y = next(train_loader) 
        progress = max(progress, approx_progress) 

    # --- FIX 6: GRADIENT CLIPPING ---
    if grad_clip > 0.0:
        scaler.unscale_(adamw_optimizer)
        scaler.unscale_(muon_optimizer)
        torch.nn.utils.clip_grad_norm_(raw_model.parameters(), grad_clip)

    # step the optimizers
    lrm = get_lr_multiplier(progress)
    for opt in optimizers:
        for group in opt.param_groups:
            group["lr"] = group["initial_lr"] * lrm
            
    muon_momentum = get_muon_momentum(step)
    # for group in muon_optimizer.param_groups:
    #     group["momentum"] = muon_momentum
    for opt in optimizers:
        # check gradients
        for group in opt.param_groups:
            for p in group['params']:
                if p.grad is None:
                    print(f"Warning: param with no gradient, shape: {p.shape}")
                    continue
                if p.grad.norm() < 1e-6:
                    print(f"Warning: param with very small gradient, shape: {p.shape}, grad_norm: {p.grad.norm()}")
        opt.step()
    model.zero_grad(set_to_none=True)
    synchronize()
    t1 = time.time()
    dt = t1 - t0
    # -------------------------------------------------------------------------

    # State
    step += 1

    # logging
    smooth_train_loss = ema_beta * smooth_train_loss + (1 - ema_beta) * train_loss.item() 
    debiased_smooth_loss = smooth_train_loss / (1 - ema_beta**(step + 1)) 
    pct_done = 100 * progress
    tok_per_sec = int(total_batch_size / dt)
    flops_per_sec = num_flops_per_token * total_batch_size / dt
    promised_flops_per_sec_h100 = 989e12 * ddp_world_size 
    mfu = 100 * flops_per_sec / promised_flops_per_sec_h100 
    if step > 10:
        total_training_time += dt 
    print0(f"step {step:05d} ({pct_done:.2f}%) | loss: {debiased_smooth_loss:.6f} | lrm: {lrm:.2f} | dt: {dt * 1000:.2f}ms | tok/sec: {tok_per_sec:,} | mfu: {mfu:.2f} | total time: {total_training_time/60:.2f}m")
    if step % 10 == 0:
        wandb_run.log({
            "step": step,
            "total_training_flops": flops_so_far,
            "total_training_time": total_training_time,
            "train/loss": debiased_smooth_loss,
            "train/lrm": lrm,
            "train/dt": dt,
            "train/tok_per_sec": tok_per_sec,
            "train/mfu": mfu,
        })

# print a few more stats
print0(f"Peak memory usage: {get_max_memory() / 1024 / 1024:.2f}MiB")
print0(f"Total training time: {total_training_time/60:.2f}m")
print0(f"Minimum validation bpb: {min_val_bpb:.4f}")

if not dry_run:
    from nanochat.report import get_report
    get_report().log(section="Midtraining", data=[
        user_config, 
        { 
            "Number of iterations": step,
            "DDP world size": ddp_world_size,
        },
        { 
            "Minimum validation bpb": min_val_bpb,
        }
    ])

wandb_run.finish() 
compute_cleanup()
