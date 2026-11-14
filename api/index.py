from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import uuid
import hmac
from datetime import datetime, timezone
from urllib.parse import urlencode
from dotenv import load_dotenv
from functools import wraps
from supabase import create_client, Client
from google import genai

load_dotenv()

_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_base_dir, 'templates'))
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)

# =====================
# CONFIG
# =====================
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "").strip()
SUPABASE_URL        = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY", "").strip()
GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET= os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback").strip()

PASAL_API_URL = "https://pasal.id/api/v1/search"
PASAL_API_TOKEN = os.getenv("PASAL_API_TOKEN", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-2.5-flash-lite").split(",")
    if model.strip() and model.strip() != GEMINI_MODEL
]

# Inisialisasi Gemini SDK baru
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

# Supabase client (lazy init agar tidak crash di Vercel jika env var belum diset)
_supabase_client: Client = None

def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise RuntimeError("SUPABASE_URL dan SUPABASE_ANON_KEY belum diset di environment variables!")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _supabase_client

# =====================
# AUTH DECORATOR
# =====================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

# =====================
# FUNGSI CARI PASAL
# =====================
def cari_pasal(kata_kunci):
    if not PASAL_API_TOKEN:
        return "Database pasal belum dikonfigurasi: PASAL_API_TOKEN tidak tersedia."
    try:
        response = requests.get(
            PASAL_API_URL,
            params={"q": kata_kunci, "limit": 5},
            headers={"Authorization": f"Bearer {PASAL_API_TOKEN}"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        hasil = ""
        for item in data.get("results", [])[:3]:
            work = item.get("work") or {}
            hasil += f"\n📌 {work.get('title', 'Peraturan tanpa judul')}"
            hasil += f" ({work.get('type', '')} {work.get('number', '')}/{work.get('year', '')})\n"
            hasil += f"Status: {work.get('status', 'tidak diketahui')}\n"
            hasil += f"Referensi: {item.get('url', '')}\n"
            for pasal in item.get("matching_pasals", [])[:3]:
                hasil += f"Pasal {pasal.get('pasal', '')}: {pasal.get('url', '')}\n"
        if not hasil:
            saran = data.get("did_you_mean") or []
            if saran:
                return "Tidak ditemukan hasil. Saran: " + ", ".join(
                    (s.get("work") or {}).get("title", "") for s in saran[:5]
                )
        return hasil if hasil else "Tidak ditemukan pasal yang relevan."
    except Exception as e:
        print(f"[cari_pasal error] {e}")
        return "Mohon maaf, saat ini asisten tidak dapat mengakses database pasal hukum. Silakan coba lagi nanti."

# =====================
# FUNGSI TANYA KE GEMINI
# =====================
def tanya_gemini(pertanyaan, konteks_pasal, profil_user=None):
    if _gemini_client is None:
        return "Sistem AI belum dikonfigurasi (API Key kosong)."

    info_profil = ""
    if profil_user and isinstance(profil_user, dict):
        kw = profil_user.get("kewarganegaraan", "")
        pk = profil_user.get("pekerjaan", "")
        if kw or pk:
            info_profil = f"\nInformasi latar belakang pengguna:\n- Kewarganegaraan: {kw or 'tidak disebutkan'}\n- Pekerjaan: {pk or 'tidak disebutkan'}\nSesuaikan penjelasan hukum agar relevan dengan konteks pengguna jika diperlukan.\n"

    prompt = f"""Kamu adalah asisten hukum Indonesia yang membantu 
masyarakat memahami hukum dengan bahasa yang mudah dimengerti.
Selalu cantumkan referensi pasal yang relevan.
Ingatkan pengguna bahwa jawabanmu bukan nasihat hukum resmi 
dan sarankan konsultasi ke pengacara untuk kasus spesifik.
{info_profil}
Pertanyaan: {pertanyaan}

Pasal-pasal yang relevan dari database hukum Indonesia:
{konteks_pasal}

Catatan penting: API Pasal.id menyediakan metadata dan tautan referensi, bukan teks lengkap
peraturan. Jangan mengarang isi pasal. Jika teks pasal tidak tersedia dalam konteks,
jelaskan keterbatasan tersebut dan arahkan pengguna ke tautan referensi yang tersedia.

Tolong jawab pertanyaan di atas berdasarkan informasi yang benar-benar tersedia."""

    try:
        last_error = None
        for model_name in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
            try:
                response = _gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and getattr(response, "text", None):
                    return response.text
            except Exception as e:
                last_error = e
                print(f"[Gemini model error] {model_name}: {e}")
                continue
            
        if last_error:
            raise last_error
        return "Maaf, AI tidak memberikan jawaban. Silakan coba lagi."
    except Exception as e:
        print(f"[Gemini SDK Error] {e}")
        return "Terjadi gangguan pada asisten AI. Silakan coba lagi nanti."

# =====================
# HELPER SUPABASE USER
# =====================
def upsert_user(email, name, avatar=None, provider="google"):
    """Simpan atau update user ke tabel 'users' di Supabase."""
    try:
        get_supabase().table("users").upsert({
            "email": email,
            "name": name,
            "avatar": avatar,
            "provider": provider,
        }, on_conflict="email").execute()
        return True
    except Exception as e:
        print(f"[Supabase upsert error] {e}")
        return False

# =====================
# ROUTES — PAGES
# =====================
@app.route("/")
def landing():
    return render_template("prototype.html")

@app.route("/prototype")
def prototype():
    return render_template("prototype.html")

@app.route("/chat")
@login_required
def chat():
    if not session.get("user", {}).get("onboarding"):
        return redirect(url_for("onboarding_page"))
    return render_template("index.html", user=session["user"])

@app.route("/onboarding")
@login_required
def onboarding_page():
    if session.get("user", {}).get("onboarding"):
        return redirect(url_for("chat"))
    return render_template("onboarding.html")

@app.route("/api/onboarding", methods=["POST"])
@login_required
def save_onboarding():
    data = request.get_json(silent=True) or {}
    if "user" in session:
        session["user"]["onboarding"] = data
        session.modified = True
    email = session.get("user", {}).get("email")
    if email:
        try:
            get_supabase().table("users").update({"onboarding": data}).eq("email", email).execute()
        except Exception as e:
            print(f"[Supabase onboarding note] {e}")
    return jsonify({"success": True, "redirect": url_for("chat")})

@app.route("/login")
def login_page():
    if "user" in session:
        if not session["user"].get("onboarding"):
            return redirect(url_for("onboarding_page"))
        return redirect(url_for("chat"))
    return render_template("login.html")

@app.route("/register")
def register_page():
    return redirect(url_for("login_page"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

# =====================
# ROUTES — EMAIL AUTH
# =====================
@app.route("/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json(silent=True) or {}
    name  = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "Semua field wajib diisi."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password minimal 6 karakter."}), 400

    try:
        # Cek apakah email sudah terdaftar
        existing = get_supabase().table("users").select("email").eq("email", email).execute()
        if existing.data:
            return jsonify({"error": "Email sudah terdaftar. Silakan login."}), 409

        # Hash password sederhana pakai bcrypt
        import bcrypt
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        get_supabase().table("users").insert({
            "email": email,
            "name": name,
            "password_hash": hashed,
            "provider": "email",
        }).execute()

        session["user"] = {"email": email, "name": name, "avatar": None}
        return jsonify({"success": True, "redirect": url_for("chat")})
    except Exception as e:
        print(f"[Register error] {e}")
        return jsonify({"error": "Terjadi kesalahan. Coba lagi."}), 500


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True) or {}
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email dan password wajib diisi."}), 400

    try:
        import bcrypt
        result = get_supabase().table("users").select("*").eq("email", email).execute()
        if not result.data:
            return jsonify({"error": "Email tidak ditemukan."}), 404

        user = result.data[0]

        if user.get("provider") != "email":
            return jsonify({"error": f"Akun ini terdaftar via {user['provider']}. Gunakan login Google."}), 400

        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return jsonify({"error": "Password salah."}), 401

        session["user"] = {
            "email": user["email"],
            "name":  user["name"],
            "avatar": user.get("avatar"),
        }
        return jsonify({"success": True, "redirect": url_for("chat")})
    except Exception as e:
        print(f"[Login error] {e}")
        return jsonify({"error": "Terjadi kesalahan. Coba lagi."}), 500

# =====================
# ROUTES — GOOGLE OAUTH
# =====================
@app.route("/auth/google")
def auth_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        return "GOOGLE_CLIENT_ID atau GOOGLE_REDIRECT_URI belum diset!", 500

    state = str(uuid.uuid4())
    session["oauth_state"] = state

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)


@app.route("/auth/google/callback")
def auth_google_callback():
    # Validasi state (CSRF protection)
    received_state = request.args.get("state", "")
    expected_state = session.get("oauth_state", "")
    if not received_state or not expected_state or not hmac.compare_digest(received_state, expected_state):
        session.pop("oauth_state", None)
        return "State mismatch. Kemungkinan serangan CSRF.", 403

    # State hanya boleh dipakai sekali setelah berhasil divalidasi.
    session.pop("oauth_state", None)

    if request.args.get("error"):
        return redirect(url_for("login_page") + "?error=google_denied")

    code = request.args.get("code")
    if not code:
        return redirect(url_for("login_page") + "?error=google_denied")

    # Tukar code → access token
    try:
        token_resp = requests.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        }, timeout=15)
        token_resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Google token error] {e}")
        return redirect(url_for("login_page") + "?error=token_failed")
    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(url_for("login_page") + "?error=token_failed")

    # Ambil info user dari Google
    try:
        user_resp = requests.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        user_resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Google userinfo error] {e}")
        return redirect(url_for("login_page") + "?error=userinfo_failed")
    user_info = user_resp.json()

    email  = user_info.get("email")
    name   = user_info.get("name")
    avatar = user_info.get("picture")

    if not email:
        return redirect(url_for("login_page") + "?error=no_email")

    # Simpan ke Supabase
    if not upsert_user(email=email, name=name, avatar=avatar, provider="google"):
        return redirect(url_for("login_page") + "?error=database_unavailable")

    # Set session
    session["user"] = {"email": email, "name": name, "avatar": avatar}
    return redirect(url_for("onboarding_page"))

# =====================
# ROUTES — CHATBOT
# =====================
@app.route("/tanya", methods=["POST"])
@login_required
def tanya():
    data = request.get_json(silent=True) or {}
    pertanyaan = str(data.get("pertanyaan", "")).strip()
    if not pertanyaan:
        return jsonify({"error": "Pertanyaan wajib diisi."}), 400
    if len(pertanyaan) > 4000:
        return jsonify({"error": "Pertanyaan terlalu panjang."}), 400
    pasal   = cari_pasal(pertanyaan)
    profil_user = session.get("user", {}).get("onboarding")
    jawaban = tanya_gemini(pertanyaan, pasal, profil_user)
    return jsonify({"jawaban": jawaban})

# =====================
# ROUTES — HISTORY
# =====================
@app.route("/history", methods=["GET"])
@login_required
def get_history():
    email = session["user"]["email"]
    try:
        result = get_supabase().table("chat_sessions") \
            .select("id, title, updated_at") \
            .eq("user_email", email) \
            .order("updated_at", desc=True) \
            .limit(50) \
            .execute()
        return jsonify({"sessions": result.data})
    except Exception as e:
        print(f"[History error] {e}")
        return jsonify({"sessions": []})

@app.route("/history/<session_id>", methods=["GET"])
@login_required
def get_session(session_id):
    email = session["user"]["email"]
    try:
        result = get_supabase().table("chat_sessions") \
            .select("*") \
            .eq("id", session_id) \
            .eq("user_email", email) \
            .single() \
            .execute()
        return jsonify({"session": result.data})
    except Exception as e:
        print(f"[Get session error] {e}")
        return jsonify({"session": None}), 404

@app.route("/history/<session_id>", methods=["POST"])
@login_required
def save_session(session_id):
    email = session["user"]["email"]
    data  = request.get_json(silent=True) or {}
    title    = str(data.get("title", "Konsultasi")).strip()[:200] or "Konsultasi"
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        return jsonify({"error": "Format messages tidak valid."}), 400
    try:
        get_supabase().table("chat_sessions").upsert({
            "id":         session_id,
            "user_email": email,
            "title":      title,
            "messages":   messages,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="id").execute()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[Save session error] {e}")
        return jsonify({"error": "Riwayat belum dapat disimpan."}), 503

@app.route("/history/<session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    email = session["user"]["email"]
    try:
        get_supabase().table("chat_sessions") \
            .delete() \
            .eq("id", session_id) \
            .eq("user_email", email) \
            .execute()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[Delete session error] {e}")
        return jsonify({"error": "Riwayat belum dapat dihapus."}), 503

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
