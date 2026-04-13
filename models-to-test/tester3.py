import pandas as pd
import numpy as np

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

# ---------------------------
# Config
# ---------------------------
CSV_PATH = "output.csv"
BATCH_SIZE = 32
LR = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 50
PATIENCE = 7
RANDOM_STATE = 42

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device:", DEVICE)

# ---------------------------
# Load & preprocess data
# ---------------------------
df = pd.read_csv(CSV_PATH)

def get_prompt_category(session):
    """Map session number (1-24) to prompt category"""
    if 1 <= session <= 4:
        return "Text Summarization"
    elif 5 <= session <= 8:
        return "Code Generation"
    elif 9 <= session <= 12:
        return "Math/Algorithmic"
    elif 13 <= session <= 16:
        return "Malware/Adversarial"
    elif 17 <= session <= 20:
        return "Logical Reasoning"
    elif 21 <= session <= 24:
        return "Technical Explanation"
    return "Unknown"

df['prompt_category'] = df['session'].apply(get_prompt_category)

print("Prompt category distribution:")
print(df['prompt_category'].value_counts())

label_encoder = LabelEncoder()
df['label'] = label_encoder.fit_transform(df['prompt_category'])

print(f"\nNumber of classes: {len(label_encoder.classes_)}")
print("Classes:", label_encoder.classes_)

id_cols = ["filename", "model", "session"]
drop_cols = id_cols + ["prompt_category", "label"]
feature_cols = [c for c in df.columns if c not in drop_cols]
print(f"\nNum features: {len(feature_cols)}")
print("Features:", feature_cols)

X_np = df[feature_cols].to_numpy(dtype=np.float32)
y_np = df['label'].to_numpy(dtype=np.int64)

print(f"\nX shape: {X_np.shape}, y shape: {y_np.shape}")

X_train, X_test, y_train, y_test = train_test_split(
    X_np,
    y_np,
    test_size=0.2,
    stratify=y_np,
    random_state=RANDOM_STATE,
)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

print("\n--- Random Forest ---")
rf = RandomForestClassifier(n_estimators=500, max_depth=15, random_state=RANDOM_STATE, n_jobs=-1)
rf.fit(X_train_scaled, y_train)
rf_acc = rf.score(X_test_scaled, y_test)
print(f"Random Forest accuracy: {rf_acc*100:.2f}%")

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

from sklearn.metrics import classification_report, confusion_matrix

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
