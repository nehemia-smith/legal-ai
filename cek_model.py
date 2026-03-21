import requests

API_KEY = "AIzaSyBTnLmGI3uYQUn9azzoO8Q-yYvImuvc_4E"

r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}")
models = r.json().get("models", [])

for m in models:
    print(m["name"])
