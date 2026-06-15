import os
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

# ---------------------------
# Config
# ---------------------------
JSON_FOLDER = "./json_data"  # <-- set this to your folder
BATCH_SIZE = 32
LR = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 50
PATIENCE = 7
RANDOM_STATE = 42

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", DEVICE)

def load_json_data(folder):
    X, y_family, y_size, y_model = [], [], [], []

    for file in os.listdir(folder):
        if not file.endswith(".json"):
            continue

        with open(os.path.join(folder, file)) as f:
            data = json.load(f)

        # 🔥 handle BOTH formats
        if isinstance(data, dict):
            data = [data]

        for sample in data:
            X.append(sample["features"])
            y_family.append(sample["family"])
            y_size.append(sample["size"])
            y_model.append(sample["model"])

    X = np.array(X, dtype=np.float32)

    return X, np.array(y_family), np.array(y_size), np.array(y_model)
# Load data
X_raw, y_family, y_size, y_model = load_json_data(JSON_FOLDER)

X_raw, y_family, y_size, y_model = load_json_data(JSON_FOLDER)

# --- DEBUG: inspect raw shape and first few samples ---
print("X_raw dtype:", X_raw.dtype)
print("X_raw ndim:", X_raw.ndim)
print("X_raw shape:", X_raw.shape)
print("First 3 raw feature entries:", X_raw[:3])
print("First y_family entries:", y_family[:3])


# Choose which label to predict (example: predict 'family')
# You can switch to y_size or y_model by changing the variable below.
label_array = y_family  # <-- change this to y_size or y_model as needed
label_name = "family"   # for reporting purposes

print(f"\nLoaded {X_raw.shape[0]} samples with {X_raw.shape[1]} features each.")
print(f"Using label: {label_name}")

# Encode string labels to integers (if needed)
label_encoder = LabelEncoder()
y_encoded = label_encoder.fit_transform(label_array)
num_classes = len(label_encoder.classes_)
print(f"\nNumber of classes: {num_classes}")
print("Classes:", label_encoder.classes_)

# ---------------------------
# Feature preprocessing (same as before)
# ---------------------------
# Assuming features are already numeric; if they come as lists, X_raw is ready.
# If you have mixed types, you may need additional encoding here.
X_np = X_raw  # already float32 from loader
y_np = y_encoded

print(f"\nX shape: {X_np.shape}, y shape: {y_np.shape}")

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X_np,
    y_np,
    test_size=0.2,
    stratify=y_np,
    random_state=RANDOM_STATE,
)

# Standard scaling
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

print("\n--- Random Forest Baseline ---")
rf = RandomForestClassifier(n_estimators=500, max_depth=15, random_state=RANDOM_STATE, n_jobs=-1)
rf.fit(X_train_scaled, y_train)
rf_acc = rf.score(X_test_scaled, y_test)
print(f"Random Forest accuracy: {rf_acc*100:.2f}%")

# ---------------------------
# Convert to PyTorch tensors
# ---------------------------
X_train_t = torch.tensor(X_train_scaled, dtype=torch.float32)
y_train_t = torch.tensor(y_train, dtype=torch.long)
X_test_t = torch.tensor(X_test_scaled, dtype=torch.float32)
y_test_t = torch.tensor(y_test, dtype=torch.long)

print("\nTrain tensor shape:", X_train_t.shape)
print("Test tensor shape:", X_test_t.shape)
print("y_train range:", y_train_t.min().item(), "to", y_train_t.max().item())

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
# MLP model (multiclass)
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
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, num_classes),
        )

    def forward(self, x):
        return self.net(x)

num_classes = len(label_encoder.classes_)
model = MLP(X_train_t.shape[1], num_classes=num_classes).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(
    model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY
)

print("\nModel:", model)
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
patience_counter = 0

for epoch in range(1, EPOCHS + 1):
    train_loss, train_acc = train_one_epoch(
        model, DEVICE, train_loader, optimizer, epoch, criterion
    )
    test_acc, test_loss = evaluate(model, DEVICE, test_loader, criterion)
    print(
        f"Epoch {epoch} summary: "
        f"Train Acc={train_acc:.2f}%, Test Acc={test_acc:.2f}%, "
        f"Best={best_acc:.2f}%"
    )
    if test_acc > best_acc:
        best_acc = test_acc
        patience_counter = 0
        torch.save({
            'model_state_dict': model.state_dict(),
            'scaler': scaler,
            'label_encoder': label_encoder,
            'num_classes': num_classes,
        }, "best_prompt_classifier.pth")
        print(f"--> New best model saved (Test Acc={best_acc:.2f}%)")
    else:
        patience_counter += 1
        print(f"No improvement for {patience_counter} epoch(s)")
    print("-" * 60)
    if patience_counter >= PATIENCE:
        print(
            f"Early stopping triggered after {epoch} epochs. "
            f"Best Test Acc={best_acc:.2f}%"
        )
        break

print("\nTraining complete. Best Test Accuracy:", best_acc)

# ---------------------------
# Load best model and show detailed results
# ---------------------------
checkpoint = torch.load("best_prompt_classifier.pth", weights_only=False)
model.load_state_dict(checkpoint['model_state_dict'])

model.eval()
all_preds = []
all_labels = []

with torch.no_grad():
    for inputs, targets in test_loader:
        inputs = inputs.to(DEVICE)
        outputs = model(inputs)
        _, predicted = torch.max(outputs, 1)
        all_preds.extend(predicted.cpu().numpy())
        all_labels.extend(targets.numpy())

print("\n" + "="*60)
print("Classification Report:")
print("="*60)
print(classification_report(
    all_labels, 
    all_preds, 
    target_names=label_encoder.classes_,
    zero_division=0
))

print("\nConfusion Matrix:")
print(confusion_matrix(all_labels, all_preds))
