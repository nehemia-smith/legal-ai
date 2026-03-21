import requests

# =====================
# KONFIGURASI
# =====================
GEMINI_API_KEY = "AIzaSyBTnLmGI3uYQUn9azzoO8Q-yYvImuvc_4E"
PASAL_API_URL = "https://pasal.id/api/v1/search"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

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

    body = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    response = requests.post(GEMINI_URL, json=body)
    data = response.json()
    
    return data["candidates"][0]["content"]["parts"][0]["text"]

# =====================
# PROGRAM UTAMA
# =====================
print("=" * 50)
print("⚖️  ASISTEN HUKUM INDONESIA")
print("=" * 50)
print("Ketik 'keluar' untuk berhenti\n")

while True:
    pertanyaan = input("❓ Pertanyaan kamu: ")
    
    if pertanyaan.lower() == "keluar":
        print("Terima kasih telah menggunakan Asisten Hukum!")
        break
    
    print("\n🔍 Mencari pasal yang relevan...")
    pasal = cari_pasal(pertanyaan)
    
    print("🤖 Menganalisis dengan AI...\n")
    jawaban = tanya_gemini(pertanyaan, pasal)
    
    print("-" * 50)
    print(jawaban)
    print("-" * 50 + "\n")