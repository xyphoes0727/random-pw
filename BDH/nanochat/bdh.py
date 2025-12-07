import math
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from dataclasses import dataclass

# --- Distributed Helper ---
def get_dist_info():
    if dist.is_available() and dist.is_initialized():
        rank = dist.get_rank()
        world_size = dist.get_world_size()
        local_rank = int(os.environ.get('LOCAL_RANK', 0))
        ddp = True
    else:
        rank = 0
        world_size = 1
        local_rank = 0
        ddp = False
    return ddp, rank, local_rank, world_size

# --- Optimizer ---

@torch.no_grad()
def zeropower_via_newtonschulz5(G, steps=5, eps=1e-7):
    assert len(G.shape) == 2
    a, b, c = (3.4445, -4.7750, 2.0315)
    X = G.bfloat16()
    X /= (X.norm() + eps)
    if G.size(0) > G.size(1):
        X = X.T
    for _ in range(steps):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if G.size(0) > G.size(1):
        X = X.T
    return X

class Muon(torch.optim.Optimizer):
    def __init__(self, params, lr=0.02, momentum=0.95, nesterov=True, ns_steps=5):
        defaults = dict(lr=lr, momentum=momentum, nesterov=nesterov, ns_steps=ns_steps)
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure=None):
        for group in self.param_groups:
            lr = group['lr']
            momentum = group['momentum']
            nesterov = group['nesterov']
            ns_steps = group['ns_steps']
            for p in group['params']:
                if p.grad is None:
                    continue
                g = p.grad
                
                shape_original = g.shape
                if g.ndim == 3:
                    # (H, D, N) -> permute to (H, N, D) -> reshape to (H*N, D)
                    g = g.permute(0, 2, 1).reshape(-1, shape_original[1])
                elif g.ndim > 3:
                    g = g.view(g.size(0), -1)
                
                state = self.state[p]
                if 'momentum_buffer' not in state:
                    state['momentum_buffer'] = torch.zeros_like(g)
                buf = state['momentum_buffer']
                
                buf.mul_(momentum).add_(g)
                
                if nesterov:
                    g = g.add(buf, alpha=momentum)
                else:
                    g = buf

                update = zeropower_via_newtonschulz5(g, steps=ns_steps)
                
                if len(shape_original) == 3:
                    # (H*N, D) -> (H, N, D) -> (H, D, N)
                    update = update.view(shape_original[0], shape_original[2], shape_original[1]).permute(0, 2, 1)
                elif len(shape_original) > 2:
                    update = update.view_as(p)
                
                p.data.add_(update, alpha=-lr)

# --- Model Components ---

# @dataclass
# class BDHConfig:
#     vocab_size: int = 265
#     n_layer: int = 6
#     n_embd: int = 256
#     # Scaled for ~100M parameters
#     n_hidden: int = 8192
#     n_head: int = 4
#     max_seq_len: int = 2048
#     dropout: float = 0.1


@dataclass
class BDHConfig:
    vocab_size: int = 265
    n_layer: int = 8
    n_embd: int = 256
    # Scaled for ~100M parameters
    n_hidden: int = 16384
    n_head: int = 4
    max_seq_len: int = 2048
    dropout: float = 0.1

class Attention(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        nh = config.n_head
        D = config.n_embd
        N = config.n_hidden // nh
        self.head_dim = N 
        
        self.register_buffer(
            "freqs",
            self.get_freqs(N, theta=2**16, dtype=torch.float32).view(1, 1, 1, N)
        )

    @staticmethod
    def get_freqs(n, theta, dtype):
        def quantize(t, q=2):
            return (t / q).floor() * q
        return (1.0 / (theta ** (quantize(torch.arange(0, n, 1, dtype=dtype)) / n)) / (2 * math.pi))

    @staticmethod
    def phases_cos_sin(phases):
        phases = (phases % 1) * (2 * math.pi)
        phases_cos = torch.cos(phases)
        phases_sin = torch.sin(phases)
        return phases_cos, phases_sin

    @staticmethod
    def rope(phases, v):
        v_rot = torch.stack((-v[..., 1::2], v[..., ::2]), dim=-1).view(*v.size())
        phases_cos, phases_sin = Attention.phases_cos_sin(phases)
        return (v * phases_cos).to(v.dtype) + (v_rot * phases_sin).to(v.dtype)

    def forward(self, Q, K, V):
        assert K is Q
        _, _, T, _ = Q.size()

        freqs_sliced = self.freqs[:, :, :T, :] 
        r_phases = (
            torch.arange(0, T, device=freqs_sliced.device, dtype=freqs_sliced.dtype).view(1, 1, -1, 1)
        ) * freqs_sliced
        
        QR = self.rope(r_phases, Q)
        KR = QR

        # --- FIX START ---
<<<<<<< HEAD
        # 1. Restore Scaling (Crucial for gradient stability)
        scale = 1.0 / math.sqrt(self.head_dim)
        
        # 2. Calculate Scores
        scores = (QR @ KR.mT) * scale
        
        # 3. Apply Mask
        # Use diagonal=0 (standard causal) or diagonal=-1 (strict past)
        # Standard GPT/Llama uses diagonal=0 (allows attending to self)
        mask = torch.ones(T, T, device=scores.device, dtype=torch.bool).tril(diagonal=0)
        scores = scores.masked_fill(~mask, float('-inf'))
        
        # 4. Restore Softmax (Crucial for selection)
        attn_weights = F.softmax(scores, dim=-1)
        
        return attn_weights @ V
=======
        # 1. REMOVE Scaling (1.0/sqrt(D))
        # 2. REMOVE Softmax
        # 3. Change Mask to 'tril(diagonal=-1)' (Strictly past, no self-attention)
        
        # Original (Broken for BDH):
        # scale = 1.0 / math.sqrt(Q.size(-1))
        # scores = (QR @ KR.mT) * scale
        # mask = torch.triu(torch.ones(T, T, device=scores.device, dtype=torch.bool), diagonal=1)
        # scores.masked_fill_(mask, float('-inf'))
        # attn_weights = F.softmax(scores, dim=-1)
        # return attn_weights @ V

        # Fixed (BDH Logic):
        scores = (QR @ KR.mT).tril(diagonal=-1)
        return scores @ V
        # --- FIX END ---
>>>>>>> main


class BDH(nn.Module):
    def __init__(self, config: BDHConfig):
        super().__init__()
        assert config.vocab_size is not None
        self.config = config
        nh = config.n_head
        D = config.n_embd
        N = config.n_hidden // nh
        
        # Universal weights
        # Maps from N (High Dim) -> D (Low Dim)
        self.decoder = nn.Parameter(torch.zeros((nh * N, D)))
        # Maps from D (Low Dim) -> N (High Dim)
        self.encoder = nn.Parameter(torch.zeros((nh, D, N)))
        self.encoder_v = nn.Parameter(torch.zeros((nh, D, N)))
        
        self.attn = Attention(config)
        self.ln = nn.LayerNorm(D, elementwise_affine=False, bias=False)
        self.embed = nn.Embedding(config.vocab_size, D)
        self.drop = nn.Dropout(config.dropout)
        
        self.lm_head = nn.Parameter(torch.zeros((D, config.vocab_size)))

        self.init_weights()

    def init_weights(self):
        # Embeddings and Head
        nn.init.normal_(self.lm_head, std=0.02)
        nn.init.normal_(self.embed.weight, std=0.02)
        
        # Encoder (D -> N): Standard init is fine
        nn.init.normal_(self.encoder, std=0.02)
        nn.init.normal_(self.encoder_v, std=0.02)
        
        # --- FIX START ---
        # Decoder (N -> D):
        # Original: nn.init.normal_(self.decoder, std=1.0 / math.sqrt(self.config.n_hidden))
        # Fixed: Match uniform std=0.02 for consistent Muon optimization
        nn.init.normal_(self.decoder, std=0.02)
        # --- FIX END ---

    def get_device(self):
        return self.embed.weight.device

    def estimate_flops(self):
        N = self.config.n_hidden
        D = self.config.n_embd
        L = self.config.n_layer
        T = self.config.max_seq_len
        return L * (3 * N * D + N * T)

<<<<<<< HEAD
    def forward(self, idx, targets=None, loss_reduction=None):
=======
    def forward(self, idx, targets=None, state=None, loss_reduction=None):
>>>>>>> main
        C = self.config
        B, T = idx.size()
        D = C.n_embd
        nh = C.n_head
        N = C.n_hidden // nh

        # Initial Embedding & Norm
        # Note: We keep x normalized, but accumulate into it
        x = self.embed(idx).unsqueeze(1) 
        x = self.ln(x)

        for level in range(C.n_layer):
            # 1. Project to Latent [B, 1, T, D] -> [B, H, T, N]
            # Input 'x' is already normalized from previous step or init
            x_latent = torch.einsum('btd,hdn->bhtn', x.squeeze(1), self.encoder)
            x_sparse = F.relu(x_latent)

            # 2. Attention
            yKV = self.attn(Q=x_sparse, K=x_sparse, V=x)
            yKV = self.ln(yKV) # Normalize attention output

            # 3. Gating
            y_latent = torch.einsum('bhtd,hdn->bhtn', yKV, self.encoder_v)
            y_sparse = F.relu(y_latent)
            
            xy_sparse = x_sparse * y_sparse
            xy_sparse = self.drop(xy_sparse)

            # 4. Project Back
            # [B, H, T, N] -> [B, 1, T, D]
            # Flatten heads: (B, T, H*N) @ (H*N, D) -> (B, T, D)
            yMLP = (xy_sparse.transpose(1, 2).reshape(B, 1, T, N * nh) @ self.decoder)
            
            # --- FIX START ---
            # Residual Connection Architecture
            # Original: x = x + self.ln(yMLP)
            # Fixed: Post-Norm on accumulation. This ensures 'x' remains a stable accumulator.
            # x = self.ln(x + yMLP)
            y = self.ln(yMLP)
            x = self.ln(x + y)
            # --- FIX END ---

        # Final Norm before Head
        # (Often implicit in the last layer update, but explicit here for safety)
        # x_final = self.ln(x)
        logits = x.view(B, T, D) @ self.lm_head
        
        if loss_reduction == 'none':
            if targets is None:
                raise ValueError("targets must be provided")
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1), reduction='none')
            return loss.view(B, T)
            
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))

        return logits, loss

    def setup_optimizers(self, unembedding_lr=0.004, embedding_lr=0.002, matrix_lr=0.02, weight_decay=0.0):
        muon_params = []
        head_params = []
        embedding_params = []
        other_params = []
        
        for name, p in self.named_parameters():
            if name in ['encoder', 'decoder', 'encoder_v']:
                muon_params.append(p)
            elif name == 'lm_head':
                head_params.append(p)
            elif name == 'embed.weight':
                embedding_params.append(p)
            else:
                other_params.append(p)
        
        dmodel_lr_scale = min(1.0, (self.config.n_embd / 768) ** -0.5)
        
        adam_groups = [
            {'params': head_params, 'lr': unembedding_lr * dmodel_lr_scale, 'weight_decay': weight_decay},
            {'params': embedding_params, 'lr': embedding_lr * dmodel_lr_scale, 'weight_decay': weight_decay},
            {'params': other_params, 'lr': embedding_lr * dmodel_lr_scale, 'weight_decay': weight_decay}
        ]
        
        optimizers = [
            torch.optim.AdamW(adam_groups, betas=(0.9, 0.95)),
            Muon(muon_params, lr=matrix_lr, momentum=0.95)
        ]
        
        
        # optimizers = [
        #     torch.optim.AdamW(
        #         [
        #             {'params': [p for n, p in self.named_parameters() if n != 'lm_head'], 'lr': embedding_lr, 'weight_decay': weight_decay},
        #             {'params': [p for n, p in self.named_parameters() if n == 'lm_head'], 'lr': unembedding_lr, 'weight_decay': weight_decay}
        #         ],
        #         betas=(0.9, 0.95)
        #     ),
        #     None
        # ]
        for opt in optimizers:
            if opt is None:
                continue
            for group in opt.param_groups:
                group["initial_lr"] = group["lr"]

        return optimizers

    @torch.inference_mode()
    def generate(self, tokens, max_tokens, temperature=1.0, top_k=None, seed=42):
        """
        Naive autoregressive streaming inference.
        """
        assert isinstance(tokens, list)
        device = self.get_device()
        rng = None
        if temperature > 0:
            rng = torch.Generator(device=device)
            rng.manual_seed(seed)
        ids = torch.tensor([tokens], dtype=torch.long, device=device) # add batch dim
        
        for _ in range(max_tokens):
            # --- FIX START ---
            # forward returns (logits, loss), so we must unpack it.
            logits, _ = self.forward(ids) 
            # --- FIX END ---
            
            logits = logits[:, -1, :] # (B, vocab_size)
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float('Inf')
            if temperature > 0:
                logits = logits / temperature
                probs = F.softmax(logits, dim=-1)
                next_ids = torch.multinomial(probs, num_samples=1, generator=rng)
            else:
                next_ids = torch.argmax(logits, dim=-1, keepdim=True)
            ids = torch.cat((ids, next_ids), dim=1)
            token = next_ids.item()
            yield token