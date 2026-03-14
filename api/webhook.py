import os
import requests
import google.generativeai as genai
from flask import Flask, request, jsonify

app = Flask(__name__)

# Config
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"
# Utilise la clé que tu viens de donner (mieux vaut la mettre dans les Variables d'Env Vercel)
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyA6naR5byGoPJ9PECCyzfi8ZLfJ4jrH0mE")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/api/webhook', methods=['POST'])
def handle_smartlead():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data"}), 400

        lead_email = data.get('lead_email', 'Inconnu')
        message_body = data.get('message_body', 'Pas de contenu')
        campaign_name = data.get('campaign_name', 'Campagne')

        # Le Prompt de génie pour la catégorisation
        prompt = f"""
        Tu es un expert en closing et prospection B2B. 
        Analyse ce mail reçu de la part d'un prospect : "{message_body}"

        Instructions :
        1. Catégorise : INTERESSE, OBJECTION (précise laquelle), ou NEGATIF.
        2. Si INTERESSE : Rédige une réponse courte, punchy, qui pousse vers un appel.
        3. Si OBJECTION : Réponds avec empathie mais recadre sur la valeur.

        Format de ta réponse :
        CATEGORIE : [Ta catégorie]
        ANALYSE : [Ton analyse en 1 phrase]
        REPONSE SUGGEREE : [Ton texte de réponse]
        """

        # Generation
        response = model.generate_content(prompt)
        ai_text = response.text

        # Envoi Discord
        discord_payload = {
            "embeds": [{
                "title": f"🧠 Analyse IA : {campaign_name}",
                "description": f"**Prospect :** {lead_email}\n\n**Analyse Gemini :**\n{ai_text}",
                "color": 15418782, # Or/Jaune
                "footer": {"text": "Powered by Gemini 1.5 Flash"}
            }]
        }
        requests.post(DISCORD_WEBHOOK, json=discord_payload)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        requests.post(DISCORD_WEBHOOK, json={"content": f"❌ Erreur Gemini : {str(e)}"})
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
