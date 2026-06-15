#!/usr/bin/env python3
"""
Random Forest Prompt Category Classifier
Adapted from model-family classifier to prompt-category classifier.
Supports model-agnostic training with leave-one-model-out validation.
"""

import os
import json
import glob
import numpy as np
from collections import defaultdict
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import (
    classification_report, accuracy_score,
    confusion_matrix, ConfusionMatrixDisplay
)
import matplotlib.pyplot as plt


# -------------------------------------------------------------------
# DATA LOADING (NEW FORMAT)
# -------------------------------------------------------------------
def load_json_data(folder):
    """
    Load JSON files with prompt category labels.

    Expected JSON format per sample:
    {
        "features": [36 or 42 floats],
        "prompt_idx": 4,
        "prompt_category": "code_generation",
        "model_name": "zephyr-7b-beta"
    }

    Returns:
        X: feature matrix
        y_prompt: prompt category labels (6 classes)
        y_model: model names (for group-based splits)
        models_list: list of model names per sample
    """
    X, y_prompt, y_model = [], [], []

    json_files = glob.glob(os.path.join(folder, "*.json"))
    print(f"Found {len(json_files)} JSON files")

    for filepath in json_files:
        with open(filepath) as f:
            data = json.load(f)

        for sample in data:
            X.append(sample["features"])
            y_prompt.append(sample.get("prompt_category", "unknown"))
            y_model.append(sample.get("model_name", "unknown"))

    return np.array(X), np.array(y_prompt), np.array(y_model)


# -------------------------------------------------------------------
# STANDARD TRAIN/TEST SPLIT
# -------------------------------------------------------------------
def train_model_standard(X, y, title="Prompt Category Classification"):
    """Standard stratified train/test split."""
    print(f"\n{'='*60}")
    print(f"===== {title} =====")
    print(f"{'='*60}")

    # Encode labels
    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    # Stratified split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc,
        test_size=0.2,
        random_state=42,
        stratify=y_enc
    )

    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train
    clf = RandomForestClassifier(
        n_estimators=400,
        max_depth=20,
        min_samples_split=5,
        class_weight="balanced",
        n_jobs=-1,
        random_state=42
    )

    clf.fit(X_train_scaled, y_train)
    y_pred = clf.predict(X_test_scaled)

    # Results
    acc = accuracy_score(y_test, y_pred)
    print(f"Accuracy: {acc:.4f}")
    print(f"\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    print("Confusion Matrix:")
    print(cm)

    # Plot
    fig, ax = plt.subplots(figsize=(8, 6))
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=le.classes_)
    disp.plot(ax=ax, xticks_rotation=45)
    plt.title(f"{title} (Acc: {acc:.3f})")
    plt.tight_layout()
    plt.savefig("confusion_matrix_standard.png", dpi=150)
    print("\nSaved confusion matrix to confusion_matrix_standard.png")

    return clf, scaler, le


# -------------------------------------------------------------------
# LEAVE-ONE-MODEL-OUT CROSS-VALIDATION
# -------------------------------------------------------------------
def train_model_leave_one_out(X, y, models, title="Leave-One-Model-Out"):
    """
    Leave-one-model-out cross-validation.
    Tests generalization to unseen models.
    """
    print(f"\n{'='*60}")
    print(f"===== {title} =====")
    print(f"{'='*60}")

    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    unique_models = np.unique(models)
    print(f"Total models: {len(unique_models)}")
    print(f"Categories: {le.classes_}")

    fold_accuracies = []
    all_y_true = []
    all_y_pred = []

    for test_model in unique_models:
        # Split by model
        train_mask = models != test_model
        test_mask = models == test_model

        X_train, X_test = X[train_mask], X[test_mask]
        y_train, y_test = y_enc[train_mask], y_enc[test_mask]

        if len(X_test) == 0:
            continue

        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train
        clf = RandomForestClassifier(
            n_estimators=400,
            max_depth=20,
            min_samples_split=5,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42
        )

        clf.fit(X_train_scaled, y_train)
        y_pred = clf.predict(X_test_scaled)

        # Collect for aggregate CM
        all_y_true.extend(y_test)
        all_y_pred.extend(y_pred)

        acc = accuracy_score(y_test, y_pred)
        fold_accuracies.append(acc)

        print(f"\nHeld-out: {test_model:30s} | Test: {len(y_test):4d} | Acc: {acc:.3f}")

    # Aggregate results
    avg_acc = np.mean(fold_accuracies)
    std_acc = np.std(fold_accuracies)

    print(f"\n{'='*60}")
    print(f"Average accuracy: {avg_acc:.3f} (+/- {std_acc:.3f})")
    print(f"{'='*60}")

    # Aggregate confusion matrix
    cm = confusion_matrix(all_y_true, all_y_pred)
    print(f"\nAggregate Confusion Matrix:")
    print(cm)

    fig, ax = plt.subplots(figsize=(8, 6))
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=le.classes_)
    disp.plot(ax=ax, xticks_rotation=45)
    plt.title(f"{title} (Avg Acc: {avg_acc:.3f})")
    plt.tight_layout()
    plt.savefig("confusion_matrix_lomo.png", dpi=150)
    print("\nSaved confusion matrix to confusion_matrix_lomo.png")

    return fold_accuracies, le


# -------------------------------------------------------------------
# FEATURE IMPORTANCE
# -------------------------------------------------------------------
def analyze_feature_importance(X, y, feature_names=None):
    """Train and report feature importances."""
    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=15,
        n_jobs=-1,
        random_state=42
    )
    clf.fit(X_scaled, y_enc)

    importances = clf.feature_importances_
    indices = np.argsort(importances)[::-1]

    # Default feature names
    if feature_names is None:
        feature_names = [f"feat_{i}" for i in range(X.shape[1])]

    print(f"\n{'='*60}")
    print("TOP 15 FEATURE IMPORTANCES")
    print(f"{'='*60}")
    for i in range(min(15, len(feature_names))):
        idx = indices[i]
        print(f"{i+1:2d}. {feature_names[idx]:25s} {importances[idx]:.4f}")

    return importances


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main():
    # Load data
    print("Loading data...")
    X, y_prompt, y_model = load_json_data("json_data_prompts/")

    print(f"\n--- DATASET INFO ---")
    print(f"Total samples: {len(X)}")
    print(f"Feature dimensions: {X.shape[1]}")
    print(f"Prompt categories: {np.unique(y_prompt)}")
    print(f"Num categories: {len(np.unique(y_prompt))}")
    print(f"Models: {len(np.unique(y_model))}")
    print(f"--------------------")

    # Category distribution
    print(f"\nCategory distribution:")
    unique, counts = np.unique(y_prompt, return_counts=True)
    for cat, count in zip(unique, counts):
        print(f"  {cat:25s}: {count:5d} ({count/len(y_prompt)*100:.1f}%)")

    # Feature importance analysis
    feature_names = [
        "iat_mean", "iat_std", "iat_min", "iat_max",
        "iat_p25", "iat_p50", "iat_p75", "iat_skew", "iat_kurt",
        "size_mean", "size_std", "size_min", "size_max",
        "size_p25", "size_p50", "size_p75",
        "packet_rate", "burstiness",
        "entropy_iat", "entropy_size",
        "dt_diff_mean", "dt_diff_std", "dt_acc_mean",
        "corr_iat_size", "interaction", "max_burst_rate",
        # Directional features (if present)
        "resp_mean", "resp_std", "resp_max",
        "resp_req_ratio", "resp_burstiness", "resp_p90", "resp_p95",
        "resp_count_ratio"
    ][:X.shape[1]]

    analyze_feature_importance(X, y_prompt, feature_names)

    # Standard split (quick check)
    print(f"\n{'='*60}")
    print("STANDARD STRATIFIED SPLIT")
    print(f"{'='*60}")
    train_model_standard(X, y_prompt)

    # Leave-one-model-out (real test)
    print(f"\n{'='*60}")
    print("LEAVE-ONE-MODEL-OUT VALIDATION")
    print(f"{'='*60}")
    train_model_leave_one_out(X, y_prompt, y_model)


if __name__ == "__main__":
    main()
