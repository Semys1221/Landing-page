import os
import io
import zipfile
import pandas as pd
from flask import Flask, request, send_file, jsonify
from supabase import create_client, Client

app = Flask(__name__)

# --- CONFIGURATION SUPABASE ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase init OK")
    except Exception as e:
        print(f"❌ Erreur init Supabase: {e}")
else:
    print(f"❌ Variables manquantes - URL: {SUPABASE_URL is not None}, KEY: {SUPABASE_KEY is not None}")


def get_column(df, keywords):
    for col in df.columns:
        if any(key.lower() in str(col).lower() for key in keywords):
            return col
    return None


@app.route('/api/debug')
def debug():
    """Route temporaire pour vérifier les variables d'env — supprimer en prod"""
    return jsonify({
        "supabase_url": os.environ.get("SUPABASE_URL", "MISSING"),
        "key_exists": os.environ.get("SUPABASE_SERVICE_ROLE_KEY") is not None,
        "key_prefix": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")[:15],
        "supabase_client": supabase is not None
    })


@app.route('/api/cleaner', methods=['POST'])
def clean_csv():
    # Guard: vérifier que Supabase est init
    if supabase is None:
        return jsonify({"error": "Supabase non initialisé. Vérifie les variables d'environnement."}), 500

    try:
        # --- 1. PARAMÈTRES UI ---
        is_already_clean = request.form.get('is_clean') == 'true'
        force_old = request.form.get('force_old') == 'true'
        intent = request.form.get('intent')
        file = request.files.get('file')

        if not file:
            return jsonify({"error": "Aucun fichier reçu."}), 400

        # --- 2. LECTURE CSV ---
        try:
            df = pd.read_csv(file, sep=None, engine='python', encoding='utf-8', on_bad_lines='skip')
        except Exception:
            file.seek(0)
            df = pd.read_csv(file, sep=None, engine='python', encoding='latin1', on_bad_lines='skip')

        email_col = get_column(df, ['email', 'mail'])
        if not email_col:
            return jsonify({"error": "Aucune colonne email trouvée."}), 400

        df[email_col] = df[email_col].astype(str).str.strip().str.lower()
        df = df[df[email_col].str.contains('@', na=False)].copy()

        if df.empty:
            return jsonify({"error": "Aucun email valide dans le fichier."}), 400

        # --- 3. NETTOYAGE (si pas déjà clean) ---
        if not is_already_clean:
            valid_cat = ['conseil', 'conseiller', 'consultant', 'planificateur', 'financial',
                         'courtier', 'broker', 'investment', 'gestionnaire', 'patrimoine']
            cat_col = get_column(df, ['category', 'column 6', 'profession'])
            if cat_col:
                df = df[df[cat_col].fillna('').str.contains('|'.join(valid_cat), case=False, na=False)]

            status_col = get_column(df, ['status', 'email_1'])
            if status_col:
                bad_status = ['invalid', 'unknown', 'blacklisted', 'catch all', 'complainer']
                df = df[~df[status_col].fillna('').str.lower().isin(bad_status)]

            prefixes = ('contact@', 'info@', 'admin@', 'hello@', 'support@', 'sales@', 'office@')
            df = df[~df[email_col].str.startswith(prefixes)]

            phone_col = get_column(df, ['phone', 'tel', 'mobile', 'column 8'])
            if phone_col:
                df[phone_col] = (df[phone_col].astype(str)
                                 .str.replace('+33', '0', regex=False)
                                 .str.replace(r'\D', '', regex=True))

        # --- 4. MAPPING ---
        df_mapped = pd.DataFrame()
        df_mapped['Email'] = df[email_col].values

        name_col = get_column(df, ['name', 'company', 'cabinet', 'first name'])
        df_mapped['Company Name'] = df[name_col].str.title().values if name_col else ''

        web_col = get_column(df, ['website', 'site', 'url'])
        df_mapped['Site Web'] = df[web_col].str.lower().values if web_col else ''

        phone_col = get_column(df, ['phone', 'tel', 'mobile'])
        df_mapped['Phone'] = df[phone_col].values if phone_col else ''

        loc_col = get_column(df, ['location', 'address', 'adresse', 'localisation'])
        df_mapped['Localisation'] = df[loc_col].values if loc_col else ''

        # --- 5. RÉCUPÉRATION MASTER DB ---
        res = supabase.table("leads").select("email, status").execute()
        db_leads = {item['email'].lower(): item['status'] for item in res.data} if res.data else {}

        # --- 6. BLACKLIST MODE ---
        if intent == 'blacklist':
            records = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "blacklist"}
                for _, r in df_mapped.iterrows()
            ]
            if records:
                supabase.table("leads").upsert(records, on_conflict="email").execute()
            return jsonify({"message": f"✅ {len(records)} leads ajoutés à la Block List."}), 200

        # --- 7. MODE À CONTACTER ---
        def categorize_lead(email):
            status = db_leads.get(email, 'new')
            if status == 'blacklist':
                return 'drop'
            if force_old or status in ['contacted', 'to_contact']:
                return 'relance'
            return 'new'

        df_mapped['category'] = df_mapped['Email'].apply(categorize_lead)
        df_neufs = df_mapped[df_mapped['category'] == 'new'].drop(columns=['category'])
        df_relances = df_mapped[df_mapped['category'] == 'relance'].drop(columns=['category'])

        # Synchro DB
        if not df_neufs.empty:
            records_new = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "to_contact"}
                for _, r in df_neufs.iterrows()
            ]
            supabase.table("leads").upsert(records_new, on_conflict="email").execute()

        if force_old and not df_relances.empty:
            records_old = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "contacted"}
                for _, r in df_relances.iterrows()
            ]
            supabase.table("leads").upsert(records_old, on_conflict="email").execute()

        # --- 8. EXPORT ZIP ---
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            if not df_neufs.empty:
                zf.writestr('1_campagne_leads_neufs.csv',
                            df_neufs.to_csv(index=False, sep=';', encoding='utf-8-sig'))
            if not df_relances.empty:
                zf.writestr('2_campagne_relances_60j.csv',
                            df_relances.to_csv(index=False, sep=';', encoding='utf-8-sig'))
            if df_neufs.empty and df_relances.empty:
                zf.writestr('vide.txt', 'Tous les leads de ce fichier etaient en blocklist.')

        memory_file.seek(0)
        return send_file(memory_file, mimetype="application/zip",
                         as_attachment=True, download_name="smartlead_exports.zip")

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()
