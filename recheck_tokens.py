import os
import time
from datetime import datetime, timezone, timedelta
import requests
from supabase import create_client

# 🔐 Variables d’environnement
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 📅 Seuil de suppression automatique
DUREE_MAX_ATTENTE = timedelta(hours=2)

# 🔁 Fonction principale
def recheck_tokens():
    print(f"\n🔄 Recheck lancé à {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        result = supabase.table("TokenIgnore").select("*").execute()
        tokens = result.data

        for token in tokens:
            address = token.get("TokenAddress")
            created_at = datetime.fromisoformat(token.get("CreatedAt").replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - created_at

            # 🕒 Suppression après 2h sans données
            if age > DUREE_MAX_ATTENTE:
                supabase.table("TokenIgnore").delete().eq("TokenAddress", address).execute()
                print(f"🗑 Token supprimé après 2h sans données : {address}")
                continue

            # 🔎 Récupération des données depuis DexScreener
            dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            dex_response = requests.get(dex_url)
            if dex_response.status_code != 200:
                print(f"⏳ Pas encore indexé sur DexScreener : {address}")
                continue

            data = dex_response.json().get("pairs")
            if not data:
                print(f"⚠️ Aucune paire trouvée pour {address}")
                continue

            pair = data[0]
            liquidity = pair.get("liquidity", {}).get("usd", 0)
            marketcap = pair.get("fdv", 0)
            twitter_url = pair.get("info", {}).get("twitter")

            # ❌ Vérifications des seuils
            if liquidity < 5000 or marketcap < 20000 or not twitter_url:
                print(f"⛔️ Token invalide : {address} (liq: {liquidity}, mc: {marketcap}, X: {twitter_url})")
                continue

            # 📊 Vérifie le top10 via Moralis
            top10 = get_holder_stats(address)
            if top10 is None or top10 > 60:
                print(f"🚫 Top10 trop élevé pour {address} : {top10}%")
                continue

            # ✅ Insertion dans tokens_detectes
            token_name = pair.get("baseToken", {}).get("name", "N/A")
            pair_address = pair.get("pairAddress", "")
            now = datetime.now(timezone.utc).isoformat()

            supabase.table("tokens_detectes").insert({
                "nom_jeton": token_name,
                "token_address": address,
                "pair_address": pair_address,
                "created_at": now,
                "dex_url": f"https://dexscreener.com/solana/{pair_address}",
                "marketcap": marketcap,
                "liquidity": liquidity,
                "top10_percent": top10
            }).execute()

            print(f"✅ Token désormais valide et inséré : {address}")

            # 🔄 Suppression de TokenIgnore
            supabase.table("TokenIgnore").delete().eq("TokenAddress", address).execute()

    except Exception as e:
        print(f"[ERREUR] {e}")


# 📡 Moralis – Récupère le top10 %
def get_holder_stats(token_address):
    try:
        url = f"https://solana-gateway.moralis.io/token/mainnet/holders/{token_address}"
        headers = {
            "accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"[❌ Moralis API Error] {response.status_code} – {token_address}")
            return None

        data = response.json()
        return round(data.get("holderSupply", {}).get("top10", {}).get("supplyPercent", 0), 2)
    except Exception as e:
        print(f"[❌ Moralis Exception] {e}")
        return None


# 🔁 Boucle infinie toutes les 10 min
if __name__ == "__main__":
    while True:
        recheck_tokens()
        time.sleep(600)  # 10 minutes
