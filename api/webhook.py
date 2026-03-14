import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Ton webhook Discord pour voir les tests arriver
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"

@app.route('/api/webhook', methods=['POST'])
def handle_smartlead():
    try:
        # Récupération du JSON envoyé par Smartlead
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        # Extraction des infos utiles du payload Smartlead
        lead_email = data.get('lead_email', 'Inconnu')
        message_body = data.get('message_body', 'Pas de contenu')
        campaign_name = data.get('campaign_name', 'Campagne inconnue')
        
        # Construction d'un bel embed pour Discord
        discord_payload = {
            "embeds": [{
                "title": f"📩 Nouveau mail reçu : {campaign_name}",
                "description": f"**De :** {lead_email}\n\n**Message :**\n{message_body}",
                "color": 3447003,
                "footer": {"text": "Relais Vercel x Smartlead"}
            }]
        }
        
        # Envoi vers Discord
        requests.post(DISCORD_WEBHOOK, json=discord_payload)

        return jsonify({"status": "ok", "message": "Signal relayé à Discord"}), 200

    except Exception as e:
        # Alerte Discord si le script crash
        requests.post(DISCORD_WEBHOOK, json={"content": f"❌ Erreur Script Vercel : {str(e)}"})
        return jsonify({"error": str(e)}), 500

# Requis pour que Vercel puisse l'exécuter
if __name__ == "__main__":
    app.run()
