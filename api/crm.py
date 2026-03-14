import os
from flask import Flask, jsonify
from supabase import create_client, Client

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

@app.route('/api/crm', methods=['GET'])
def get_crm_stats():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # 1. Compter les leads par statut
        # (On limite à 1 pour ne pas télécharger la data, on veut juste le chiffre "count")
        to_contact = supabase.table("leads").select("email", count="exact").eq("status", "to_contact").limit(1).execute()
        contacted = supabase.table("leads").select("email", count="exact").eq("status", "contacted").limit(1).execute()
        
        count_to_contact = to_contact.count if to_contact.count else 0
        count_contacted = contacted.count if contacted.count else 0

        # 2. Récupérer les 5 derniers leads ajoutés pour la preview
        # Assure-toi d'avoir une colonne 'created_at' dans Supabase, sinon trie par 'email'
        recent_leads = supabase.table("leads").select("email, company_name, status").limit(5).execute()

        data = {
            "stats": {
                "total": count_to_contact + count_contacted,
                "to_contact": count_to_contact,
                "contacted": count_contacted
            },
            "recent": recent_leads.data
        }

        return jsonify(data), 200

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
