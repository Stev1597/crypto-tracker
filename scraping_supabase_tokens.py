import requests
import time
from datetime import datetime, timezone
from supabase import create_client, Client
import os

# === Variables d'environnement ===
SUPABASE_URL = os.environ.get("https://mwnejkrkjlnrwrulqedd.supabase.co")
SUPABASE_KEY = os.environ.get("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im13bmVqa3JramxucndydWxxZWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM4OTc4NzYsImV4cCI6MjA2OTQ3Mzg3Nn0.6gCD-zi1nFK4m61bLBzYKmuE48ZqKOgVclelebO9vUk")

# Connexion Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Seuils minimum
LIQUIDITY_MIN = 500
MARKETCAP_MIN = 5000

def get_existing_tokens():
    try:
        response = supabase.table("tokens_detectes").select("token_address").execute()
        return set(item["token_address"] for item in response.data if item.get("token_address"))
    except Exception as e:
        print(f"[ERREUR RECUP TOKEN] {e}")
        return set()

def fetch_price_data(token_address):
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        pairs = data.get("pairs", [])

        # Prioriser PumpSwap et Raydium uniquement
        for pair in pairs:
            dex_id = pair.get("dexId", "").lower()
            if dex_id in ["pumpswap", "raydium"]:
                return pair  # Retourne la première paire valide

        return None  # Aucune paire valide trouvée
    except Exception as e:
        print(f"[ERREUR FETCH PRIX] {e}")
        return None

def has_x_account(links):
    if not links:
        return False
    for link in links:
        if link.get("type") == "twitter" or "x.com" in link.get("url", ""):
            return True
    return False

def insert_detected_token(token_data):
    try:
        supabase.table("tokens_detectes").insert(token_data).execute()
        print(f"[INSÉRÉ ✅] {token_data['token_address']}")
    except Exception as e:
        print(f"[ERREUR INSERT token_detected] {e}")

def insert_valid_token(token_data):
    try:
        supabase.table("tokens_valides").insert(token_data).execute()
        print(f"[VALIDÉ ✅] {token_data['token_address']}")
    except Exception as e:
        print(f"[ERREUR INSERT token_valides] {e}")

def process_token(token):
    if token.get("chainId") != "solana":
        return

    adresse = token.get("tokenAddress")
    nom = token.get("description", "N/A")
    dex_url = token.get("url", "N/A")
    links = token.get("links", [])

    pair_data = fetch_price_data(adresse)  # corrige le nom ici
    if not pair_data:
        print(f"[SKIP] Pas de données de pair pour {adresse}")
        return

    liquidite = float(pair_data.get("liquidity", {}).get("usd", 0))
    marketcap = float(pair_data.get("fdv", 0))
    has_x = has_x_account(links)

    # Filtrage AVANT toute insertion
    if liquidite < LIQUIDITY_MIN or marketcap < MARKETCAP_MIN or not has_x:
        print(f"[IGNORÉ ❌] {adresse} - Liquidité: {liquidite} | MarketCap: {marketcap} | Compte X: {has_x}")
        return

    now = datetime.now(timezone.utc).isoformat()

    token_data = {
        "nom_jeton": nom,
        "token_address": adresse,
        "dex_url": dex_url,
        "created_at": now,
        "liquidite": liquidite,
        "marketcap": marketcap,
        "has_x_account": has_x
    }

    insert_detected_token(token_data)
    insert_valid_token(token_data)

def get_solana_tokens():
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"[ERREUR API] Statut {response.status_code}")
            return

        data = response.json()
        tokens_existants = get_existing_tokens()

        for token in data:
            adresse = token.get("tokenAddress")
            if not adresse or adresse in tokens_existants:
                continue

            print(f"[NOUVEAU TOKEN] {adresse}")
            process_token(token)

    except Exception as e:
        print(f"[ERREUR GET SOLANA TOKENS] {e}")

# Boucle toutes les 5 minutes
while True:
    print("[SCRAPING EN COURS]")
    get_solana_tokens()
    print("[PAUSE] 5 minutes...\n")
    time.sleep(300)
