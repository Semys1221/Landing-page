import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

@app.route('/api/crm', methods=['GET'])
def get_crm_stats():
    try:
        def count_by_status(status):
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/leads?status=eq.{status}&select=email",
                headers={**HEADERS, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"}
            )
            return int(r.headers.get("Content-Range", "0/0").split("/")[-1])

        to_contact = count_by_status("to_contact")
        contacted = count_by_status("contacted")
        blacklist = count_by_status("blacklist")
        total = to_contact + contacted + blacklist

        recent = requests.get(
            f"{SUPABASE_URL}/rest/v1/leads?select=email,company_name,status&limit=5",
            headers=HEADERS
        ).json()

        return jsonify({
            "stats": {
                "total": total,
                "to_contact": to_contact,
                "contacted": contacted,
                "blacklist": blacklist
            },
            "recent": recent
        }), 200

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
