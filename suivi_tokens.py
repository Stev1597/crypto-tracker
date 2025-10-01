import requests
import time
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# Supabase credentials
SUPABASE_URL = "https://mwnejkrkjlnrwrulqedd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Plages de variation en minutes
INTERVALS = {
    "var_5": 5,
    "var_15": 15,
    "var_30": 30,
    "var_45": 45,
    "var_1h": 60,
    "var_3h": 180,
    "var_6h": 360,
    "var_12h": 720,
    "var_24h": 1440,
}

# Seuils
SEUIL_MC = 20000
SEUIL_LIQ = 5000

def fetch_price_data(token_address):
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if not data.get("pairs"):
            return None
        return data["pairs"][0]
    except Exception as e:
        print(f"[ERREUR FETCH PRIX] {e}")
        return None

def get_old_price(token_address, minutes_ago):
    try:
        response = supabase.table("suivi_tokens") \
            .select("created_at, price") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .execute()

        now = datetime.now(timezone.utc)
        for record in response.data:
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            delta = (now - created).total_seconds() / 60
            if delta >= minutes_ago:
                return float(record["price"])
        return None
    except Exception as e:
        print(f"[ERREUR OLD PRICE {minutes_ago}min] {e}")
        return None

def should_remove_token(token_address):
    try:
        response_init = supabase.table("suivi_tokens") \
            .select("marketcap, created_at") \
            .eq("token_address", token_address) \
            .order("created_at", desc=False) \
            .limit(1) \
            .execute()

        if not response_init.data:
            return False

        initial_data = response_init.data[0]
        initial_mc = float(initial_data.get("marketcap", 0))
        created_at = datetime.fromisoformat(initial_data["created_at"].replace("Z", "+00:00"))

        now = datetime.now(timezone.utc)
        age_days = (now - created_at).days
        if age_days >= 3 and initial_mc < SEUIL_MC:
            print(f"🕒 Token trop ancien et toujours sous les seuils : {token_address}")
            return True

        response_now = supabase.table("suivi_tokens") \
            .select("marketcap") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        current_mc = float(response_now.data[0].get("marketcap", 0))
        if initial_mc > 0:
            drop = ((initial_mc - current_mc) / initial_mc) * 100
            if drop >= 70:
                print(f"📉 Token a chuté de plus de 70 % : {token_address}")
                return True

        return False
    except Exception as e:
        print(f"[ERREUR CHECK CHUTE] {e}")
        return False

def remove_token_completely(token_address):
    try:
        supabase.table("suivi_tokens").delete().eq("token_address", token_address).execute()
        supabase.table("tokens_detectes").delete().eq("token_address", token_address).execute()
        print(f"🚫 Token supprimé : {token_address}")
    except Exception as e:
        print(f"[ERREUR SUPPRESSION TOKEN] {e}")

def track_token(token):
    token_address = token.get("token_address")
    nom_jeton = token.get("nom_jeton", "N/A")

    # ⏱️ Ne pas dupliquer si trop récent
    try:
        last_entry = supabase.table("suivi_tokens") \
            .select("created_at") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if last_entry.data:
            last_ts = datetime.fromisoformat(last_entry.data[0]["created_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - last_ts).total_seconds() < 240:
                print(f"[IGNORÉ 🕒] Suivi trop récent pour {token_address}")
                return
    except Exception as e:
        print(f"[ERREUR CHECK TEMPS] {e}")

    if should_remove_token(token_address):
        remove_token_completely(token_address)
        return

    data = fetch_price_data(token_address)
    if not data:
        print(f"[SKIP] Pas de données pour {token_address}")
        return

    try:
        price = float(data.get("priceUsd", 0))
        liquidity = float(data.get("liquidity", {}).get("usd", 0))
        marketcap = float(data.get("fdv", 0))
    except:
        print(f"[ERREUR CONVERSION VALEURS] {token_address}")
        return

    now = datetime.now(timezone.utc).isoformat()
    variations = {}

    for var_col, minutes in INTERVALS.items():
        old_price = get_old_price(token_address, minutes)
        if old_price and old_price != 0:
            variations[var_col] = round(((price - old_price) / old_price) * 100, 2)
        else:
            variations[var_col] = None

    suivi_data = {
        "token_address": token_address,
        "nom_jeton": nom_jeton,
        "created_at": now,
        "price": price,
        "liquidity": liquidity,
        "marketcap": marketcap,
        **variations
    }

    try:
        supabase.table("suivi_tokens").insert(suivi_data).execute()
        print(f"[SUIVI] {nom_jeton} ({token_address})")
    except Exception as e:
        print(f"[ERREUR INSERT SUIVI] {e}")

def main():
    print("\\n[SUIVI EN COURS]")
    start = time.time()
    count = 0
    try:
        response = supabase.table("tokens_detectes").select("*").execute()
        for token in response.data:
            track_token(token)
            count += 1
    except Exception as e:
        print(f"[ERREUR FETCH TOKENS DETECTES] {e}")
    duration = round(time.time() - start, 2)
    print(f"[FIN SUIVI] {count} tokens suivis en {duration} secondes.")
    print("[PAUSE] 5 minutes...\\n")

while True:
    main()
    time.sleep(300)
