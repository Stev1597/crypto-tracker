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
def get_top10_hold_percent(token_address):
    try:
        url = f"https://deep-index.moralis.io/api/v2.2/erc20/{token_address}/holders?chain=solana&limit=10"
        headers = {
            "accept": "application/json",
            "X-API-Key": "TA_CLEF_API_MORALIS"  # remplace ici
        }
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()

            # ✅ DEBUG PRINT POUR COMPRENDRE LA STRUCTURE
            print(f"[DEBUG MORALIS] {token_address} →\n{data}\n")

            total_percent = 0.0
            for holder in data.get("result", []):
                percent = holder.get("percentage", 0)
                total_percent += percent
            return round(total_percent, 2)

        else:
            print(f"[❌ ERREUR MORALIS] {token_address} — Code {response.status_code}")
    except Exception as e:
        print(f"[❌ EXCEPTION MORALIS] {token_address} — {e}")
    return None


def update_top10_percent_for_all():
    try:
        # Récupération de tous les tokens déjà détectés
        tokens = supabase.table("tokens_detectes").select("token_address").execute()
        if not tokens.data:
            print("[ℹ️] Aucun token à mettre à jour.")
            return

        for t in tokens.data:
            token_address = t["token_address"]
            top10_percent = get_top10_hold_percent(token_address)

            if top10_percent is not None:
                supabase.table("tokens_detectes").update({
                    "top10_percent": top10_percent
                }).eq("token_address", token_address).execute()
                print(f"[✅ Mis à jour] {token_address} → {top10_percent:.2f}%")
            else:
                print(f"[⚠️ Échec mise à jour] {token_address}")

            # Petite pause pour éviter un rate limit Moralis
            time.sleep(0.5)

    except Exception as e:
        print(f"[❌ ERREUR UPDATE TOP10] {e}")


def get_existing_tokens():
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
        valid_pairs = [p for p in pairs if p.get("dexId", "").lower() in ALLOWED_DEXES]
        if not valid_pairs:
            add_to_ignored_tokens(token_address, "Aucun DEX valide (ex: pumpfun/météora)")
            return None

        return valid_pairs[0]  # ✅ pairAddress incluse
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
        # 🔒 Ne pas réinsérer si le token a déjà été supprimé
        res = supabase.table("tokens_supprimes").select("token_address").eq("token_address", token_data["token_address"]).execute()
        if res.data:
            print(f"[IGNORÉ ❌] Token {token_data['token_address']} précédemment supprimé. Ignoré.")
            return

        # Vérification existence dans tokens_detectes
        existing = supabase.table("tokens_detectes") \
            .select("token_address") \
            .eq("token_address", token_data["token_address"]) \
            .execute()

        if existing.data:
            print(f"[⚠️ DÉJÀ PRÉSENT] {token_data['token_address']}")
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
    chain = token.get("chainId", "").lower()
    if chain != "solana":
        print(f"[⛔️ NON SOLANA] {token.get('tokenAddress')} — ignoré.")
        return

    # Si le token n'a pas de nom ou de description, on l’ignore
    name = token.get("description", "").strip()
    if not name or name.lower() in ["n/a", ""]:
        print(f"[REJETÉ ❌] Token sans nom/description : {token.get('tokenAddress')}")
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
    pair_address = pair_data.get("pairAddress", "")  # ✅ NOUVEAU
    has_x = has_x_account(links)
    top10_percent = get_top10_hold_percent(address)

    if not (liquidity >= LIQUIDITY_MIN and marketcap >= MARKETCAP_MIN and has_x):
        print(f"[IGNORÉ ❌] {address} | LIQ: {liquidity} | MC: {marketcap} | X: {has_x}")
        return

    now = datetime.now(timezone.utc).isoformat()
    token_data = {
        "nom_jeton": name,
        "token_address": address,
        "pair_address": pair_address,  # ✅ NOUVEAU
        "dex_url": dex_url,
        "created_at": now,
        "liquidite": liquidity,
        "marketcap": marketcap,
        "has_x_account": has_x,
        "top10_percent": top10_percent
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

def purge_ignored_tokens():
    try:
        seuil = datetime.now(timezone.utc).timestamp() - 3 * 24 * 3600
        date_limite = datetime.fromtimestamp(seuil).isoformat()
        supabase.table("tokens_ignores") \
            .delete() \
            .lt("created_at", date_limite) \
            .execute()
        print("[🧹 PURGE] Anciennes entrées ignorées supprimées.")
    except Exception as e:
        print(f"[ERREUR PURGE] {e}")

update_top10_percent_for_all()

# ------------------ BOUCLE PRINCIPALE ------------------ #
while True:
    print("[🚀 SCRAPING EN COURS]")
    get_solana_tokens()
    print("[⏳ PAUSE 5 min...]\n")
    purge_ignored_tokens()
    time.sleep(300)
