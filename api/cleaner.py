import os
import io
import zipfile
import requests
import pandas as pd
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

def sb_select():
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/leads?select=email,status",
            headers=HEADERS,
            timeout=10
        )
        return r.json() if r.ok else []
    except Exception as e:
        print(f"sb_select error: {e}")
        return []

def sb_upsert(records):
    if not records:
        return
    # Déduplique les records avant envoi
    seen = set()
    unique_records = []
    for r in records:
        email = r.get("email", "").lower().strip()
        if email and email not in seen:
            seen.add(email)
            unique_records.append(r)
    
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/leads",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=unique_records,
            timeout=30
        )
        print(f"UPSERT status: {r.status_code}, response: {r.text[:200]}")
    except Exception as e:
        print(f"sb_upsert error: {e}")

def get_column(df, keywords):
    for col in df.columns:
        if any(key.lower() in str(col).lower() for key in keywords):
            return col
    return None

def safe_str(val):
    """Convertit une valeur en string propre, gère NaN/None"""
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip()

@app.route('/api/cleaner', methods=['POST'])
def clean_csv():
    try:
        is_already_clean = request.form.get('is_clean') == 'true'
        force_old = request.form.get('force_old') == 'true'
        intent = request.form.get('intent', 'to_contact')
        file = request.files.get('file')

        if not file:
            return jsonify({"error": "Aucun fichier reçu."}), 400

        # --- LECTURE CSV robuste ---
        df = None
        for encoding in ['utf-8', 'latin1', 'cp1252']:
            try:
                file.seek(0)
                df = pd.read_csv(file, sep=None, engine='python',
                                 encoding=encoding, on_bad_lines='skip',
                                 dtype=str)  # Tout en string pour éviter les erreurs de type
                break
            except Exception:
                continue

        if df is None or df.empty:
            return jsonify({"error": "Impossible de lire le fichier CSV."}), 400

        # Nettoie les noms de colonnes
        df.columns = df.columns.str.strip()

        # --- COLONNE EMAIL ---
        email_col = get_column(df, ['email', 'mail'])
        if not email_col:
            return jsonify({"error": "Aucune colonne email trouvée."}), 400

        df[email_col] = df[email_col].astype(str).str.strip().str.lower()
        df = df[df[email_col].str.contains('@', na=False)].copy()
        df = df[df[email_col].str.len() > 5].copy()  # Filtre emails trop courts

        if df.empty:
            return jsonify({"error": "Aucun email valide dans le fichier."}), 400

        # Déduplique le CSV source
        df = df.drop_duplicates(subset=[email_col], keep='first').copy()

        # --- NETTOYAGE MÉTIER ---
        if not is_already_clean:
            valid_cat = ['conseil', 'conseiller', 'consultant', 'planificateur',
                         'financial', 'courtier', 'broker', 'investment',
                         'gestionnaire', 'patrimoine']
            cat_col = get_column(df, ['category', 'column 6', 'profession'])
            if cat_col:
                df = df[df[cat_col].fillna('').str.contains(
                    '|'.join(valid_cat), case=False, na=False)].copy()

            status_col = get_column(df, ['status', 'email_1'])
            if status_col:
                bad_status = ['invalid', 'unknown', 'blacklisted', 'catch all', 'complainer']
                df = df[~df[status_col].fillna('').str.lower().isin(bad_status)].copy()

            prefixes = ('contact@', 'info@', 'admin@', 'hello@', 'support@', 'sales@', 'office@')
            df = df[~df[email_col].str.startswith(prefixes)].copy()

            phone_col = get_column(df, ['phone', 'tel', 'mobile', 'column 8'])
            if phone_col:
                df[phone_col] = (df[phone_col].astype(str)
                                 .str.replace('+33', '0', regex=False)
                                 .str.replace(r'\D', '', regex=True))

        if df.empty:
            return jsonify({"error": "Aucun lead valide après nettoyage."}), 400

        # --- MAPPING ---
        name_col = get_column(df, ['name', 'company', 'cabinet', 'first name'])
        web_col = get_column(df, ['website', 'site', 'url'])
        phone_col = get_column(df, ['phone', 'tel', 'mobile'])
        loc_col = get_column(df, ['location', 'address', 'adresse', 'localisation'])

        df_mapped = pd.DataFrame()
        df_mapped['Email'] = df[email_col].values
        df_mapped['Company Name'] = df[name_col].apply(lambda x: safe_str(x).title()).values if name_col else ''
        df_mapped['Site Web'] = df[web_col].apply(lambda x: safe_str(x).lower()).values if web_col else ''
        df_mapped['Phone'] = df[phone_col].apply(safe_str).values if phone_col else ''
        df_mapped['Localisation'] = df[loc_col].apply(safe_str).values if loc_col else ''

        # Déduplique après mapping (sécurité double)
        df_mapped = df_mapped.drop_duplicates(subset=['Email'], keep='first').copy()

        # --- MASTER DB ---
        db_data = sb_select()
        db_leads = {}
        if isinstance(db_data, list):
            db_leads = {item['email'].lower(): item['status']
                       for item in db_data if isinstance(item, dict) and 'email' in item}

        # --- MODE BLACKLIST ---
        if intent == 'blacklist':
            records = [
                {"email": r['Email'],
                 "company_name": r['Company Name'],
                 "site_web": r['Site Web'],
                 "status": "blacklist"}
                for _, r in df_mapped.iterrows()
                if r['Email']
            ]
            sb_upsert(records)
            return jsonify({"message": f"✅ {len(records)} leads ajoutés à la Block List."}), 200

        # --- MODE À CONTACTER ---
        def categorize_lead(email):
            status = db_leads.get(email.lower(), 'new')
            if status == 'blacklist':
                return 'drop'
            if force_old or status in ['contacted', 'to_contact']:
                return 'relance'
            return 'new'

        df_mapped['category'] = df_mapped['Email'].apply(categorize_lead)
        df_neufs = df_mapped[df_mapped['category'] == 'new'].drop(columns=['category']).copy()
        df_relances = df_mapped[df_mapped['category'] == 'relance'].drop(columns=['category']).copy()

        if not df_neufs.empty:
            records_new = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "to_contact"}
                for _, r in df_neufs.iterrows() if r['Email']
            ]
            sb_upsert(records_new)

        if force_old and not df_relances.empty:
            records_old = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "contacted"}
                for _, r in df_relances.iterrows() if r['Email']
            ]
            sb_upsert(records_old)

        # --- EXPORT ZIP ---
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            if not df_neufs.empty:
                zf.writestr('1_campagne_leads_neufs.csv',
                            df_neufs.to_csv(index=False, sep=';', encoding='utf-8-sig'))
            if not df_relances.empty:
                zf.writestr('2_campagne_relances_60j.csv',
                            df_relances.to_csv(index=False, sep=';', encoding='utf-8-sig'))
            if df_neufs.empty and df_relances.empty:
                zf.writestr('vide.txt', 'Tous les leads étaient en blacklist ou déjà traités.')

        memory_file.seek(0)
        return send_file(memory_file, mimetype="application/zip",
                         as_attachment=True, download_name="smartlead_exports.zip")

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
