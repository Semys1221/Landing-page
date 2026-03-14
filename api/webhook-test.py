import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"

INTERESSES = ["intéressé", "interesse", "oui", "volontiers", "pourquoi pas",
               "avec plaisir", "bien sûr", "bien sur", "je veux", "dites m'en plus",
               "plus d'info", "comment ça marche", "comment ca marche", "appel", "disponible"]

NEGATIFS = ["non", "pas intéressé", "pas interesse", "désabonner", "desabonner",
             "arrêtez", "arretez", "stop", "retirer", "ne pas contacter", "remove"]

def classify(message):
    msg = message.lower()
    for kw in NEGATIFS:
        if kw in msg:
            return "NEGATIF"
    for kw in INTERESSES:
        if kw in msg:
            return "INTERESSE"
    return "INCERTAIN"

@app.route('/api/webhook-test', methods=['POST'])
def test_webhook():
    data     = request.json or {}
    message  = data.get('message', 'oui je suis intéressé')
    email    = data.get('email', 'test@montismedia.com')
    category = classify(message)

    discord_payload = {"embeds": [{"title": f"🧪 TEST — {category}",
        "description": f"**De :** {email}\n**Message :** {message}\n\n✅ Webhook opérationnel",
        "color": 9807270}]}
    requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=5)

    return jsonify({"status": "test_ok", "category": category, "discord": "notif envoyée"}), 200

handler = app
