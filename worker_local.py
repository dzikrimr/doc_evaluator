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

# ===================== KEYWORDS =====================
KEYWORDS = {
    "dokumenAdmin": [
        "ktp", "npwp", "akta", "domisili", "siup", "rekening", "identitas",
        "ktppribadi", "npwpperusahaan", "suratdomisili", "aktaperusahaan",
        "ktppemilik", "ktpkaryawan", "izin", "kelengkapan"
    ],
    "dokumenLegal": [
        "izin", "legalitas", "sertifikat", "aktapendirian", "notaris", "operasional",
        "lingkungan", "gangguan", "pemerintah", "perijinan", "legal", "izinusaha",
        "akta", "perizinan", "pengesahan"
    ],
    "dokumenTeknikal": [
        "spesifikasi", "rencana", "desain", "workflow", "diagram", "analisis",
        "prosedur", "peta", "tekni", "teknis", "engineering", "perhitungan",
        "gambar", "layout", "manual", "sistem", "jadwal"
    ],
    "dokumenFinansial": [
        "keuangan", "rupiah", "idr", "usd", "euro", "jumlah", "total", "neraca",
        "labarugi", "aruskas", "saldo", "pembayaran", "utang", "piutang",
        "dividen", "modal", "deposit", "investasi", "laporan", "invoice",
        "faktur", "buku", "audit", "pajak", "npwp", "bukti", "realisasi"
    ]
}

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

    if pred.lower() == "approved":
        reason = "Dokumen memenuhi syarat dan lengkap."
    else:
        reason = "Dokumen tidak lengkap atau tidak valid."

    return pred.upper(), reason

def check_keywords(doc_texts: dict, min_match=1):
    """
    Periksa setiap dokumen apakah mengandung minimal min_match keyword.
    """
    missing = {}
    for key, keywords in KEYWORDS.items():
        text = doc_texts.get(key, "").lower()
        match_count = sum(1 for k in keywords if k in text)
        if match_count < min_match:
            missing[key] = [k for k in keywords if k not in text]
    return missing

def send_email(to_email: str, vendor_name: str, approved: bool):
    if not SENDGRID_API_KEY:
        logger.warning("SENDGRID_API_KEY belum di-set")
        return False

    if approved:
        subject = "Pendaftaran Vendor Diterima ✅"
        body = f"""Halo {vendor_name},

Selamat! Pendaftaran vendor Anda telah berhasil diterima. Terima kasih telah melengkapi semua dokumen.

Anda dapat melihat status dan informasi lebih lanjut melalui halaman berikut:
[Dashboard Vendor](https://pier-pelindo.vercel.app/dashboard-vendor)

Salam hangat,
Tim PT Integration Logistic Cipta Solusi
"""
    else:
        subject = "Pendaftaran Vendor Belum Diterima ❌"
        body = f"""Halo {vendor_name},

Pendaftaran vendor Anda belum bisa kami terima karena dokumen yang dikirimkan tidak lengkap atau tidak valid.

Silakan periksa dan lengkapi dokumen Anda melalui halaman registrasi vendor berikut:
[Perbarui Pendaftaran Anda](https://pier-pelindo.vercel.app/vendor-registration)

Terima kasih atas perhatian dan kerjasamanya.

Salam hangat,
Tim PT Integration Logistic Cipta Solusi
"""

    msg = Mail(
        from_email=Email(SENDER_EMAIL),
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", body)
    )

    try:
        SendGridAPIClient(SENDGRID_API_KEY).send(msg)
        logger.info(f"Email terkirim ke {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False

# ===================== PROCESS =====================
def evaluate_vendor(doc_data: dict):
    document_urls = {
        "dokumenAdmin": doc_data.get("dokumenAdmin"),
        "dokumenLegal": doc_data.get("dokumenLegal"),
        "dokumenTeknikal": doc_data.get("dokumenTeknikal"),
        "dokumenFinansial": doc_data.get("dokumenFinansial")
    }
    doc_texts = {}
    all_text = ""
    downloaded_files = []

    for key, url in document_urls.items():
        if url:
            path = download_from_url(url)
            if path:
                downloaded_files.append(path)
                text = extract_text_from_pdf(path)
                doc_texts[key] = text
                all_text += text + "\n"

    if not all_text.strip():
        return "REJECTED", "Tidak ada teks dari dokumen"

    # cek keywords dengan threshold 1
    missing = check_keywords(doc_texts, min_match=1)
    if missing:
        decision = "REJECTED"
        reason = "Dokumen kurang lengkap"
    else:
        # pakai AI sebagai evaluasi tambahan
        decision, reason = evaluate_text(all_text)

    # Hapus file sementara
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

        # Update status dan alasan AI di Firestore
        db.collection("vendor_registrations").document(doc_snapshot.id).update({
            "status": decision.lower(),
            "aiReason": reason,
            "processedAt": firestore.SERVER_TIMESTAMP
        })

        # Kirim email (tanpa reason)
        if vendor_email:
            send_email(vendor_email, vendor_name, decision == "APPROVED")

# ===================== MAIN LOOP =====================
if __name__ == "__main__":
    logger.info("🔥 [Worker] Vendor Registration Local Processor Started")
    while True:
        try:
            process_pending_documents()
            time.sleep(60)  # cek setiap 1 menit
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Worker cycle error: {e}")
            time.sleep(60)
