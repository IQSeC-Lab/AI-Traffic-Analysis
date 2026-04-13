import os
import json
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler



def load_json_data(folder):
    X, y_family, y_size = [], [], []

    for file in os.listdir(folder):
        if not file.endswith(".json"):
            continue

        with open(os.path.join(folder, file)) as f:
            data = json.load(f)

        for sample in data:   # 🔥 REQUIRED
            X.append(sample["features"])
            y_family.append(sample["family"])
            y_size.append(sample["size"])

    return np.array(X), np.array(y_family), np.array(y_size)

def train_model(X, y, title):
    print(f"\n===== {title} =====")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    import numpy as np

    print(sorted(set(y_train)))
    print(sorted(set(y_test)))
    print("unique overall:", sorted(set(list(y_train) + list(y_test))))
    clf = RandomForestClassifier(
        n_estimators=200,
        n_jobs=-1,
        random_state=42
    )

    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)

    print("Accuracy:", accuracy_score(y_test, y_pred))
    print(classification_report(y_test, y_pred))
    from sklearn.metrics import confusion_matrix

    cm = confusion_matrix(y_test, y_pred)
    print(cm)


def main():
    X, y_family, y_size = load_json_data("json_data3/")
    
    # -------------------------
    # BINARY (7B vs 14B)
    # -------------------------
    # train_model(X, y_size, "Binary Classification (7B vs 14B)")

    # -------------------------
    # MULTICLASS (families)
    # -------------------------
    train_model(X, y_family, "Multiclass (Families)")


if __name__ == "__main__":
    main()