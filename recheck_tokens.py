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

            # 🕒 Suppression après 2h
            if age > DUREE_MAX_ATTENTE:
                supabase.table("TokenIgnore").delete().eq("TokenAddress", address).execute()
                print(f"🗑 Supprimé après 2h sans données : {address}")
                continue

            # 🔎 Récupération des données DexScreener
            dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            response = requests.get(dex_url)
            if response.status_code != 200:
                print(f"⏳ Pas encore indexé sur DexScreener : {address}")
                continue

            pairs = response.json().get("pairs")
            if not pairs:
                print(f"⚠️ Aucune paire trouvée : {address}")
                continue

            pair = pairs[0]

            # ❌ Vérifications spécifiques
            if pair.get("chainId") != "solana":
                print(f"❌ Token hors Solana : {address}")
                continue

            if pair.get("dexId") not in ["raydium", "pumpswap"]:
                print(f"❌ DEX non autorisé : {address} ({pair.get('dexId')})")
                continue

            liquidity = pair.get("liquidity", {}).get("usd", 0)
            marketcap = pair.get("fdv", 0)
            twitter_url = pair.get("info", {}).get("twitter", "")
            description = pair.get("info", {}).get("description", "")

            if liquidity < 5000 or marketcap < 20000 or not twitter_url or not description:
                print(f"⛔️ Paramètres invalides : {address} (liq={liquidity}, mc={marketcap}, X={twitter_url}, desc={description})")
                continue

            # ✅ Vérifie le top 10
            top10 = get_holder_stats(address)
            if top10 is None or top10 > 60:
                print(f"🚫 Top10 trop élevé : {address} – {top10}%")
                continue

            # ✅ Si tout est OK, insérer dans tokens_detectes
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

            print(f"✅ Inséré dans tokens_detectes : {token_name} ({address})")

            # ❌ Suppression de TokenIgnore après succès
            supabase.table("TokenIgnore").delete().eq("TokenAddress", address).execute()

    except Exception as e:
        print(f"[ERREUR RECHECK] {e}")

# 🔁 Boucle infinie toutes les 10 minutes
if __name__ == "__main__":
    while True:
        recheck_tokens()
        time.sleep(600)
