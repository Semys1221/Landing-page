import os
import io
import json
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
            headers=HEADERS, timeout=10
        )
        return r.json() if r.ok else []
    except Exception as e:
        print(f"sb_select error: {e}")
        return []

def sb_upsert(records):
    if not records:
        return
    seen = set()
    unique = []
    for r in records:
        email = r.get("email", "").lower().strip()
        if email and email not in seen:
            seen.add(email)
            unique.append(r)
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/leads",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=unique, timeout=30
        )
        print(f"UPSERT status: {r.status_code}, response: {r.text[:200]}")
    except Exception as e:
        print(f"sb_upsert error: {e}")

def safe_str(val):
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass
    return str(val).strip() if val is not None else ""

@app.route('/api/cleaner', methods=['POST'])
def clean_csv():
    try:
        mapping   = json.loads(request.form.get('mapping', '{}'))
        do_clean  = request.form.get('do_clean') == 'true'
        force_old = request.form.get('force_old') == 'true'
        intent    = request.form.get('intent', 'to_contact')
        file      = request.files.get('file')

        if not file:
            return jsonify({"error": "Aucun fichier reçu."}), 400
        if not mapping.get('email'):
            return jsonify({"error": "Colonne email non mappée."}), 400

        df = None
        for encoding in ['utf-8', 'latin1', 'cp1252']:
            try:
                file.seek(0)
                df = pd.read_csv(file, sep=None, engine='python',
                                 encoding=encoding, on_bad_lines='skip', dtype=str)
                break
            except Exception:
                continue

        if df is None or df.empty:
            return jsonify({"error": "Impossible de lire le fichier CSV."}), 400

        df.columns = df.columns.str.strip()
        print(f"Colonnes CSV: {list(df.columns)}")
        print(f"Mapping reçu: {mapping}")

        email_col = mapping['email']
        if email_col not in df.columns:
            return jsonify({"error": f"Colonne '{email_col}' introuvable dans le CSV."}), 400

        df[email_col] = df[email_col].astype(str).str.strip().str.lower()
        df = df[df[email_col].str.contains('@', na=False)].copy()
        df = df[df[email_col].str.len() > 5].copy()
        df = df.drop_duplicates(subset=[email_col], keep='first').copy()

        if df.empty:
            return jsonify({"error": "Aucun email valide dans le fichier."}), 400

        if do_clean:
            valid_cat = ['conseil', 'conseiller', 'consultant', 'planificateur',
                         'financial', 'courtier', 'broker', 'investment',
                         'gestionnaire', 'patrimoine']

            cat_col = None
            for col in df.columns:
                col_norm = col.lower().replace(' ', '').replace('_', '')
                if any(k in col_norm for k in ['category', 'categorie', 'profession', 'metier']):
                    cat_col = col
                    break
            if cat_col:
                df = df[df[cat_col].fillna('').str.contains(
                    '|'.join(valid_cat), case=False, na=False)].copy()

            status_csv_col = None
            for col in df.columns:
                col_norm = col.lower().replace(' ', '').replace('_', '')
                if any(k in col_norm for k in ['emailstatus', 'email1', 'emailvalid']):
                    status_csv_col = col
                    break
            if status_csv_col:
                bad = ['invalid', 'unknown', 'blacklisted', 'catch all', 'complainer']
                df  = df[~df[status_csv_col].fillna('').str.lower().isin(bad)].copy()

            prefixes = ('contact@', 'info@', 'admin@', 'hello@', 'support@', 'sales@', 'office@')
            df = df[~df[email_col].str.startswith(prefixes)].copy()

            if df.empty:
                return jsonify({"error": "Aucun lead valide après nettoyage."}), 400

        def get_mapped(col_name):
            col = mapping.get(col_name)
            if col and col in df.columns:
                return df[col].apply(safe_str).values
            return ''

        df_mapped = pd.DataFrame()
        df_mapped['Email']        = df[email_col].apply(safe_str).values
        df_mapped['Company Name'] = pd.Series(get_mapped('company_name')).apply(lambda x: x.title() if x else '').values
        df_mapped['Site Web']     = pd.Series(get_mapped('site_web')).apply(lambda x: x.lower() if x else '').values
        df_mapped['Phone']        = get_mapped('phone')
        df_mapped['Localisation'] = get_mapped('localisation')

        df_mapped = df_mapped.drop_duplicates(subset=['Email'], keep='first').copy()
        print(f"Leads après mapping: {len(df_mapped)}")

        db_data  = sb_select()
        db_leads = {}
        if isinstance(db_data, list):
            db_leads = {item['email'].lower(): item['status']
                        for item in db_data if isinstance(item, dict) and 'email' in item}

        if intent == 'blacklist':
            records = [
                {"email": r['Email'], "company_name": r['Company Name'],
                 "site_web": r['Site Web'], "status": "blacklist"}
                for _, r in df_mapped.iterrows() if r['Email']
            ]
            sb_upsert(records)
            return jsonify({"message": f"✅ {len(records)} leads ajoutés à la Block List."}), 200

        def categorize_lead(email):
            status = db_leads.get(email.lower(), 'new')
            if status == 'blacklist':
                return 'drop'
            if force_old or status in ['contacted', 'to_contact']:
                return 'relance'
            return 'new'

        df_mapped['category'] = df_mapped['Email'].apply(categorize_lead)
        df_neufs    = df_mapped[df_mapped['category'] == 'new'].drop(columns=['category']).copy()
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
