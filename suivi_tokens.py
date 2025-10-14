import requests
import time
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# Supabase credentials
SUPABASE_URL = "https://mwnejkrkjlnrwrulqedd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im13bmVqa3JramxucndydWxxZWRkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM4OTc4NzYsImV4cCI6MjA2OTQ3Mzg3Nn0.6gCD-zi1nFK4m61bLBzYKmuE48ZqKOgVclelebO9vUk"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Plages de variation
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

# Seuils minimaux
SEUIL_MC = 20000
SEUIL_LIQ = 5000


# --------------------------- FETCH DES DONNÉES --------------------------- #
def fetch_price_data(token_address):
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 429:
            print(f"[⚠️ LIMITÉ PAR L'API] Trop de requêtes. Pause 30 sec…")
            time.sleep(30)
            return None

        if response.status_code != 200:
            print(f"[ERREUR HTTP] Code: {response.status_code} pour {token_address}")
            return None

        if not response.content:
            print(f"[ERREUR VIDE] Réponse vide pour {token_address}")
            return None

        data = response.json()
        if not data.get("pairs"):
            # ⚠️ Suppression automatique si aucune paire trouvée
            print(f"[SUPPRESSION AUTO - AUCUNE PAIRE] {token_address}")
            remove_token_completely(token_address)
            return None

        return data["pairs"][0]

    except Exception as e:
        print(f"[ERREUR FETCH PRIX] {e}")
        return None


# --------------------------- UTILITAIRES --------------------------- #
def get_old_price(token_address, minutes_ago, tolerance=6):
    """
    Récupère le prix du token autour de l'instant visé (± tolerance minutes).
    Si rien trouvé, retourne la valeur la plus proche *avant* T-interval.
    """
    try:
        response = supabase.table("suivi_tokens") \
            .select("created_at, price") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .execute()

        if not response.data:
            return None

        now = datetime.now(timezone.utc)
        target_time = now - timedelta(minutes=minutes_ago)

        closest_in_window = None
        min_diff = float("inf")
        fallback_price = None
        fallback_time = None

        for record in response.data:
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            price = float(record["price"])
            delta_minutes = abs((created - target_time).total_seconds()) / 60

            if delta_minutes <= tolerance and delta_minutes < min_diff:
                closest_in_window = price
                min_diff = delta_minutes

            # fallback : on prend la plus proche avant target_time
            if created < target_time:
                if not fallback_time or created > fallback_time:
                    fallback_price = price
                    fallback_time = created

        if closest_in_window is not None:
            return closest_in_window

        return fallback_price  # Peut être None si aucun fallback non plus

    except Exception as e:
        print(f"[ERREUR GET OLD PRICE {minutes_ago}min] {e}")
        return None



def is_token_frozen(token_address):
    """
    Considère un token comme figé si TOUTES les variations
    var_5, var_15, var_30, var_45, var_1h dans les 60 dernières minutes
    sont comprises entre -0.1% et +0.1%.
    """
    try:
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(minutes=60)

        response = supabase.table("suivi_tokens") \
            .select("created_at, var_5, var_15, var_30, var_45, var_1h") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()

        if not response.data:
            return False

        # Récupère la dernière ligne dans les 60 dernières minutes
        for record in response.data:
            created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            if created < one_hour_ago:
                continue

            variations = [
                record.get("var_5"),
                record.get("var_15"),
                record.get("var_30"),
                record.get("var_45"),
                record.get("var_1h"),
            ]

            if any(v is None for v in variations):
                return False  # Pas assez de données

            if all(-0.1 <= v <= 0.1 for v in variations):
                print(f"[🧊 FIGÉ] Token {token_address} : variations < 0.1% sur 1h")
                return True

        return False

    except Exception as e:
        print(f"[ERREUR FIGÉ] {e}")
        return False



def should_remove_token(token_address):
    """Vérifie si le token doit être supprimé pour inactivité ou chute importante"""
    try:
        # Supprimer si aucune mise à jour depuis 3 jours
        last_update = supabase.table("suivi_tokens") \
            .select("created_at") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if last_update.data:
            last_date = datetime.fromisoformat(last_update.data[0]["created_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - last_date).days > 3:
                print(f"[🕒] Pas de mise à jour depuis 3 jours : {token_address}")
                return True

        # Supprimer si chute > 80% par rapport au marketcap max
        max_mc_resp = supabase.table("suivi_tokens") \
            .select("marketcap") \
            .eq("token_address", token_address) \
            .order("marketcap", desc=True) \
            .limit(1) \
            .execute()

        if not max_mc_resp.data:
            return False

        max_mc = float(max_mc_resp.data[0].get("marketcap", 0))

        current_mc_resp = supabase.table("suivi_tokens") \
            .select("marketcap") \
            .eq("token_address", token_address) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        current_mc = float(current_mc_resp.data[0].get("marketcap", 0))

        if max_mc > 0:
            drop = ((max_mc - current_mc) / max_mc) * 100
            if drop >= 80:
                print(f"[📉] Token a chuté de +80% (par rapport au max) : {token_address}")
                return True

        return False
    except Exception as e:
        print(f"[ERREUR CHECK CHUTE] {e}")
        return False


def remove_token_completely(token_address):
    """Supprime le token des tables de suivi"""
    try:
        supabase.table("suivi_tokens").delete().eq("token_address", token_address).execute()
        supabase.table("tokens_detectes").delete().eq("token_address", token_address).execute()
        print(f"[🚫] Token supprimé : {token_address}")
    except Exception as e:
        print(f"[ERREUR SUPPRESSION TOKEN] {e}")


# --------------------------- SUIVI DU TOKEN --------------------------- #
def track_token(token):
    token_address = token.get("token_address")
    raw_name = token.get("nom_jeton", "N/A")

    # Nettoyage du nom
    nom_jeton = ' '.join(raw_name.split()).strip()
    if len(nom_jeton) > 60:
        nom_jeton = nom_jeton[:57] + "..."

    # Récupération des données depuis Dexscreener
    data = fetch_price_data(token_address)
    if not data:
        return "removed"

    try:
        price = float(data.get("priceUsd", 0))
        liquidity = float(data.get("liquidity", {}).get("usd", 0))
        marketcap = float(data.get("fdv", 0))
    except:
        print(f"[ERREUR CONVERSION VALEURS] {token_address}")
        return "error"

    # ⚠️ Suppression automatique si sous-seuil
    if marketcap < SEUIL_MC or liquidity < SEUIL_LIQ:
        print(f"[SUPPRESSION AUTO - SOUS SEUIL] {token_address} | MC: {marketcap} | LIQ: {liquidity}")
        remove_token_completely(token_address)
        return "removed"

    # ⚠️ Suppression si figé depuis 15 min (aucune update + var_5 = 0)
    if is_token_frozen(token_address):
        print(f"[SUPPRESSION AUTO - FIGÉ] {token_address}")
        remove_token_completely(token_address)
        return "removed"

    # ⚠️ Suppression si chute ou inactivité prolongée
    if should_remove_token(token_address):
        remove_token_completely(token_address)
        return "removed"

    # Calcul des variations
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
        return "suivi_ok"
    except Exception as e:
        print(f"[ERREUR INSERT SUIVI] {e}")
        return "error"


# --------------------------- BOUCLE PRINCIPALE --------------------------- #
def main():
    print("[SUIVI EN COURS]")
    start_time = time.time()
    counters = {"suivi_ok": 0, "ignored": 0, "error": 0, "removed": 0}

    try:
        response = supabase.table("tokens_detectes").select("*").execute()
        for token in response.data:
            result = track_token(token)
            if result in counters:
                counters[result] += 1
            time.sleep(0.5)
    except Exception as e:
        print(f"[ERREUR FETCH TOKENS DETECTES] {e}")

    elapsed = round(time.time() - start_time, 2)
    print(f"[FIN DE CYCLE] ✅ Suivis: {counters['suivi_ok']} | ⏭️ Ignorés: {counters['ignored']} | ❌ Erreurs: {counters['error']} | 🗑️ Supprimés: {counters['removed']} | ⏱️ Temps: {elapsed} sec")
    print("[PAUSE] 5 minutes…\n")


# --------------------------- BOUCLE INFINIE --------------------------- #
while True:
    main()
    # time.sleep(300)
