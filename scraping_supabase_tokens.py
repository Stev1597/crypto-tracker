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
RETRY_INTERVAL_MIN = 15
MAX_WAIT_HOURS = 3

# ------------------ LOGGING ------------------ #
def log_event(token_address, event, message):
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("logs_detection").insert({
            "token_address": token_address,
            "event": event,
            "message": message,
            "created_at": now
        }).execute()
        print(f"[📝 LOG] {event} | {token_address} => {message}")
    except Exception as e:
        print(f"[ERREUR LOG DETECTION] {e}")

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
        for pair in pairs:
            dex_id = pair.get("dexId", "").lower()
            if dex_id in ["pumpswap", "raydium"]:
                return pair
        return None
    except:
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
        supabase.table("tokens_detectes").insert(token_data).execute()
        print(f"[INSÉRÉ ✅] {token_data['token_address']}")
        log_event(token_data["token_address"], "INSERT_DETECTED", "Token inséré dans tokens_detectes")
    except Exception as e:
        print(f"[ERREUR INSERT token_detectes] {e}")

def insert_valid_token(token_data):
    try:
        supabase.table("tokens_valides").insert(token_data).execute()
        log_event(token_data["token_address"], "INSERT_VALID", "Token inséré dans tokens_valides")
    except Exception as e:
        print(f"[ERREUR INSERT token_valides] {e}")

def add_pending_token(address, name):
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("tokens_en_attente").insert({
            "token_address": address,
            "nom_jeton": name,
            "premiere_detection": now,
            "derniere_tentative": now,
            "tentatives": 1
        }).execute()
        print(f"[⏳ EN ATTENTE] {address}")
        log_event(address, "EN_ATTENTE", "Token ajouté à tokens_en_attente sans données")
    except Exception as e:
        print(f"[ERREUR INSERT EN ATTENTE] {e}")

def update_pending_attempt(address):
    try:
        supabase.table("tokens_en_attente").update({
            "derniere_tentative": datetime.now(timezone.utc).isoformat()
        }).eq("token_address", address).execute()
    except Exception as e:
        print(f"[ERREUR UPDATE EN ATTENTE] {e}")

def remove_pending_token(address):
    try:
        supabase.table("tokens_en_attente").delete().eq("token_address", address).execute()
        print(f"[❌ RETIRÉ] {address}")
        log_event(address, "SUPPRESSION_ATTENTE", "Token retiré après 3h sans données")
    except Exception as e:
        print(f"[ERREUR DELETE EN ATTENTE] {e}")

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
        add_pending_token(address, name)
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

# ------------------ RECHECK ATTENTES ------------------ #
def recheck_pending_tokens():
    try:
        result = supabase.table("tokens_en_attente").select("*").execute()
        for record in result.data:
            addr = record["token_address"]
            nom = record.get("nom_jeton", "N/A")
            premiere = datetime.fromisoformat(record["premiere_detection"])
            elapsed = (datetime.now(timezone.utc) - premiere).total_seconds()

            if elapsed > MAX_WAIT_HOURS * 3600:
                remove_pending_token(addr)
                continue

            print(f"[🔁 RETENTE] {addr}")
            pair_data = fetch_price_data(addr)
            update_pending_attempt(addr)

            if pair_data:
                print(f"[✅ INDEXÉ] {addr}")
                log_event(addr, "INDEXATION", "Token enfin indexé")

                remove_pending_token(addr)
                liquidity = float(pair_data.get("liquidity", {}).get("usd", 0))
                marketcap = float(pair_data.get("fdv", 0))

                token_data = {
                    "nom_jeton": nom,
                    "token_address": addr,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "liquidite": liquidity,
                    "marketcap": marketcap
                }

                insert_detected_token(token_data)
                insert_valid_token(token_data)
    except Exception as e:
        print(f"[ERREUR RETENTE] {e}")

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
    recheck_pending_tokens()
    print("[⏳ PAUSE 5 min...]\n")
    time.sleep(300)
