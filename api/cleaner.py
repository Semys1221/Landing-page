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

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Erreur init Supabase: {e}")

def get_column(df, keywords):
    """Trouve la colonne correspondante selon une liste de mots-clés"""
    for col in df.columns:
        if any(key.lower() in str(col).lower() for key in keywords):
            return col
    return None

@app.route('/api/cleaner', methods=['POST'])
def clean_csv():
    try:
        # --- 1. RÉCUPÉRATION DES DONNÉES DE L'INTERFACE ---
        is_already_clean = request.form.get('is_clean') == 'true'
        intent = request.form.get('intent') # 'to_contact' ou 'blacklist'
        file = request.files['file']

        # Lecture du CSV (Tolérance sur l'encodage et les séparateurs)
        try:
            df = pd.read_csv(file, sep=None, engine='python', encoding='utf-8', on_bad_lines='skip')
        except:
            file.seek(0)
            df = pd.read_csv(file, sep=None, engine='python', encoding='latin1', on_bad_lines='skip')

        # Identifier la colonne Email (Indispensable)
        email_col = get_column(df, ['email', 'mail'])
        if not email_col:
            return jsonify({"error": "Aucune colonne email trouvée dans le CSV."}), 400
        
        df[email_col] = df[email_col].astype(str).str.strip().str.lower()
        df = df[df[email_col].str.contains('@', na=False)] # Sécurité de base

        # --- 2. NETTOYAGE (Uniquement si le fichier n'est pas déclaré 'Clean') ---
        if not is_already_clean:
            # A. Filtrage Métier
            valid_categories = ['conseil', 'conseiller', 'consultant', 'planificateur', 'financial planner', 'financial consultant', 'courtier', 'finance broker', 'investment service', 'gestionnaire', 'patrimoine']
            cat_col = get_column(df, ['category', 'column 6', 'profession'])
            if cat_col:
                df = df[df[cat_col].fillna('').str.contains('|'.join(valid_categories), case=False, na=False)]

            # B. Validation Email (Exit invalides)
            status_col = get_column(df, ['status', 'email_1.emails_validator.status'])
            if status_col:
                bad_status = ['invalid', 'unknown', 'blacklisted', 'catch all', 'invalid smtp', 'invalid dns', 'invalid format', 'undeliverable', 'cannot validate', 'complainer']
                df = df[~df[status_col].fillna('').str.lower().isin(bad_status)]

            # C. Nettoyage Générique
            generic_prefixes = ('contact@', 'info@', 'admin@', 'hello@', 'support@', 'sales@', 'office@', 'accueil@')
            df = df[~df[email_col].str.startswith(generic_prefixes)]

            # D. Nettoyage Téléphone
            phone_col = get_column(df, ['phone', 'tel', 'column 8', 'mobile'])
            if phone_col:
                df[phone_col] = df[phone_col].astype(str).str.replace('+33', '0', regex=False).str.replace(r'\D', '', regex=True)

        # MAPPING DES COLONNES (Pour standardiser l'export)
        name_col = get_column(df, ['name', 'company', 'cabinet', 'first name'])
        web_col = get_column(df, ['website', 'site', 'url'])
        loc_col = get_column(df, ['location', 'address', 'adresse', 'localisation'])
        phone_col = get_column(df, ['phone', 'tel', 'mobile'])

        df_mapped = pd.DataFrame()
        df_mapped['Email'] = df[email_col]
        df_mapped['Company Name'] = df[name_col].str.title() if name_col else ''
        df_mapped['Site Web'] = df[web_col].str.lower() if web_col else ''
        df_mapped['Phone'] = df[phone_col] if phone_col else ''
        df_mapped['Localisation'] = df[loc_col] if loc_col else ''

        # --- 3. INTERROGATION DE LA MASTER DB (SUPABASE) ---
        res = supabase.table("leads").select("email, status").execute()
        db_leads = {item['email'].lower(): item['status'] for item in res.data} if res.data else {}

        # --- 4. TRAITEMENT SELON L'INTENTION ---
        if intent == 'blacklist':
            # MODE : NE PLUS CONTACTER
            records_to_upsert = []
            for _, row in df_mapped.iterrows():
                records_to_upsert.append({
                    "email": row['Email'],
                    "company_name": row['Company Name'],
                    "site_web": row['Site Web'],
                    "status": "blacklist"
                })
            if records_to_upsert:
                supabase.table("leads").upsert(records_to_upsert, on_conflict="email").execute()
            
            return jsonify({"message": f"✅ {len(records_to_upsert)} leads ont été ajoutés à la Block List de la Master DB. Aucun fichier exporté."}), 200

        else:
            # MODE : À CONTACTER (Tri Intelligent)
            def categorize_lead(email):
                status = db_leads.get(email, 'new')
                if status == 'blacklist': return 'drop'
                if status in ['contacted', 'to_contact']: return 'relance'
                return 'new'

            df_mapped['category'] = df_mapped['Email'].apply(categorize_lead)

            # Séparation des DataFrames
            df_neufs = df_mapped[df_mapped['category'] == 'new'].drop(columns=['category'])
            df_relances = df_mapped[df_mapped['category'] == 'relance'].drop(columns=['category'])

            # Sauvegarde des TOUT NEUFS dans Supabase
            if not df_neufs.empty:
                records_new = []
                for _, row in df_neufs.iterrows():
                    records_new.append({
                        "email": row['Email'],
                        "company_name": row['Company Name'],
                        "site_web": row['Site Web'],
                        "status": "to_contact"
                    })
                supabase.table("leads").upsert(records_new, on_conflict="email").execute()

            # --- 5. EXPORT ZIP ---
            memory_file = io.BytesIO()
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Fichier 1 : Les Neufs
                csv_neufs = df_neufs.to_csv(index=False, sep=';', encoding='utf-8-sig')
                zf.writestr('1_campagne_leads_neufs.csv', csv_neufs)
                
                # Fichier 2 : Les Relances
                csv_relances = df_relances.to_csv(index=False, sep=';', encoding='utf-8-sig')
                zf.writestr('2_campagne_relances_60j.csv', csv_relances)
                
            memory_file.seek(0)
            return send_file(
                memory_file, 
                mimetype="application/zip", 
                as_attachment=True, 
                download_name="smartlead_exports.zip"
            )

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
