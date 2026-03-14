import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1481916119412379702/RcXuyn6RKvbwqAU4EdcWRVuLhY6ZA8jCVe3d4jQl_a0-sUO9IVOM0-s7yCVhAIUqH0ow"

@app.route('/api/webhook', methods=['POST'])
def handle_smartlead():
    try:
        data = request.json

        # DEBUG : envoie tout le payload brut sur Discord
        requests.post(DISCORD_WEBHOOK, json={"content": f"🔍 **DEBUG payload Smartlead :**\n```{str(data)}```"})

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        requests.post(DISCORD_WEBHOOK, json={"content": f"❌ Erreur : {str(e)}"})
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
