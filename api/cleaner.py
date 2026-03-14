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

# --- FONCTION DE RECHERCHE DE COLONNE (MAPPING FLEXIBLE) ---
def get_column(df, keywords):
    for col in df.columns:
        if any(key.lower() in col.lower() for key in keywords):
            return col
    return None

@app.route('/api/cleaner', methods=['POST'])
def clean_csv():
    try:
        # 1. LECTURE DU FICHIER BORDELIQUE
        file = request.files['file']
        try:
            df = pd.read_csv(file, sep=None, engine='python', encoding='utf-8', on_bad_lines='skip')
        except:
            # Fallback si l'encodage du scraper est bizarre
            file.seek(0)
            df = pd.read_csv(file, sep=None, engine='python', encoding='latin1', on_bad_lines='skip')

        # Sauvegarde des noms de colonnes en minuscules pour faciliter la recherche exacte
        cols_lower = [str(c).lower().strip() for c in df.columns]

        # 2. FILTRAGE MÉTIER (Category & Column 6)
        valid_categories = ['conseil', 'conseiller', 'consultant', 'planificateur', 'financial planner', 'financial consultant', 'courtier', 'finance broker', 'investment service', 'gestionnaire']
        cat_col = get_column(df, ['category', 'column 6'])
        if cat_col:
            df = df[df[cat_col].fillna('').str.contains('|'.join(valid_categories), case=False, na=False)]

        # 3. FILTRAGE QUERY (Si la colonne 'query' existe)
        query_col = get_column(df, ['query'])
        if query_col:
            valid_queries = ['financial consultant', 'financial advisor']
            df = df[df[query_col].fillna('').str.contains('|'.join(valid_queries), case=False, na=False)]

        # 4. VALIDATION EMAILS (Status & Validator)
        # On cherche la colonne exacte ou approchante
        status_col = get_column(df, ['status', 'email_1.emails_validator.status'])
        if status_col:
            bad_status = ['invalid', 'unknown', 'blacklisted', 'catch all', 'invalid smtp', 'invalid dns', 'invalid format', 'undeliverable', 'cannot validate', 'complainer']
            df = df[~df[status_col].fillna('').str.lower().isin(bad_status)]

        # 5. NETTOYAGE DES EMAILS (Génériques & Personnels)
        email_col = get_column(df, ['email', 'mail'])
        if not email_col:
            return jsonify({"error": "Aucune colonne email trouvée dans le CSV."}), 400
        
        df[email_col] = df[email_col].astype(str).str.strip().str.lower()
        # Regex pour virer info@, contact@, etc.
        generic_prefixes = ('contact@', 'info@', 'admin@', 'hello@', 'support@', 'sales@', 'office@', 'accueil@')
        df = df[~df[email_col].str.startswith(generic_prefixes)]
        # Supprime les lignes sans email
        df = df[df[email_col].str.contains('@', na=False)]

        # 6. NETTOYAGE TÉLÉPHONE (Column 8 / Phone)
        phone_col = get_column(df, ['phone', 'tel', 'column 8', 'mobile'])
        if phone_col:
            # Remplace +33 par 0, enlève tout ce qui n'est pas un chiffre
            df[phone_col] = df[phone_col].astype(str).str.replace('+33', '0', regex=False).str.replace(r'\D', '', regex=True)
            # Supprime les lignes où le téléphone est vide après nettoyage
            df = df[df[phone_col].str.strip() != '']

        # --- 7. DÉDUPLICATION & TRI INTELLIGENT (Supabase) ---
        
        # On récupère les emails et leur statut depuis Supabase
        res = supabase.table("leads").select("email, status").execute()
        
        # On crée un dictionnaire : {'jean@mail.com': 'blacklist', 'marc@mail.com': 'contacted'}
        db_leads = {item['email'].lower(): item['status'] for item in res.data} if res.data else {}

        # Fonction pour catégoriser chaque ligne du CSV
        def categorize_lead(email):
            status = db_leads.get(email, 'new') # 'new' si inconnu
            if status == 'blacklist':
                return 'drop'
            elif status == 'contacted' or status == 'to_contact':
                return 'relance_60j'
            else:
                return 'new'

        # On applique la catégorie
        df['lead_category'] = df[email_col].apply(categorize_lead)

        # On supprime les 'drop' (blacklistés)
        df = df[df['lead_category'] != 'drop']

        # --- 8. SÉPARATION DES FICHIERS ---
        
        # Les tout neufs
        df_neufs = df[df['lead_category'] == 'new'].drop(columns=['lead_category'])
        
        # Ceux à relancer dans 60 jours
        df_relances = df[df['lead_category'] == 'relance_60j'].drop(columns=['lead_category'])

        # (Tu appliques ensuite ton Mapping des 5 colonnes sur ces deux dataframes...)
        
        # 8. MAPPING FINAL (Les 5 colonnes magiques)
        name_col = get_column(df, ['name', 'company', 'cabinet', 'first name'])
        web_col = get_column(df, ['website', 'site', 'url'])
        loc_col = get_column(df, ['location', 'address', 'adresse'])

        # Création du DataFrame final propre
        df_final = pd.DataFrame()
        df_final['Email'] = df[email_col]
        df_final['First Name Name (cabinet)'] = df[name_col].str.title() if name_col else ''
        df_final['Site web'] = df[web_col].str.lower() if web_col else ''
        df_final['Phone'] = df[phone_col] if phone_col else ''
        df_final['Location (full adress)'] = df[loc_col] if loc_col else ''

        # 9. SAUVEGARDE DES NOUVEAUX LEADS DANS SUPABASE
        # On prépare le dictionnaire pour Supabase
        records_to_insert = []
        for _, row in df_final.iterrows():
            records_to_insert.append({
                "email": row['Email'],
                "company_name": row['First Name Name (cabinet)'],
                "site_web": row['Site web'],
                "status": "to_contact" # Statut par défaut
            })
        
        # Insert batch (Supabase gère bien les listes de dict)
        if records_to_insert:
            supabase.table("leads").insert(records_to_insert).execute()

        # 10. SPLIT DU FICHIER EN 2 (Pour Smartlead)
        mid_index = len(df_final) // 2
        df_part1 = df_final.iloc[:mid_index]
        df_part2 = df_final.iloc[mid_index:]

        # 11. EXPORT ZIP (UTF-8-SIG et séparateur ;)
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # On génère le CSV en mémoire pour la partie 1
            csv1 = df_part1.to_csv(index=False, sep=';', encoding='utf-8-sig')
            zf.writestr('smartlead_partie_1.csv', csv1)
            
            # On génère le CSV en mémoire pour la partie 2
            csv2 = df_part2.to_csv(index=False, sep=';', encoding='utf-8-sig')
            zf.writestr('smartlead_partie_2.csv', csv2)
            
        memory_file.seek(0)

        # On renvoie le fichier ZIP au navigateur
        return send_file(
            memory_file, 
            mimetype="application/zip", 
            as_attachment=True, 
            download_name="leads_nettoyes_split.zip"
        )

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
