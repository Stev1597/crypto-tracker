import requests
import time
from datetime import datetime, timezone
from supabase import create_client, Client

# Supabase config
SUPABASE_URL = "https://mwnejkrkjlnrwrulqedd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im13bmVqa3JramxucndydWxxZWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM4OTc4NzYsImV4cCI6MjA2OTQ3Mzg3Nn0.6gCD-zi1nFK4m61bLBzYKmuE48ZqKOgVclelebO9vUk"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Seuils
LIQUIDITY_MIN = 5000
MARKETCAP_MIN = 20000

# ------------------ UTILS ------------------ #
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
        if response.status_code == 429:
            time.sleep(30)
            return None
        if response.status_code != 200:
            return None

        data = response.json()
        pairs = data.get("pairs", [])

        # Filtre toutes les paires autorisées (PumpSwap ou Raydium)
        allowed_dexes = ["pumpswap", "raydium"]
        allowed_pairs = [pair for pair in pairs if pair.get("dexId", "").lower() in allowed_dexes]

        if not allowed_pairs:
            print(f"[❌ PAS DE DEX VALIDE] {token_address}")
            return None

        # Tu peux choisir ici la première paire PumpSwap ou Raydium trouvée :
        return allowed_pairs[0]

    except Exception as e:
        print(f"[ERREUR FETCH] {e}")
        return None

def has_x_account(links):
    if not links:
        return False
    for link in links:
        if link.get("type") == "twitter" or "x.com" in link.get("url", ""):
            return True
    return False

# ------------------ BDD ------------------ #
def insert_detected_token(token_data):
    try:
        existing = supabase.table("tokens_detectes") \
            .select("token_address") \
            .eq("token_address", token_data["token_address"]) \
            .execute()
        if existing.data:
            print(f"[🔁 DÉJÀ PRÉSENT] {token_data['token_address']}")
            return
        supabase.table("tokens_detectes").insert(token_data).execute()
        print(f"[INSÉRÉ ✅] {token_data['token_address']}")
    except Exception as e:
        print(f"[ERREUR INSERT DETECT] {e}")

def insert_valid_token(token_data):
    try:
        supabase.table("tokens_valides").insert(token_data).execute()
    except Exception as e:
        print(f"[ERREUR INSERT VALIDES] {e}")

# ------------------ TRAITEMENT ------------------ #
def process_token(token):
    if token.get("chainId") != "solana":
        return

    address = token.get("tokenAddress")
    name = token.get("description", "N/A")
    dex_url = token.get("url", "N/A")
    links = token.get("links", [])

    pair_data = fetch_price_data(address)
    if not pair_data:
        print(f"[NON INDEXÉ ❌] {address}")
        return

    liquidity = float(pair_data.get("liquidity", {}).get("usd", 0))
    marketcap = float(pair_data.get("fdv", 0))
    has_x = has_x_account(links)

    if not (liquidity >= LIQUIDITY_MIN and marketcap >= MARKETCAP_MIN and has_x):
        print(f"[IGNORÉ ❌] {address} | LIQ: {liquidity} | MC: {marketcap} | X: {has_x}")
        return

    now = datetime.now(timezone.utc).isoformat()
    token_data = {
        "nom_jeton": name,
        "token_address": address,
        "dex_url": dex_url,
        "created_at": now,
        "liquidite": liquidity,
        "marketcap": marketcap,
        "has_x_account": has_x
    }

    insert_detected_token(token_data)
    insert_valid_token(token_data)

# ------------------ SCRAPING ------------------ #
def get_solana_tokens():
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return
        data = response.json()
        existing = get_existing_tokens()
        for token in data:
            address = token.get("tokenAddress")
            if not address or address in existing:
                continue
            print(f"[🆕 TOKEN] {address}")
            process_token(token)
    except Exception as e:
        print(f"[ERREUR GET TOKENS] {e}")

# ------------------ BOUCLE ------------------ #
while True:
    print("[🚀 SCRAPING EN COURS]")
    get_solana_tokens()
    print("[⏳ PAUSE 5 min...]\n")
    time.sleep(300)
