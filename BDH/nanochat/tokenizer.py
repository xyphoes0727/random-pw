import torch
import copy

class ByteTokenizer:
    def __init__(self):
        # Base vocabulary is 256 bytes.
        # We append special tokens starting at index 256.
        self.special_tokens_list = [
            "<|bos|>",
            "<|user_start|>", "<|user_end|>",
            "<|assistant_start|>", "<|assistant_end|>",
            "<|python_start|>", "<|python_end|>",
            "<|output_start|>", "<|output_end|>"
        ]
        
        # Map special tokens to unique IDs (256, 257, ...)
        self.special_ids = {
            token: 256 + i for i, token in enumerate(self.special_tokens_list)
        }
        self.id_to_special = {v: k for k, v in self.special_ids.items()}
        
        # Total vocab size = 256 bytes + Number of special tokens
        self.vocab_size = 256 + len(self.special_tokens_list)
        
    def encode(self, text, prepend=None):
        """
        Encodes a string or list of strings into token IDs.
        Input: text (str | list[str]), prepend (optional special token str or int)
        Output: list[int] | list[list[int]]
        """
        # Normalize prepend to a list of IDs if it exists
        prefix_ids = []
        if prepend is not None:
            if isinstance(prepend, int):
                prefix_ids = [prepend]
            elif isinstance(prepend, str):
                # If prepend is a string, check if it is a known special token
                if prepend in self.special_ids:
                    prefix_ids = [self.special_ids[prepend]]
                else:
                    # Fallback: treat as raw text bytes
                    prefix_ids = list(prepend.encode('utf-8'))
            elif isinstance(prepend, list):
                # If it's a list, recursively process (assuming list of ints or strings)
                for item in prepend:
                    if isinstance(item, int):
                        prefix_ids.append(item)
                    elif isinstance(item, str) and item in self.special_ids:
                        prefix_ids.append(self.special_ids[item])

        if isinstance(text, str):
            # Encode string to raw bytes (0-255)
            tokens = list(text.encode('utf-8'))
            return prefix_ids + tokens
        
        elif isinstance(text, list):
            # Batch encode
            encoded_batch = []
            for t in text:
                tokens = list(t.encode('utf-8'))
                encoded_batch.append(prefix_ids + tokens)
            return encoded_batch
        
        else:
            raise ValueError(f"Unsupported text type: {type(text)}")

    def __call__(self, text, prepend=None):
        return self.encode(text, prepend=prepend)
        
    def decode(self, ids):
        """
        Decodes a list of IDs back to a string.
        Input: ids (list[int] | torch.Tensor)
        Output: str
        """
        if isinstance(ids, torch.Tensor):
             ids = ids.tolist()
             
        decoded_parts = []
        byte_buffer = []

        for i in ids:
            if not isinstance(i, int):
                continue
                
            # If it's a standard byte (0-255)
            if 0 <= i < 256:
                byte_buffer.append(i)
            # If it's a special token (> 255)
            elif i in self.id_to_special:
                # Flush the byte buffer first
                if byte_buffer:
                    decoded_parts.append(bytes(byte_buffer).decode('utf-8', errors='replace'))
                    byte_buffer = []
                # Append the special token string
                decoded_parts.append(self.id_to_special[i])
        
        # Flush any remaining bytes
        if byte_buffer:
            decoded_parts.append(bytes(byte_buffer).decode('utf-8', errors='replace'))
            
        return "".join(decoded_parts)
        
    def get_vocab_size(self):
        return self.vocab_size
        
    def get_bos_token_id(self):
        # Return the unique ID for <|bos|>
        return self.special_ids["<|bos|>"]

    def get_eos_token_id(self):
        # Using BOS as EOS/PAD or define separate if needed. 
        # For now returning BOS to match previous logic style.
        return self.special_ids["<|bos|>"]

    def encode_special(self, special_token):
        """
        Returns the unique integer ID for a special token.
        Input: special_token (str)
        Output: int (not list)
        """
        if special_token in self.special_ids:
            return self.special_ids[special_token]
        raise ValueError(f"Unknown special token: {special_token}")

    def render_conversation(self, conversation, max_tokens=2048):
        """
        Tokenize a Chat conversation.
        Returns:
        - ids: list[int]
        - mask: list[int]
        """
        ids, mask = [], []
        
        # Helper to ensure inputs are always lists
        def add_tokens(token_ids, mask_val):
            if isinstance(token_ids, int):
                token_ids = [token_ids]
            ids.extend(token_ids)
            mask.extend([mask_val] * len(token_ids))

        # Handle system message merging
        if conversation["messages"][0]["role"] == "system":
            conversation = copy.deepcopy(conversation)
            messages = conversation["messages"]
            assert messages[1]["role"] == "user", "System message must be followed by a user message"
            messages[1]["content"] = messages[0]["content"] + "\n\n" + messages[1]["content"]
            messages = messages[1:]
        else:
            messages = conversation["messages"]
        assert len(messages) >= 1, f"Conversation has less than 1 message"

        # Fetch special token IDs (integers)
        bos = self.get_bos_token_id()
        user_start = self.encode_special("<|user_start|>")
        user_end = self.encode_special("<|user_end|>")
        assistant_start = self.encode_special("<|assistant_start|>")
        assistant_end = self.encode_special("<|assistant_end|>")
        python_start = self.encode_special("<|python_start|>")
        python_end = self.encode_special("<|python_end|>")
        output_start = self.encode_special("<|output_start|>")
        output_end = self.encode_special("<|output_end|>")

        # Start with BOS
        add_tokens(bos, 0)
        
        for i, message in enumerate(messages):
            must_be_from = "user" if i % 2 == 0 else "assistant"
            assert message["role"] == must_be_from

            content = message["content"]

            if message["role"] == "user":
                assert isinstance(content, str)
                value_ids = self.encode(content) # encode returns list[int] for str input
                add_tokens(user_start, 0)
                add_tokens(value_ids, 0)
                add_tokens(user_end, 0)
                
            elif message["role"] == "assistant":
                # Assistant Start is context, not target (mask=0)
                add_tokens(assistant_start, 0)
                
                if isinstance(content, str):
                    value_ids = self.encode(content)
                    add_tokens(value_ids, 1) # Train on content
                elif isinstance(content, list):
                    for part in content:
                        value_ids = self.encode(part["text"])
                        if part["type"] == "text":
                            add_tokens(value_ids, 1)
                        elif part["type"] == "python":
                            add_tokens(python_start, 1)
                            add_tokens(value_ids, 1)
                            add_tokens(python_end, 1)
                        elif part["type"] == "python_output":
                            # Output is environmental observation, not trained
                            add_tokens(output_start, 0)
                            add_tokens(value_ids, 0)
                            add_tokens(output_end, 0)
                        else:
                            raise ValueError(f"Unknown part type: {part['type']}")
                
                # Assistant End is trained
                add_tokens(assistant_end, 1)

        ids = ids[:max_tokens]
        mask = mask[:max_tokens]
        return ids, mask

    def visualize_tokenization(self, ids, mask, with_token_id=False):
        RED = '\033[91m'
        GREEN = '\033[92m'
        RESET = '\033[0m'
        GRAY = '\033[90m'
        tokens = []
        for i, (token_id, mask_val) in enumerate(zip(ids, mask)):
            # Handle special tokens for visualization
            if token_id in self.id_to_special:
                token_str = self.id_to_special[token_id]
            else:
                token_str = self.decode([token_id])
                
            color = GREEN if mask_val == 1 else RED
            tokens.append(f"{color}{token_str}{RESET}")
            if with_token_id:
                tokens.append(f"{GRAY}({token_id}){RESET}")
        return '|'.join(tokens)

    def render_for_completion(self, conversation):
        """
        Renders conversation for inference (RL/Sampling).
        Returns: ids (list[int])
        """
        conversation = copy.deepcopy(conversation)
        messages = conversation["messages"]
        assert messages[-1]["role"] == "assistant"
        messages.pop() 

        ids, _ = self.render_conversation(conversation)

        # Append assistant start token to prime the model
        assistant_start = self.encode_special("<|assistant_start|>")
        ids.append(assistant_start)
        return ids
# -----------------------------------------------------------------------------
# nanochat-specific convenience functions

def get_tokenizer():
    from nanochat.common import get_base_dir
    # base_dir = get_base_dir()
    # tokenizer_dir = os.path.join(base_dir, "tokenizer")
    # return HuggingFaceTokenizer.from_directory(tokenizer_dir)
    # return RustBPETokenizer.from_directory(tokenizer_dir)
    return ByteTokenizer()

def get_token_bytes(device="cpu"):
    """
    Returns a tensor representing the byte length of every token in the vocab.
    Size matches tokenizer.get_vocab_size() (265).
    """
    tokenizer = get_tokenizer()
    vocab_size = tokenizer.get_vocab_size() # Returns 265
    
    # Initialize with 0s (special tokens have 0 'content' bytes for BPB calculation)
    t = torch.zeros(vocab_size, dtype=torch.int64, device=device)
    
    # 0-255 are exactly 1 byte each
    # This prevents 'index out of bounds' when x contains index 257+
    t[:256] = 1
    
    return t
