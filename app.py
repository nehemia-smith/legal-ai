from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import uuid
from dotenv import load_dotenv
from functools import wraps
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-this")

# =====================
# CONFIG
# =====================
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY")
GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET= os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback")

PASAL_API_URL = "https://pasal.id/api/v1/search"
GEMINI_URL    = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

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
    except:
        return "Tidak dapat mengakses database pasal saat ini."

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

    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(GEMINI_URL, json=body)
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

# =====================
# HELPER SUPABASE USER
# =====================
def upsert_user(email, name, avatar=None, provider="google"):
    """Simpan atau update user ke tabel 'users' di Supabase."""
    try:
        supabase.table("users").upsert({
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
        existing = supabase.table("users").select("email").eq("email", email).execute()
        if existing.data:
            return jsonify({"error": "Email sudah terdaftar. Silakan login."}), 409

        # Hash password sederhana pakai bcrypt
        import bcrypt
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        supabase.table("users").insert({
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
        result = supabase.table("users").select("*").eq("email", email).execute()
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
    auth_url = GOOGLE_AUTH_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
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
        result = supabase.table("chat_sessions") \
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
        result = supabase.table("chat_sessions") \
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
        supabase.table("chat_sessions").upsert({
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
        supabase.table("chat_sessions") \
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