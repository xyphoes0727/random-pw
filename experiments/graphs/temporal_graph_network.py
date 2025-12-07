import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    confusion_matrix
)
from collections import defaultdict
from tqdm import tqdm
from loguru import logger
import warnings
from iter_mod import read_in_order
from river import preprocessing
# Suppress common warnings
warnings.filterwarnings("ignore", category=UserWarning)


class TemporalGNN(nn.Module):
    def __init__(self, edge_feat_dim, memory_dim, hidden_dim):
        super().__init__()
        self.memory_dim = memory_dim

        # Message function:
        # Input: edge_feat + 2*neighbor_memory + time_delta
        self.msg_input_dim = edge_feat_dim + 2 * memory_dim + 1

        self.msg_encoder = nn.Sequential(
            nn.Linear(self.msg_input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, memory_dim)
        )

        # Memory Updater: GRUCell
        self.gru = nn.GRUCell(memory_dim, memory_dim)

        # Predictor
        # Input: 3*memory (u, c, v) + edge_feat
        self.predictor_input_dim = 3 * memory_dim + edge_feat_dim

        self.predictor = nn.Sequential(
            nn.Linear(self.predictor_input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1)
        )

        # Node memory store (dictionary for dynamic nodes)
        self.node_memory = {}
        self.last_update_time = {}
        self.device = torch.device(
            'cuda' if torch.cuda.is_available() else 'cpu'
        )

    def get_memory(self, node_id):
        if node_id not in self.node_memory:
            self.node_memory[node_id] = torch.zeros(
                self.memory_dim
            ).to(self.device)
        return self.node_memory[node_id]

    def set_memory(self, node_id, memory):
        # Detach to prevent infinite graph growth during backprop through time
        self.node_memory[node_id] = memory.detach()

    def get_last_time(self, node_id):
        return self.last_update_time.get(node_id, 0)

    def forward(self, u, c, v, edge_feat):
        # 1. Retrieve current memory
        mem_u = self.get_memory(u)
        mem_c = self.get_memory(c)
        mem_v = self.get_memory(v)

        # 2. Predict
        # Input: [mem_u, mem_c, mem_v, edge_feat]
        combined = torch.cat([mem_u, mem_c, mem_v, edge_feat], dim=0)
        logits = self.predictor(combined)

        return logits

    def update_memory(self, u, c, v, edge_feat, timestamp):
        # Get current memories
        mem_u = self.get_memory(u)
        mem_c = self.get_memory(c)
        mem_v = self.get_memory(v)

        # Calculate time deltas
        t_u = self.get_last_time(u)
        t_c = self.get_last_time(c)
        t_v = self.get_last_time(v)

        dt_u = torch.tensor(
            [timestamp - t_u], dtype=torch.float32
        ).to(self.device)
        dt_c = torch.tensor(
            [timestamp - t_c], dtype=torch.float32
        ).to(self.device)
        dt_v = torch.tensor(
            [timestamp - t_v], dtype=torch.float32
        ).to(self.device)

        # Update last times
        self.last_update_time[u] = timestamp
        self.last_update_time[c] = timestamp
        self.last_update_time[v] = timestamp

        # Create messages
        # Msg for u: context is (c, v)
        input_u = torch.cat([edge_feat, mem_c, mem_v, dt_u], dim=0)
        msg_u = self.msg_encoder(input_u)
        new_mem_u = self.gru(msg_u.unsqueeze(0), mem_u.unsqueeze(0)).squeeze(0)

        # Msg for c: context is (u, v)
        input_c = torch.cat([edge_feat, mem_u, mem_v, dt_c], dim=0)
        msg_c = self.msg_encoder(input_c)
        new_mem_c = self.gru(msg_c.unsqueeze(0), mem_c.unsqueeze(0)).squeeze(0)

        # Msg for v: context is (u, c)
        input_v = torch.cat([edge_feat, mem_u, mem_c, dt_v], dim=0)
        msg_v = self.msg_encoder(input_v)
        new_mem_v = self.gru(msg_v.unsqueeze(0), mem_v.unsqueeze(0)).squeeze(0)

        self.set_memory(u, new_mem_u)
        self.set_memory(c, new_mem_c)
        self.set_memory(v, new_mem_v)


def str_to_bool(s):
    return s == 'True'


converter = {
    'amount': float,
    'use_chip': int,
    'card_brand': int,
    'card_type': int,
    'num_cards_issued': int,
    'credit_limit': float,
    'total_debt': float,
    'credit_score': int,
    'num_credit_cards': int,
    'is_fraud': int,
    'timestamp': int
}


def train_stream():
    return read_in_order(
        '../data/datasets/financial_transactions_dataset.csv',
        target='is_fraud',
        converters=converter,
        drop=[]  # Keep all columns for now, select specific ones in loop
    )


def train_temporal_gnn():
    # --- Hyperparameters ---
    EDGE_FEAT_DIM = 9
    MEMORY_DIM = 32
    HIDDEN_DIM = 64
    LEARNING_RATE = 0.001

    # --- Initialization ---
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f"Using device: {device}")

    model = TemporalGNN(
        edge_feat_dim=EDGE_FEAT_DIM,
        memory_dim=MEMORY_DIM,
        hidden_dim=HIDDEN_DIM
    ).to(device)

    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.BCEWithLogitsLoss()

    # Online Scaler
    scaler = preprocessing.StandardScaler()

    # Node mapping
    node_to_id = defaultdict(lambda: len(node_to_id))

    # Evaluation
    actual_output = []
    predicted_output = []

    total_data = 12645953

    logger.info("Starting temporal training loop...")

    for idx, (x, y) in tqdm(
        enumerate(train_stream()), total=total_data, desc="Training"
    ):

        # 1. Extract and Preprocess Features
        u_str = "u_" + str(x['card_client_id'])
        c_str = "c_" + str(x['card_id'])
        v_str = "v_" + str(x['merchant_id'])

        u = node_to_id[u_str]
        c = node_to_id[c_str]
        v = node_to_id[v_str]

        timestamp = x['timestamp']

        # Features to use
        feats = {
            'amount': x['amount'],
            'use_chip': x['use_chip'],
            'card_brand': x['card_brand'],
            'card_type': x['card_type'],
            'num_cards_issued': x['num_cards_issued'],
            'credit_limit': x['credit_limit'],
            'total_debt': x['total_debt'],
            'credit_score': x['credit_score'],
            'num_credit_cards': x['num_credit_cards']
        }

        # Online scaling
        scaler.learn_one(feats)
        feats_scaled = scaler.transform_one(feats)

        # Convert to tensor
        edge_feat_np = np.array([
            feats_scaled['amount'],
            feats_scaled['use_chip'],
            feats_scaled['card_brand'],
            feats_scaled['card_type'],
            feats_scaled['num_cards_issued'],
            feats_scaled['credit_limit'],
            feats_scaled['total_debt'],
            feats_scaled['credit_score'],
            feats_scaled['num_credit_cards']
        ], dtype=np.float32)

        edge_feat = torch.tensor(edge_feat_np).to(device)

        label = torch.tensor(
            [1.0 if y else 0.0], dtype=torch.float32
        ).to(device)

        # PREDICTION STEP
        model.eval()
        # No grad for prediction
        with torch.no_grad():
            logits = model(u, c, v, edge_feat)
            pred_prob = torch.sigmoid(logits).item()
            pred_binary = 1 if pred_prob > 0.5 else 0

            actual_output.append(y)
            predicted_output.append(pred_binary)

        train_all = False
        if train_all or y != pred_binary:
            # LEARNING STEP
            model.train()
            optimizer.zero_grad()

            # Forward pass again for gradient
            logits = model(u, c, v, edge_feat)
            loss = criterion(logits.squeeze(), label.squeeze())

            loss.backward()
            optimizer.step()

            # MEMORY UPDATE STEP
            with torch.no_grad():
                model.update_memory(u, c, v, edge_feat, timestamp)
        else:
            optimizer.zero_grad()

        if (idx + 1) % 10000 == 0:
            logger.info(f"Transaction: {idx+1}")
            # try:
            cf = confusion_matrix(actual_output, predicted_output)
            logger.info(
                f"Confusion Matrix:\n{cf}"
            )

            class_report_str = classification_report(
                actual_output, predicted_output,
                target_names=['Not Fraud', 'Fraud'], digits=5
            )
            logger.info(f"Classification Report:\n{class_report_str}")
    return actual_output, predicted_output, model


if __name__ == "__main__":
    actual, predicted, trained_model = train_temporal_gnn()

    logger.info("\n--- Final Evaluation ---")
    cf = classification_report(
        actual, predicted, target_names=['Not Fraud', 'Fraud'],
        digits=5
    )
    logger.info(f"\n{cf}")

    try:
        auc = roc_auc_score(actual, predicted)
        logger.info(f"ROC-AUC Score: {auc:.4f}")
    except Exception as e:
        logger.error(f"Could not calculate ROC-AUC: {e}")
