import os
import json
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay


def load_json_data(folder):
    X, y_family, y_size, y_model = [], [], [], []

    for file in os.listdir(folder):
        if not file.endswith(".json"):
            continue

        with open(os.path.join(folder, file)) as f:
            data = json.load(f)

        for sample in data:
            X.append(sample["features"])
            y_family.append(sample["family"])
            y_size.append(sample["size"])
            y_model.append(sample["model"])

    return (
        np.array(X),
        np.array(y_family),
        np.array(y_size),
        np.array(y_model)
    )

def train_model(X, y, title):
    print(f"\n===== {title} =====")

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=400,
        n_jobs=-1,
        random_state=42
    )

    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)

    print("Accuracy:", accuracy_score(y_test, y_pred))
    print(classification_report(y_test, y_pred))
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred))

def main():
    # X, y_family, y_size, y_model = load_json_data("json_data/")
    X, y_family, y_size, y_model = load_json_data("json_data/")

    print("\n--- DATASET INFO ---")
    print("Families:", np.unique(y_family))
    print("Num families:", len(np.unique(y_family)))

    print("Models:", np.unique(y_model))
    print("Num models:", len(np.unique(y_model)))

    print("Sizes:", np.unique(y_size))
    print("--------------------")

    # 🔥 MODEL-LEVEL (THIS IS WHAT YOU WANT)
    train_model(X, y_model, "Multiclass (Models)")


if __name__ == "__main__":
    main()