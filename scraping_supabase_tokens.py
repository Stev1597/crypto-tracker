import requests
import time
from datetime import datetime, timezone
from supabase import create_client, Client

# Supabase config
SUPABASE_URL = "https://mwnejkrkjlnrwrulqedd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im13bmVqa3JramxucndydWxxZWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM4OTc4NzYsImV4cCI6MjA2OTQ3Mzg3Nn0.6gCD-zi1nFK4m61bLBzYKmuE48ZqKOgVclelebO9vUk"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Seuils stricts requis
LIQUIDITY_MIN = 5000
MARKETCAP_MIN = 20000


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
            print(f"[⚠️ LIMITÉ PAR L'API] Pause 30 sec...")
            time.sleep(30)
            return None

        if response.status_code != 200:
            print(f"[ERREUR HTTP {response.status_code}] pour {token_address}")
            return None

        data = response.json()
        pairs = data.get("pairs", [])

        # Prioriser PumpSwap et Raydium
        for pair in pairs:
            dex_id = pair.get("dexId", "").lower()
            if dex_id in ["pumpswap", "raydium"]:
                return pair

        return None
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
        print(f"[ERREUR INSERT token_detectes] {e}")


def insert_valid_token(token_data):
    try:
        supabase.table("tokens_valides").insert(token_data).execute()
        print(f"[VALIDÉ ✅] {token_data['token_address']}")
    except Exception as e:
        print(f"[ERREUR INSERT token_valides] {e}")


def process_token(token):
    if token.get("chainId") != "solana":
        return

    address = token.get("tokenAddress")
    name = token.get("description", "N/A")
    dex_url = token.get("url", "N/A")
    links = token.get("links", [])

    pair_data = fetch_price_data(address)
    if not pair_data:
        print(f"[SKIP] Pas de données de pair pour {address}")
        return

    liquidity = float(pair_data.get("liquidity", {}).get("usd", 0))
    marketcap = float(pair_data.get("fdv", 0))
    has_x = has_x_account(links)

    # ⚠️ FILTRAGE : ne garde que les tokens solides
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


def get_solana_tokens():
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"[ERREUR API] Statut {response.status_code}")
            return

        data = response.json()
        existing = get_existing_tokens()

        for token in data:
            address = token.get("tokenAddress")
            if not address or address in existing:
                continue
            print(f"[NOUVEAU TOKEN] {address}")
            process_token(token)

    except Exception as e:
        print(f"[ERREUR GET SOLANA TOKENS] {e}")



# Boucle toutes les 5 minutes
while True:
    print("[SCRAPING EN COURS]")
    get_solana_tokens()
    print("[PAUSE] 5 minutes...\n")
    time.sleep(300)
