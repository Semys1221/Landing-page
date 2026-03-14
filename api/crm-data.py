import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"

def sl_get(path, params={}):
    try:
        r = requests.get(f"{BASE}{path}", params={"api_key": SMARTLEAD_API_KEY, **params}, timeout=10)
        return r.json() if r.ok else None
    except:
        return None

@app.route('/api/crm-data')
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

            # Catégorisation
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

    # Tri : intéressés en premier
    order = {"INTERESSE": 0, "INCERTAIN": 1, "NEGATIF": 2}
    result.sort(key=lambda x: order.get(x["category"], 3))

    return jsonify(result)

if __name__ == "__main__":
    app.run()
