import os
import requests
from flask import Flask, request, jsonify

# Vercel détecte automatiquement cette variable "app"
app = Flask(__name__)

# --- CONFIGURATION ---
SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"

INTERESSES = ["intéressé", "interesse", "oui", "volontiers", "pourquoi pas",
               "avec plaisir", "bien sûr", "bien sur", "je veux", "dites m'en plus",
               "plus d'info", "comment ça marche", "comment ca marche", "appel", "disponible"]

NEGATIFS = ["non", "pas intéressé", "pas interesse", "désabonner", "desabonner",
             "arrêtez", "arretez", "stop", "retirer", "ne pas contacter", "remove"]

# --- FONCTIONS UTILITAIRES ---
def sl_get(path, params={}):
    try:
        r = requests.get(f"{BASE}{path}", params={"api_key": SMARTLEAD_API_KEY, **params}, timeout=10)
        return r.json() if r.ok else None
    except:
        return None

def classify(message):
    msg = message.lower()
    for kw in NEGATIFS:
        if kw in msg:
            return "NEGATIF"
    for kw in INTERESSES:
        if kw in msg:
            return "INTERESSE"
    return "INCERTAIN"

# ==========================================
# ROUTE 1 : DATA CRM (Synchronisation Smartlead)
# ==========================================
@app.route('/api/crm-data', methods=['GET'])
def crm_data():
    # 1. Récupère toutes les campagnes actives
    campaigns = sl_get("/campaigns/") or []
    active = [c for c in campaigns if c.get("status") in ["ACTIVE", "PAUSED"]]

    result = []

    for campaign in active:
        cid = campaign["id"]
        cname = campaign["name"]

        # 2. Leads de la campagne
        leads_data = sl_get(f"/campaigns/{cid}/leads", {"limit": 100, "offset": 0}) or []
        leads = leads_data if isinstance(leads_data, list) else leads_data.get("data", [])

        for lead in leads:
            lead_id = lead.get("id")
            email = lead.get("email", "")
            status = lead.get("status", "")
            is_interested = lead.get("is_interested")
            reply_count = lead.get("reply_count", 0)

            if reply_count == 0:
                continue  # Garde seulement les leads qui ont répondu

            # 3. Historique des messages
            history = sl_get(f"/campaigns/{cid}/leads/{lead_id}/message-history") or []

            messages = []
            for msg in history:
                messages.append({
                    "type": msg.get("type", ""),        # SENT ou REPLY
                    "time": msg.get("time", ""),
                    "subject": msg.get("subject", ""),
                    "body": msg.get("message", "")[:500] if msg.get("message") else "",
                    "scheduled": msg.get("stats", {}).get("status") == "SCHEDULED" if msg.get("stats") else False
                })

            # 4. Catégorisation
            if is_interested:
                category = "INTERESSE"
            elif status == "BLOCKED":
                category = "NEGATIF"
            else:
                category = "INCERTAIN"

            result.append({
                "email": email,
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company": lead.get("company_name", ""),
                "campaign_id": cid,
                "campaign_name": cname,
                "status": status,
                "category": category,
                "reply_count": reply_count,
                "open_count": lead.get("open_count", 0),
                "messages": messages
            })

    # 5. Tri : intéressés en premier
    order = {"INTERESSE": 0, "INCERTAIN": 1, "NEGATIF": 2}
    result.sort(key=lambda x: order.get(x["category"], 3))

    return jsonify(result)

# ==========================================
# ROUTE 2 : WEBHOOK & DISCORD NOTIFICATION
# ==========================================
@app.route('/api/webhook-test', methods=['POST'])
def test_webhook():
    data     = request.json or {}
    message  = data.get('message', 'oui je suis intéressé')
    email    = data.get('email', 'test@montismedia.com')
    
    category = classify(message)

    # Définition des couleurs Discord selon la catégorie (Vert, Rouge, Jaune)
    colors = {
        "INTERESSE": 3066993,  # Vert
        "NEGATIF": 15158332,   # Rouge
        "INCERTAIN": 16776960  # Jaune
    }

    discord_payload = {
        "embeds": [{
            "title": f"🔔 NOUVEAU MESSAGE — {category}",
            "description": f"**De :** {email}\n**Message :** {message}\n\n✅ Webhook Vercel Opérationnel",
            "color": colors.get(category, 9807270)
        }]
    }
    
    # Try/Except pour ne pas faire crasher l'API si Discord met du temps à répondre
    try:
        requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=5)
    except Exception as e:
        print(f"Erreur d'envoi Discord : {e}")

    return jsonify({"status": "ok", "category": category, "discord": "notif envoyée"}), 200

# Permet de tester le code en local sur ta machine (Vercel ignorera cette ligne)
if __name__ == "__main__":
    app.run(debug=True)
