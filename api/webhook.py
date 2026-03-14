import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"
SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY")

T1 = """Ravie de votre intérêt,

Nous permettons aux CGP d'obtenir jusqu'à 20 nouveaux rendez-vous qualifiés avec des profils BIC/BNC en 90 jours, grâce à une méthode qui fait venir les prospects à vous, sans que vous ayez à passer d'appels à froid ni à vous positionner comme un démarcheur téléphonique.

Le tout dans un cadre entièrement indexé sur les résultats délivrés.

Le plus simple pour en discuter est de planifier un court échange de 15 minutes.
<a href="http://montismedia.com/A-scheduling-page">Réserver un appel</a>

Au plaisir de vous rencontrer,
Julie Piana"""

T2 = """Bonjour,

Vous avez peut-être été pris dans le fil. Confirmez-vous toujours votre intérêt pour l'augmentation de votre collecte de dossiers à forte TMI ?

Voici un lien pour réserver un échange : <a href="http://montismedia.com/A-scheduling-page">réserver un appel</a>

Bien cordialement,
Julie Piana"""

T3 = """Bonjour,

Sans retour de votre part, je vais donc clore votre dossier.

Je vous souhaite malgré tout une excellente continuation dans le développement de vos encours.

Bien cordialement,
Julie Piana"""

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

def get_scheduled_time(days_from_now):
    date = datetime.utcnow() + timedelta(days=days_from_now)
    if date.weekday() == 5:
        date += timedelta(days=2)
    elif date.weekday() == 6:
        date += timedelta(days=1)
    date = date.replace(hour=9, minute=0, second=0, microsecond=0)
    return date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def send_reply(campaign_id, stats_id, body, scheduled_time=None):
    url = f"https://server.smartlead.ai/api/v1/email-campaigns/send-email-thread?api_key={SMARTLEAD_API_KEY}"
    payload = {
        "campaignId": int(campaign_id),
        "emailStatsId": str(stats_id),
        "emailBody": body,
        "addSignature": False,
    }
    if scheduled_time:
        payload["scheduledTime"] = scheduled_time
    r = requests.post(url, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()

@app.route('/api/webhook', methods=['POST'])
def handle_smartlead():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400

        lead_email    = data.get('sl_lead_email', 'Inconnu')
        campaign_name = data.get('campaign_name', 'Campagne inconnue')
        campaign_id   = data.get('campaign_id')
        stats_id      = data.get('stats_id')
        reply_message = data.get('reply_message', {})
        message_body  = reply_message.get('text', '') if isinstance(reply_message, dict) else ''

        category = classify(message_body)

        if category == "INTERESSE" and campaign_id and stats_id:
            send_reply(campaign_id, stats_id, T1)
            send_reply(campaign_id, stats_id, T2, get_scheduled_time(1))
            send_reply(campaign_id, stats_id, T3, get_scheduled_time(3))
            discord_payload = {"embeds": [{"title": f"✅ Prospect chaud : {campaign_name}",
                "description": f"**De :** {lead_email}\n**Message :** {message_body}\n\n📧 T1 envoyé, T2 J+1, T3 J+3",
                "color": 3066993}]}

        elif category == "NEGATIF":
            discord_payload = {"embeds": [{"title": f"❌ Négatif : {campaign_name}",
                "description": f"**De :** {lead_email}\n**Message :** {message_body}",
                "color": 15158332}]}

        else:
            discord_payload = {"embeds": [{"title": f"⚠️ Incertain : {campaign_name}",
                "description": f"**De :** {lead_email}\n**Message :** {message_body}\n\nRéponse manuelle requise.",
                "color": 16776960}]}

        requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=5)
        return jsonify({"status": "ok", "category": category}), 200

    except Exception as e:
        requests.post(DISCORD_WEBHOOK, json={"content": f"❌ Erreur Webhook : {str(e)}"}, timeout=5)
        return jsonify({"error": str(e)}), 500


@app.route('/api/webhook/test', methods=['POST'])
def test_webhook():
    data = request.json or {}
    message = data.get('message', 'oui je suis intéressé')
    email   = data.get('email', 'test@montismedia.com')
    category = classify(message)

    discord_payload = {"embeds": [{"title": f"🧪 TEST — {category}",
        "description": f"**De :** {email}\n**Message :** {message}\n\n✅ Webhook opérationnel",
        "color": 9807270}]}
    requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=5)

    return jsonify({"status": "test_ok", "category": category, "discord": "notif envoyée"}), 200
