import pandas as pd
import numpy as np

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

# ---------------------------
# Config
# ---------------------------
CSV_PATH = "pcap_features_all.csv"
BATCH_SIZE = 32
LR = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 30
PATIENCE = 5
RANDOM_STATE = 42

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", DEVICE)

# ---------------------------
# Load & preprocess data
# ---------------------------
df = pd.read_csv(CSV_PATH)

# Map models to size: 0 = 7B, 1 = 14B
model_to_size = {
    "mistralai-Mistral-7B-Instruct-v0.2": 0,
    "HuggingFaceH4-zephyr-7b-beta": 0,
    "Qwen-Qwen2.5-7B-Instruct": 0,
    "Qwen-Qwen3-14B-Base": 1,
    "ozone-research-0x-lite": 1,
    "prithivMLmods-Gauss-Opus-14B-R999": 1,
}

df["size"] = df["model"].map(model_to_size)
assert not df["size"].isna().any(), "Unmapped model names in df['model']"

print("Size distribution:\n", df["size"].value_counts())

# Features: drop ids and label columns
id_cols = ["filename", "session"]
drop_cols = id_cols + ["model", "size"]
feature_cols = [c for c in df.columns if c not in drop_cols]
print("Num features:", len(feature_cols), "->", feature_cols)

X_np = df[feature_cols].to_numpy(dtype=np.float32)
y_np = df["size"].to_numpy(dtype=np.int64)

print(f"X shape: {X_np.shape}, y shape: {y_np.shape}")

# Train/test split (stratified)
X_train, X_test, y_train, y_test = train_test_split(
    X_np,
    y_np,
    test_size=0.2,
    stratify=y_np,
    random_state=RANDOM_STATE,
)

# Standardize using train statistics only
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# To tensors
X_train_t = torch.tensor(X_train_scaled, dtype=torch.float32)
y_train_t = torch.tensor(y_train, dtype=torch.long)
X_test_t = torch.tensor(X_test_scaled, dtype=torch.float32)
y_test_t = torch.tensor(y_test, dtype=torch.long)

print("Train tensor shape:", X_train_t.shape)
print("Test tensor shape:", X_test_t.shape)
print("y_train range:", y_train_t.min().item(), "to", y_train_t.max().item())

# ---------------------------
# Dataloaders
# ---------------------------
train_loader = DataLoader(
    TensorDataset(X_train_t, y_train_t),
    batch_size=BATCH_SIZE,
    shuffle=True,
    num_workers=0,
)
test_loader = DataLoader(
    TensorDataset(X_test_t, y_test_t),
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=0,
)

print(f"Train batches: {len(train_loader)}, Test batches: {len(test_loader)}")

# ---------------------------
# MLP model (binary: 2 outputs)
# ---------------------------
class MLP(nn.Module):
    def __init__(self, input_dim, num_classes):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 512),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, x):
        return self.net(x)


model = MLP(X_train_t.shape[1], num_classes=2).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(
    model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY
)

print("Model:", model)
print("Final layer:", model.net[-1])

# ---------------------------
# Train / test functions
# ---------------------------
def train_one_epoch(model, device, loader, optimizer, epoch, criterion):
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for batch_idx, (inputs, targets) in enumerate(loader):
        inputs, targets = inputs.to(device), targets.to(device)

        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()

        _, predicted = torch.max(outputs, dim=1)
        total += targets.size(0)
        correct += (predicted == targets).sum().item()
        running_loss += loss.item()

    epoch_loss = running_loss / len(loader)
    epoch_acc = 100.0 * correct / total
    print(
        f"Epoch {epoch}: Train Loss={epoch_loss:.4f}, "
        f"Train Acc={epoch_acc:.2f}%"
    )
    return epoch_loss, epoch_acc


@torch.no_grad()
def evaluate(model, device, loader, criterion=None):
    model.eval()
    correct = 0
    total = 0
    running_loss = 0.0

    for inputs, targets in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        outputs = model(inputs)
        _, predicted = torch.max(outputs, dim=1)
        total += targets.size(0)
        correct += (predicted == targets).sum().item()

        if criterion is not None:
            loss = criterion(outputs, targets)
            running_loss += loss.item()

    acc = 100.0 * correct / total
    avg_loss = running_loss / len(loader) if criterion is not None else None
    if avg_loss is not None:
        print(f"Val Loss={avg_loss:.4f}, Val Acc={acc:.2f}%")
    else:
        print(f"Val Acc={acc:.2f}%")
    return acc, avg_loss


# ---------------------------
# Training loop with early stopping
# ---------------------------
torch.backends.cudnn.benchmark = True

best_acc = 0.0
patience = PATIENCE
epochs_without_improve = 0

history = {"train_acc": [], "test_acc": []}

for epoch in range(1, EPOCHS + 1):
    train_loss, train_acc = train_one_epoch(
        model, DEVICE, train_loader, optimizer, epoch, criterion
    )
    test_acc, test_loss = evaluate(model, DEVICE, test_loader, criterion)

    history["train_acc"].append(train_acc)
    history["test_acc"].append(test_acc)

    print(
        f"Epoch {epoch} summary: "
        f"Train Acc={train_acc:.2f}%, Test Acc={test_acc:.2f}%, "
        f"Best={best_acc:.2f}%"
    )

    if test_acc > best_acc:
        best_acc = test_acc
        epochs_without_improve = 0
        torch.save(model.state_dict(), "best_size_classifier.pth")
        print(f"--> New best model saved (Test Acc={best_acc:.2f}%)")
    else:
        epochs_without_improve += 1
        print(f"No improvement for {epochs_without_improve} epoch(s)")

    print("-" * 60)

    if epochs_without_improve >= patience:
        print(
            f"Early stopping triggered after {epoch} epochs. "
            f"Best Test Acc={best_acc:.2f}%"
        )
        break

print("Training complete. Best Test Accuracy:", best_acc)
