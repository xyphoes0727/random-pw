import torch
import pyarrow.parquet as pq
import itertools

from nanochat.common import get_dist_info
from nanochat.dataset import list_parquet_files
from nanochat.tokenizer import get_tokenizer

def tokenizing_distributed_data_loader_with_state(B, T, split, tokenizer_threads=4, tokenizer_batch_size=128, device="cuda", resume_state_dict=None):
    """
    Corrected Data Loader for BDH / TBPTT.
    
    Instead of chunking documents individually, this loader creates a continuous 
    stream of data, reshapes it into 'B' rows, and iterates through time.
    """
    assert split in ["train", "val"], "split must be 'train' or 'val'"

    # 1. Distributed Setup & Tokenizer
    # --- FIX: ENABLE DDP INFO ---
    ddp, ddp_rank, ddp_local_rank, ddp_world_size = get_dist_info()
    
    # Removed hardcoded single-node values
    # ddp_rank = 0 
    # ...
    
    tokenizer = get_tokenizer()
    bos_token = tokenizer.get_bos_token_id()
    
    # 2. Infinite Token Stream Generator
    def infinite_token_stream():
        # Get all files
        all_paths = list_parquet_files()
        all_paths = all_paths[:-1] if split == "train" else all_paths[-1:]
        
        # Shard files for DDP: Each rank gets a unique subset of files
        # This ensures CONTINUITY per rank (each rank iterates a unique chain of files)
        if split == "train":
            my_paths = all_paths[ddp_rank::ddp_world_size]
        else:
            # For validation, use all files on all ranks to avoid empty file lists
            # This duplicates work but ensures correctness when files < ranks
            my_paths = all_paths
        
        # Resume logic (simplified: skip files)
        start_file_idx = resume_state_dict["file_idx"] if resume_state_dict else 0
        
        # Infinite Epoch Loop
        while True:
            for i, filepath in enumerate(my_paths[start_file_idx:], start=start_file_idx):
                try:
                    pf = pq.ParquetFile(filepath)
                    # Read entire file (or row groups)
                    for rg in range(pf.num_row_groups):
                        table = pf.read_row_group(rg)
                        texts = table.column('text').to_pylist()
                        
                        # Bulk tokenize
                        batch_tokens = tokenizer.encode(texts, prepend=bos_token) 
                        
                        # Flatten list of lists into a single stream and yield
                        for doc in batch_tokens:
                            yield from doc
                            
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")
                    continue
                
                # Update state tracking
                if resume_state_dict:
                    resume_state_dict["file_idx"] = i
            
            # Reset for next epoch
            start_file_idx = 0

    token_iter = infinite_token_stream()

    # 3. Buffer and Reshape Logic
    # We load a large "Macro Batch" into memory, reshape it to (B, L), 
    # and then slice it into micro-batches of width T.
    
    tokens_per_macro_batch = 5_000_000 
    tokens_per_macro_batch = (tokens_per_macro_batch // B) * B
    
    batches_yielded = resume_state_dict.get("batches_yielded", 0) if resume_state_dict else 0

    while True:
        # A. Fill the Buffer
        buffer = list(itertools.islice(token_iter, tokens_per_macro_batch))
        
        if len(buffer) < B * T + 1:
            break
            
        valid_len = (len(buffer) // B) * B
        
        # B. Create Tensor and Reshape
        # Shape becomes [B, Sequence_Length_Per_Row]
        data_tensor = torch.tensor(buffer[:valid_len], dtype=torch.long)
        num_cols = valid_len // B
        data_view = data_tensor.view(B, num_cols)
        
        # C. Yield Minibatches
        for i in range(0, num_cols - 1, T):
            if i + T + 1 > num_cols:
                break
            
            x = data_view[:, i : i+T]
            y = data_view[:, i+1 : i+T+1]
            
            if device == "cuda":
                x = x.pin_memory().to(device, non_blocking=True)
                y = y.pin_memory().to(device, non_blocking=True)
            else:
                x = x.to(device)
                y = y.to(device)
            
            current_state = {
                "batches_yielded": batches_yielded,
            }
            
            yield x, y, current_state
            batches_yielded += 1

# text_file_data_loader remains unchanged as it is for single file debug usually
def text_file_data_loader(B, T, device="cuda", resume_state_dict=None):
    # ... (Same as provided)
    data_path='/home/b23cs1037/noise_init/nanochat_better/input.txt'
    tokenizer = get_tokenizer()
    bos_token = tokenizer.get_bos_token_id()
    
    def infinite_token_stream():
        while True: 
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                tokens = tokenizer.encode([text], prepend=bos_token)[0] 
                yield from tokens
            except Exception as e:
                print(f"Error reading {data_path}: {e}")
                raise e

    token_iter = infinite_token_stream()
    tokens_per_macro_batch = 5_000_000 
    tokens_per_macro_batch = (tokens_per_macro_batch // B) * B
    batches_yielded = resume_state_dict.get("batches_yielded", 0) if resume_state_dict else 0

    while True:
        buffer = list(itertools.islice(token_iter, tokens_per_macro_batch))
        if len(buffer) < B * T + 1:
            break
        valid_len = (len(buffer) // B) * B
        data_tensor = torch.tensor(buffer[:valid_len], dtype=torch.long)
        num_cols = valid_len // B
        data_view = data_tensor.view(B, num_cols)
        for i in range(0, num_cols - 1, T):
            if i + T + 1 > num_cols:
                break
            x = data_view[:, i : i+T]
            y = data_view[:, i+1 : i+T+1]
            if device == "cuda":
                x = x.pin_memory().to(device, non_blocking=True)
                y = y.pin_memory().to(device, non_blocking=True)
            else:
                x = x.to(device)
                y = y.to(device)
            yield x, y, {"batches_yielded": batches_yielded}
            batches_yielded += 1

def tokenizing_distributed_data_loader(*args, **kwargs):
    for inputs, targets, state_dict in tokenizing_distributed_data_loader_with_state(*args, **kwargs):
        yield inputs, targets
