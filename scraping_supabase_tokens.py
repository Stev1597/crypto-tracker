import requests
import time
from datetime import datetime, timezone
from supabase import create_client, Client

# ------------------ CONFIG ------------------ #
SUPABASE_URL = "https://mwnejkrkjlnrwrulqedd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im13bmVqa3JramxucndydWxxZWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM4OTc4NzYsImV4cCI6MjA2OTQ3Mzg3Nn0.6gCD-zi1nFK4m61bLBzYKmuE48ZqKOgVclelebO9vUk"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

LIQUIDITY_MIN = 5000
MARKETCAP_MIN = 20000
ALLOWED_DEXES = ["pumpswap", "raydium"]

# ------------------ UTILS ------------------ #
def get_existing_tokens():
    """Récupère tous les tokens déjà détectés ou ignorés."""
    try:
        detectes = supabase.table("tokens_detectes").select("token_address").execute()
        ignores = supabase.table("tokens_ignores").select("token_address").execute()

        list_detectes = {t["token_address"] for t in detectes.data if t.get("token_address")}
        list_ignores = {t["token_address"] for t in ignores.data if t.get("token_address")}
        return list_detectes.union(list_ignores)
    except Exception as e:
        print(f"[ERREUR RECUP TOKEN] {e}")
        return set()

def add_to_ignored_tokens(address, reason="Aucun DEX valide"):
    """Ajoute un token à la liste noire permanente."""
    try:
        supabase.table("tokens_ignores").insert({
            "token_address": address,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raison": reason
        }).execute()
        print(f"[🛑 IGNORÉ DÉFINITIVEMENT] {address} — {reason}")
    except Exception as e:
        print(f"[ERREUR INSERT IGNORE] {e}")

def fetch_price_data(token_address):
    """Interroge Dexscreener pour les données et vérifie la présence d’un DEX autorisé."""
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 429:
            print("[⚠️ RATE LIMIT] Pause 30 sec...")
            time.sleep(30)
            return None
        if response.status_code != 200:
            return None

        data = response.json()
        pairs = data.get("pairs", [])

        # Filtrer les DEX autorisés
        valid_pairs = [p for p in pairs if p.get("dexId", "").lower() in ALLOWED_DEXES]
        if not valid_pairs:
            add_to_ignored_tokens(token_address, "Aucun DEX valide (ex: pumpfun/météora)")
            return None

        return valid_pairs[0]

    except Exception as e:
        print(f"[ERREUR FETCH PRIX] {e}")
        return None

def has_x_account(links):
    if not links:
        return False
    for link in links:
        url = link.get("url", "").lower()
        if link.get("type") == "twitter" or "x.com" in url:
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
    """Analyse et filtre un token avant insertion."""
    chain = token.get("chainId", "").lower()
    if chain != "solana":
        print(f"[⛔️ NON SOLANA] {token.get('tokenAddress')} — ignoré.")
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
    """Récupère les tokens récents depuis Dexscreener."""
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


def purge_ignored_tokens():
    try:
        seuil = datetime.now(timezone.utc).timestamp() - 3 * 24 * 3600  # 3 jours
        date_limite = datetime.fromtimestamp(seuil).isoformat()
        supabase.table("tokens_ignores") \
            .delete() \
            .lt("created_at", date_limite) \
            .execute()
        print("[🧹 PURGE] Anciennes entrées ignorées supprimées.")
    except Exception as e:
        print(f"[ERREUR PURGE] {e}")

# ------------------ BOUCLE PRINCIPALE ------------------ #
while True:
    print("[🚀 SCRAPING EN COURS]")
    get_solana_tokens()
    print("[⏳ PAUSE 5 min...]\n")
    purge_ignored_tokens()
    time.sleep(300)
