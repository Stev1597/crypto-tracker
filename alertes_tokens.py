import time
from datetime import datetime, timezone, timedelta
import os
import requests
from supabase import create_client, Client

# 🔐 Variables d’environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 📊 Plages temporelles
PLAGES = ["var_5", "var_15", "var_30", "var_45", "var_1h", "var_3h", "var_6h", "var_12h", "var_24h"]
COOLDOWN_MINUTES = 30  # délai minimal entre deux alertes identiques

TABLE_SUIVI = "suivi_tokens"
TABLE_LOGS = "alertes_envoyees"

# 📤 Envoi Telegram
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"[ERREUR ENVOI TELEGRAM] {response.text}")
    except Exception as e:
        print(f"[ERREUR TELEGRAM] {e}")

# 🔁 Vérifie si une alerte identique a déjà été envoyée récemment
def alerte_deja_envoyee(token_address, type_alerte):
    try:
        limite = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES)
        result = supabase.table(TABLE_LOGS).select("*") \
            .eq("token_address", token_address) \
            .eq("type_alerte", type_alerte) \
            .gte("horodatage", limite.isoformat()).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[ERREUR VERIF LOG] {e}")
        return False

# 📝 Enregistre l’envoi d’une alerte
def enregistrer_alerte(token_address, type_alerte):
    try:
        supabase.table(TABLE_LOGS).insert({
            "token_address": token_address,
            "type_alerte": type_alerte,
            "horodatage": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        print(f"[ERREUR INSERT LOG] {e}")

# 🔍 Détecte les scénarios d'alerte
def detecter_scenarios(token, premier_prix):
    alerts = []
    name = token.get("nom_jeton") or "Token"
    address = token.get("token_address")
    lien = f"https://dexscreener.com/solana/{address}"

    prix_actuel = token.get("price")
    mcap = token.get("marketcap")
    debut = datetime.fromisoformat(token["created_at"].replace("Z", "+00:00"))
    heures = int((datetime.now(timezone.utc) - debut).total_seconds() // 3600)

    multiplicateur = round(prix_actuel / premier_prix, 2) if premier_prix else "?"

    if token["var_15"] and token["var_15"] >= 100 or token["var_1h"] and token["var_1h"] >= 200:
        alerts.append(("hausse_soudaine", f"🚀 *HAUSSE SUDDAINE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif token["var_6h"] and token["var_6h"] >= 300 or token["var_12h"] and token["var_12h"] >= 500:
        alerts.append(("hausse_lente", f"📈 *HAUSSE LENTE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif token["var_60"] and abs(token["var_60"]) <= 5 and token["var_5"] and token["var_5"] >= 30:
        alerts.append(("hausse_differee", f"⏳ *HAUSSE APRÈS STAGNATION* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif token["var_1h"] and token["var_1h"] <= -80 or token["var_3h"] and token["var_3h"] <= -90:
        alerts.append(("chute_brutale", f"⚠️ *CHUTE BRUTALE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif all(token.get(p) and token[p] > 0 for p in PLAGES):
        alerts.append(("solidite", f"🧱 *TOKEN SOLIDE* : {name} progresse sur toutes les périodes\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    return alerts

# ▶️ MAIN
def main():
    print(f"\n[🔔 CYCLE ALERTES] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        rows = supabase.table(TABLE_SUIVI).select("*").order("created_at", desc=True).execute().data
        tokens_uniques = {}
        for r in rows:
            addr = r["token_address"]
            if addr not in tokens_uniques:
                tokens_uniques[addr] = r

        for token in tokens_uniques.values():
            premier_enregistrement = supabase.table(TABLE_SUIVI).select("price").eq("token_address", token["token_address"]).order("created_at").limit(1).execute().data
            premier_prix = premier_enregistrement[0]["price"] if premier_enregistrement else None

            scenarios = detecter_scenarios(token, premier_prix)
            for type_alerte, message in scenarios:
                if token.get("suivi_personnel") or not alerte_deja_envoyee(token["token_address"], type_alerte):
                    send_telegram_alert(message)
                    enregistrer_alerte(token["token_address"], type_alerte)
                else:
                    print(f"[🔕] Alerte ignorée (déjà envoyée) : {type_alerte} pour {token.get('nom_jeton')}")
    except Exception as e:
        print(f"[ERREUR PRINCIPALE] {e}")

# 🔁 Boucle infinie
while True:
    main()
    time.sleep(60)  # Tu peux retirer la pause ici si tu veux une analyse sans interruption
