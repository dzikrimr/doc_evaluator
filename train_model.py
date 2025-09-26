import os, pickle
from extract_text import extract_text_from_pdf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import SVC

DATASET_DIR = "dataset"
MODEL_PATH = "models/classifier.pkl"

texts = []
labels = []

for label in ["approved", "rejected"]:
    folder = os.path.join(DATASET_DIR, label)
    for file in os.listdir(folder):
        if file.endswith(".pdf"):
            path = os.path.join(folder, file)
            text = extract_text_from_pdf(path)
            if text.strip():
                texts.append(text)
                labels.append(label)

vectorizer = TfidfVectorizer(max_features=5000)
X = vectorizer.fit_transform(texts)
clf = SVC(probability=True)
clf.fit(X, labels)

os.makedirs("models", exist_ok=True)
with open(MODEL_PATH, "wb") as f:
    pickle.dump({"vectorizer": vectorizer, "model": clf}, f)

print("✅ Model trained and saved to", MODEL_PATH)
