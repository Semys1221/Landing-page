import os
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION DES CLÉS API ---
SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE_SMARTLEAD = "https://server.smartlead.ai/api/v1"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"
GEMINI_API_KEY = "AIzaSyDmmAEeF9RHZaw_pQuCddlfRFloaJ8Hizc"

# ==========================================
# 1. FONCTIONS OUTILS (DATA CRM)
# ==========================================
def sl_get(path, params={}):
    try:
        r = requests.get(f"{BASE_SMARTLEAD}{path}", params={"api_key": SMARTLEAD_API_KEY, **params}, timeout=10)
        return r.json() if r.ok else None
    except:
        return None

# ==========================================
# 2. LE CERVEAU : ANALYSE & RÉDACTION IA
# ==========================================
def classify_with_ai(message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
    Tu es un analyste de ventes High Ticket. Analyse la réponse de ce prospect.
    Réponds UNIQUEMENT par l'un de ces 3 mots :
    - INTERESSE : Le prospect dit oui, veut un rendez-vous, demande des infos, ou dit "pourquoi pas".
    - NEGATIF : Le prospect dit non, n'est pas intéressé, désabonner, stop.
    - INCERTAIN : Le prospect pose une question, soulève une objection, ou sa réponse est floue.
    Message : "{message}"
    """
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if r.ok:
            response_text = r.json()['candidates'][0]['content']['parts'][0]['text'].strip().upper()
            for cat in ["INTERESSE", "NEGATIF", "INCERTAIN"]:
                if cat in response_text: return cat
        return "INCERTAIN"
    except:
        return "INCERTAIN"

def generate_objection_handling_reply(message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
    Tu es Julie Piana, de l'infrastructure Montis Media. Tu t'adresses à un Conseiller en Gestion de Patrimoine (CGP).
    Ton offre : vous réalisez les rendez-vous de découverte (R1) à leur place et leur allouez 15 dossiers haut de gamme (TMI > 30%) par trimestre.
    Le prospect a répondu à ton e-mail de prospection avec une question ou une incertitude : "{message}"
    
    Rédige une réponse sur-mesure courte (3 phrases max), très professionnelle, directe et sans jargon marketing pour lever son doute.
    Termine l'e-mail en lui proposant d'en discuter de vive voix via ce lien : <a href="https://www.montismedia.com/A-scheduling-page/index.html">réserver un appel de 15 min</a>
    
    Format : Utilise des balises HTML <p>. Ne mets pas d'objet. Signe uniquement : "Bien cordialement,<br>Julie Piana".
    """
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        if r.ok:
            return r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        return "<p>Bonjour, merci pour votre retour. Le plus simple serait d'en discuter de vive voix pour clarifier ce point : <a href='https://www.montismedia.com/A-scheduling-page/index.html'>réserver un appel</a>.</p><p>Bien cordialement,<br>Julie Piana</p>"
    except:
        return "<p>Bonjour, merci pour votre retour. Le plus simple serait d'en discuter de vive voix : <a href='https://www.montismedia.com/A-scheduling-page/index.html'>réserver un appel</a>.</p><p>Bien cordialement,<br>Julie Piana</p>"

# ==========================================
# 3. LE BRAS ARMÉ : ACTION SMARTLEAD
# ==========================================
def send_smartlead_reply(campaign_id, lead_id, reply_message_id, email_body, delay_days=0):
    url = f"{BASE_SMARTLEAD}/campaigns/{campaign_id}/reply-email-thread?api_key={SMARTLEAD_API_KEY}"
    send_time = datetime.utcnow() + timedelta(days=delay_days)
    
    requests.post(url, json={
        "lead_id": int(lead_id),
        "email_body": email_body,
        "reply_message_id": str(reply_message_id),
        "reply_email_time": send_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    })

def schedule_interested_sequence(campaign_id, lead_id, reply_message_id):
    # EMAIL 1 : Immédiat
    body_1 = """<p>Ravie de votre intérêt,</p>
    <p>Nous réalisons les R1 et vous allouons jusqu'à 15 rendez-vous qualifiés sur 90 jours, auprès de profils BIC/BNC, sans aucun démarchage de votre part, avec un modèle orienté performance.</p>
    <p>Le plus simple est de planifier un court échange de 15 minutes pour voir si cela fait sens : <a href="https://www.montismedia.com/A-scheduling-page/index.html">Réserver un appel</a>.</p>
    <p>Au plaisir d'échanger,<br>Julie Piana</p>"""
    send_smartlead_reply(campaign_id, lead_id, reply_message_id, body_1, delay_days=0)

    # EMAIL 2 : J+2
    body_2 = """<p>Bonjour,</p>
    <p>Vous avez peut-être été pris dans le fil. Confirmez-vous toujours votre intérêt pour l'augmentation de votre collecte de dossiers à forte TMI ?</p>
    <p>Voici un lien pour réserver un échange : <a href="https://www.montismedia.com/A-scheduling-page/index.html">réserver un appel</a>.</p>
    <p>Bien cordialement,<br>Julie Piana</p>"""
    send_smartlead_reply(campaign_id, lead_id, reply_message_id, body_2, delay_days=2)

    # EMAIL 3 : J+4
    body_3 = """<p>Bonjour,</p>
    <p>Sans retour de votre part, je vais donc clore votre dossier.</p>
    <p>Je vous souhaite malgré tout une excellente continuation dans le développement de vos encours.</p>
    <p>Bien cordialement,<br>Julie Piana</p>"""
    send_smartlead_reply(campaign_id, lead_id, reply_message_id, body_3, delay_days=4)

# ==========================================
# 4. ROUTES DE L'API (CRM & WEBHOOK)
# ==========================================
@app.route('/api/crm-data', methods=['GET'])
def crm_data():
    campaigns = sl_get("/campaigns/") or []
    active = [c for c in campaigns if c.get("status") in ["ACTIVE", "PAUSED"]]
    result = []

    for campaign in active:
        cid = campaign["id"]
        cname = campaign["name"]
        leads_data = sl_get(f"/campaigns/{cid}/leads", {"limit": 100, "offset": 0}) or []
        leads = leads_data if isinstance(leads_data, list) else leads_data.get("data", [])

        for lead in leads:
            if lead.get("reply_count", 0) == 0: continue
            
            history = sl_get(f"/campaigns/{cid}/leads/{lead.get('id')}/message-history") or []
            messages = []
            for msg in history:
                messages.append({
                    "type": msg.get("type", ""),
                    "time": msg.get("time", ""),
                    "subject": msg.get("subject", ""),
                    "body": msg.get("message", "")[:500] if msg.get("message") else "",
                    "scheduled": msg.get("stats", {}).get("status") == "SCHEDULED" if msg.get("stats") else False
                })

            if lead.get("is_interested"): cat = "INTERESSE"
            elif lead.get("status") == "BLOCKED": cat = "NEGATIF"
            else: cat = "INCERTAIN"

            result.append({
                "email": lead.get("email", ""),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company": lead.get("company_name", ""),
                "campaign_id": cid,
                "campaign_name": cname,
                "status": lead.get("status", ""),
                "category": cat,
                "reply_count": lead.get("reply_count", 0),
                "messages": messages
            })

    order = {"INTERESSE": 0, "INCERTAIN": 1, "NEGATIF": 2}
    result.sort(key=lambda x: order.get(x["category"], 3))
    return jsonify(result)

@app.route('/api/webhook-test', methods=['POST'])
def test_webhook():
    data = request.json or {}
    message = data.get('message') or data.get('text') or 'Pouvez-vous m\'en dire plus sur le prix ?'
    email = data.get('email') or data.get('from_email') or 'test@montismedia.com'
    
    campaign_id = data.get('campaign_id')
    lead_id = data.get('lead_id')
    message_id = data.get('message_id')

    # 1. Classification
    category = classify_with_ai(message)
    action_taken = "Aucune action (Analyse IA seule)"
    ai_generated_text = ""

    # 2. Exécution des actions selon la catégorie
    if category == "INTERESSE" and campaign_id and lead_id and message_id:
        schedule_interested_sequence(campaign_id, lead_id, message_id)
        action_taken = "Séquence de 3 emails planifiée"
        
    elif category == "NEGATIF":
        action_taken = "Aucune action (Lead ignoré)"
        
    elif category == "INCERTAIN" and campaign_id and lead_id and message_id:
        # L'IA rédige la réponse aux objections
        ai_generated_text = generate_objection_handling_reply(message)
        # On l'envoie immédiatement (délai = 0)
        send_smartlead_reply(campaign_id, lead_id, message_id, ai_generated_text, delay_days=0)
        action_taken = "Réponse sur-mesure générée par l'IA et envoyée"

    # Si c'est un test depuis l'interface web (pas de campaign_id réel)
    if category == "INCERTAIN" and not campaign_id:
        ai_generated_text = generate_objection_handling_reply(message)
        action_taken = "Simulation de réponse générée par l'IA (Non envoyée car mode test)"

    # 3. Notification Discord
    colors = {"INTERESSE": 3066993, "NEGATIF": 15158332, "INCERTAIN": 16776960}
    description = f"**De :** {email}\n**Message :** {message}\n\n⚙️ **Action :** {action_taken}"
    
    if ai_generated_text:
        description += f"\n\n🤖 **Réponse générée :**\n```html\n{ai_generated_text}\n```"

    discord_payload = {
        "embeds": [{
            "title": f"🧠 ANALYSE IA — {category}",
            "description": description,
            "color": colors.get(category, 9807270)
        }]
    }
    
    try:
        requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=5)
    except:
        pass

    return jsonify({
        "status": "ok", 
        "category": category, 
        "action": action_taken,
        "ai_reply": ai_generated_text
    }), 200

if __name__ == "__main__":
    app.run(debug=True)
