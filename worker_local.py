import firebase_admin
from firebase_admin import credentials, firestore, storage
import os, tempfile, logging, time, pickle
from urllib.parse import unquote
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from extract_text import extract_text_from_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== FIREBASE =====================
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {"storageBucket": "pier-pelindo.firebasestorage.app"})
db = firestore.client()
bucket = storage.bucket()

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDER_EMAIL = "pelindoierepository@gmail.com"

# ===================== LOAD MODEL =====================
with open("models/classifier.pkl", "rb") as f:
    data = pickle.load(f)
vectorizer, clf = data["vectorizer"], data["model"]

# ===================== HELPERS =====================
def download_from_url(url: str) -> str:
    try:
        if "firebasestorage.googleapis.com" in url:
            obj = unquote(url.split("/o/")[1].split("?")[0])
            blob = bucket.blob(obj)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            blob.download_to_filename(tmp.name)
            tmp.close()
            return tmp.name
        return None
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None

def evaluate_text(text: str):
    X = vectorizer.transform([text])
    pred = clf.predict(X)[0]
    reason = text[:500] if text else "Tidak ada teks dari dokumen"
    return pred.upper(), reason

def send_email(to_email: str, vendor_name: str, decision: str, reason: str):
    if not SENDGRID_API_KEY:
        logger.warning("SENDGRID_API_KEY belum di-set")
        return False
    body = f"Dear {vendor_name},\n\nDecision: {decision}\nReason: {reason}\n\nBest regards,\nPT Integration Logistic Cipta Solusi Team"
    msg = Mail(from_email=Email(SENDER_EMAIL),
               to_emails=To(to_email),
               subject=f"Vendor Registration {decision}",
               plain_text_content=Content("text/plain", body))
    try:
        SendGridAPIClient(SENDGRID_API_KEY).send(msg)
        logger.info(f"Email terkirim ke {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False

# ===================== PROCESS =====================
def evaluate_vendor(doc_data: dict):
    document_urls = [
        doc_data.get("dokumenAdmin"),
        doc_data.get("dokumenLegal"),
        doc_data.get("dokumenTeknikal"),
        doc_data.get("dokumenFinansial")
    ]
    all_text = ""
    downloaded_files = []

    for url in document_urls:
        if url:
            path = download_from_url(url)
            if path:
                downloaded_files.append(path)
                all_text += extract_text_from_pdf(path) + "\n"

    if not all_text.strip():
        return "REJECTED", "Tidak ada teks dari dokumen"

    decision, reason = evaluate_text(all_text)

    for f in downloaded_files:
        try: os.remove(f)
        except: pass

    return decision, reason

def process_pending_documents():
    docs = db.collection("vendor_registrations").where("status", "==", "pending").stream()
    for doc_snapshot in docs:
        doc_data = doc_snapshot.to_dict()
        vendor_name = doc_data.get("namaVendor", "Vendor")
        vendor_email = doc_data.get("emailVendor")
        
        decision, reason = evaluate_vendor(doc_data)
        
        db.collection("vendor_registrations").document(doc_snapshot.id).update({
            "status": decision.lower(),
            "aiReason": reason,
            "processedAt": firestore.SERVER_TIMESTAMP
        })

        if vendor_email:
            send_email(vendor_email, vendor_name, decision, reason)

# ===================== MAIN LOOP =====================
if __name__ == "__main__":
    logger.info("🔥 [Worker] Vendor Registration Local Processor Started")
    while True:
        try:
            process_pending_documents()
            time.sleep(60)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Worker cycle error: {e}")
            time.sleep(60)
