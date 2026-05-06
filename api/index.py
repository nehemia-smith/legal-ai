from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import uuid
from urllib.parse import urlencode
from dotenv import load_dotenv
from functools import wraps
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__, template_folder='../templates')
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")

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
# Gunakan gemini-pro sebagai yang paling stabil jika flash bermasalah
GEMINI_MODEL = "gemini-pro" 
GEMINI_BASE_URL = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"

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
    try:
        response = requests.get(PASAL_API_URL, params={"q": kata_kunci})
        data = response.json()
        hasil = ""
        for item in data.get("results", [])[:3]:
            hasil += f"\n📌 {item.get('title', '')}\n"
            hasil += f"{item.get('content', '')}\n"
        return hasil if hasil else "Tidak ditemukan pasal yang relevan."
    except Exception as e:
        print(f"[cari_pasal error] {e}")
        return "Mohon maaf, saat ini asisten tidak dapat mengakses database pasal hukum. Silakan coba lagi nanti."

# =====================
# FUNGSI TANYA KE GEMINI
# =====================
def tanya_gemini(pertanyaan, konteks_pasal):
    prompt = f"""Kamu adalah asisten hukum Indonesia yang membantu 
masyarakat memahami hukum dengan bahasa yang mudah dimengerti.
Selalu cantumkan referensi pasal yang relevan.
Ingatkan pengguna bahwa jawabanmu bukan nasihat hukum resmi 
dan sarankan konsultasi ke pengacara untuk kasus spesifik.

Pertanyaan: {pertanyaan}

Pasal-pasal yang relevan dari database hukum Indonesia:
{konteks_pasal}

Tolong jawab pertanyaan di atas berdasarkan pasal-pasal tersebut."""

    try:
        # Konstruksi URL dengan Key terbaru
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        
        # Coba request
        response = requests.post(url, json=body, timeout=25)
        
        # Jika gemini-pro pun 404, coba flash-latest (cadangan terakhir)
        if response.status_code == 404:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
            response = requests.post(url, json=body, timeout=25)
            
        response.raise_for_status()
        data = response.json()
        
        if "candidates" in data and len(data["candidates"]) > 0:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        
        # Handle safety filter or other reasons for no candidates
        if "promptFeedback" in data:
            return "Maaf, permintaan Anda tidak dapat diproses karena kebijakan keamanan AI. Cobalah bertanya dengan bahasa yang lebih netral."
            
        return "Maaf, asisten hukum sedang tidak dapat memberikan jawaban saat ini. Silakan coba pertanyaan lain."
    except Exception as e:
        print(f"[Gemini error] {e}")
        return f"Terjadi gangguan pada koneksi AI. (Detail: {str(e)[:50]}...)"

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
    except Exception as e:
        print(f"[Supabase upsert error] {e}")

# =====================
# ROUTES — PAGES
# =====================
@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/chat")
@login_required
def chat():
    return render_template("index.html", user=session["user"])

@app.route("/login")
def login_page():
    if "user" in session:
        return redirect(url_for("chat"))
    return render_template("login.html")

@app.route("/register")
def register_page():
    if "user" in session:
        return redirect(url_for("chat"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

# =====================
# ROUTES — EMAIL AUTH
# =====================
@app.route("/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json()
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
    data = request.get_json()
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
    if request.args.get("state") != session.pop("oauth_state", None):
        return "State mismatch. Kemungkinan serangan CSRF.", 403

    code = request.args.get("code")
    if not code:
        return redirect(url_for("login_page") + "?error=google_denied")

    # Tukar code → access token
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "grant_type":    "authorization_code",
    })
    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(url_for("login_page") + "?error=token_failed")

    # Ambil info user dari Google
    user_resp = requests.get(GOOGLE_USER_URL, headers={"Authorization": f"Bearer {access_token}"})
    user_info = user_resp.json()

    email  = user_info.get("email")
    name   = user_info.get("name")
    avatar = user_info.get("picture")

    if not email:
        return redirect(url_for("login_page") + "?error=no_email")

    # Simpan ke Supabase
    upsert_user(email=email, name=name, avatar=avatar, provider="google")

    # Set session
    session["user"] = {"email": email, "name": name, "avatar": avatar}
    return redirect(url_for("chat"))

# =====================
# ROUTES — CHATBOT
# =====================
@app.route("/tanya", methods=["POST"])
@login_required
def tanya():
    data = request.json
    pertanyaan = data.get("pertanyaan", "")
    pasal   = cari_pasal(pertanyaan)
    jawaban = tanya_gemini(pertanyaan, pasal)
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
    data  = request.get_json()
    title    = data.get("title", "Konsultasi")
    messages = data.get("messages", [])
    try:
        get_supabase().table("chat_sessions").upsert({
            "id":         session_id,
            "user_email": email,
            "title":      title,
            "messages":   messages,
            "updated_at": "now()",
        }, on_conflict="id").execute()
        return jsonify({"success": True})
    except Exception as e:
        print(f"[Save session error] {e}")
        return jsonify({"error": str(e)}), 500

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
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)