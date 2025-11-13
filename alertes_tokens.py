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
MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 📦 Suivi des prix maximums pour chaque token
prix_max_token = {}

# 📊 Plages temporelles
PLAGES = ["var_5", "var_15", "var_30", "var_45", "var_1h", "var_3h", "var_6h", "var_12h", "var_24h"]
COOLDOWN_MINUTES = 10

TABLE_SUIVI = "suivi_tokens"
TABLE_LOGS = "alertes_envoyees"
TABLE_PERSO = "tokens_suivis_personnels"

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

# ⏱ Vérifie si une alerte identique a déjà été envoyée
def alerte_deja_envoyee(token_address, type_alerte):
    try:
        limite = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES)
        result = supabase.table(TABLE_LOGS).select("*") \
            .eq("token_address", token_address) \
            .eq("type_alerte", type_alerte) \
            .gte("created_at", limite.isoformat()).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[ERREUR VERIF LOG] {e}")
        return False

# 🔢 Compte le nombre d'alertes déjà envoyées pour ce token
def nombre_alertes_envoyees(token_address):
    try:
        result = supabase.table(TABLE_LOGS).select("id").eq("token_address", token_address).execute()
        return len(result.data)
    except Exception as e:
        print(f"[ERREUR COMPTE ALERTES] {e}")
        return 0

# ✅ Enregistre l’envoi
def enregistrer_alerte(token_address, type_alerte):
    try:
        supabase.table(TABLE_LOGS).insert({
            "token_address": token_address,
            "type_alerte": type_alerte,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        print(f"[ERREUR INSERT LOG] {e}")

# ✅ Vérifie si le token est marqué comme suivi personnellement
def est_suivi_personnellement(token_address):
    try:
        result = supabase.table(TABLE_PERSO).select("suivi") \
            .eq("token_address", token_address).execute()
        return result.data and result.data[0].get("suivi", "").lower() == "oui"
    except Exception as e:
        print(f"[ERREUR VERIF SUIVI PERSO] {e}")
        return False

# 🔁 Récupère les infos initiales de détection
def get_infos_initiales(token_address):
    try:
        infos = supabase.table("tokens_detectes") \
            .select("top10_percent, total_holders, created_at") \
            .eq("token_address", token_address) \
            .order("created_at") \
            .limit(1) \
            .execute()

        if infos.data:
            data = infos.data[0]
            return {
                "top10_percent": data.get("top10_percent", "?"),
                "total_holders": data.get("total_holders", "?"),
                "created_at": data.get("created_at", None)
            }
    except Exception as e:
        print(f"[ERREUR INFOS INITIALES] {e}")
    return {}

# 📡 Interroge Moralis pour les nouvelles infos
def get_infos_actuelles(token_address):
    try:
        url = f"https://mainnet.g.alchemy.com/v2/{MORALIS_API_KEY}/getTokenHolderStats?address={token_address}"
        headers = {
            "accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }
        response = requests.get(f"https://deep-index.moralis.io/api/v2.2/erc20/{token_address}/holders", headers=headers)
        if response.status_code == 200:
            data = response.json()
            return {
                "top10_percent": data.get("top_10_holders_percent", "?"),
                "total_holders": data.get("total_holders", "?")
            }
    except Exception as e:
        print(f"[ERREUR MORALIS STATS] {e}")
    return {}

# 🔚 Génère le bloc avec flèches ➡️ à ajouter à la fin de chaque message
def generer_bloc_fleches(token_address):
    initial = get_infos_initiales(token_address)
    actuel = get_infos_actuelles(token_address)

    try:
        holders_old = int(initial.get("total_holders", 0))
        holders_new = int(actuel.get("total_holders", 0))
        top10_old = float(initial.get("top10_percent", 0))
        top10_new = float(actuel.get("top10_percent", 0))

        holders_str = f"{holders_old:,}".replace(",", " ") + " ➡️ " + f"{holders_new:,}".replace(",", " ")
        top10_str = f"{top10_old:.1f} % ➡️ {top10_new:.1f} %"

        return f"\n👥 *Holders* : {holders_str}\n🔟 *Top10* : {top10_str}"
    except Exception as e:
        print(f"[ERREUR FORMATAGE FLÈCHES] {e}")
        return ""


def detecter_scenarios(token, premier_prix, est_suivi):
    alerts = []
    name = token.get("nom_jeton") or "Token"
    address = token.get("token_address")
    pair = token.get("pair_address", "")
    lien = f"https://axiom.trade/meme/{pair}"
    prix_actuel = token.get("price")
    mcap = token.get("marketcap")
    debut = datetime.fromisoformat(token["created_at"].replace("Z", "+00:00"))
    heures = int((datetime.now(timezone.utc) - debut).total_seconds() // 3600)
    multiplicateur = round(prix_actuel / premier_prix, 2) if premier_prix else "?"
    infos = generer_infos_supplementaires(token)
    fleches = generer_bloc_fleches(address)

    if isinstance(multiplicateur, (int, float)) and multiplicateur <= 1:
        print(f"[IGNORÉ] Multiplicateur trop faible ({multiplicateur}) pour {name}")
        return []

    if token["var_15"] and token["var_15"] >= 100 or token["var_1h"] and token["var_1h"] >= 200:
        alerts.append(("hausse_soudaine", f"🚀 *HAUSSE SOUDAINE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"))

    elif token["var_6h"] and token["var_6h"] >= 300 or token["var_12h"] and token["var_12h"] >= 500:
        alerts.append(("hausse_lente", f"📈 *HAUSSE LENTE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"))

    elif token["var_1h"] and abs(token["var_1h"]) <= 5 and token["var_5"] and token["var_5"] >= 30:
        alerts.append(("hausse_differee", f"⏳ *HAUSSE APRÈS STAGNATION* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"))

    elif all(token.get(p) and token[p] > 0 for p in PLAGES):
        alerts.append(("solidite", f"🧱 *TOKEN SOLIDE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"))

    try:
        rows = supabase.table(TABLE_SUIVI).select("var_5").eq("token_address", address).order("created_at", desc=True).limit(5).execute().data
        var5_list = [r["var_5"] for r in rows if r.get("var_5") is not None]
        if len(var5_list) >= 3:
            count_15p = sum(1 for v in var5_list if v >= 15)
            if count_15p >= 2:
                var5_str = ", ".join(f"{v:.1f}%" for v in var5_list)
                alerts.append((
                    "hausse_continue_var5",
                    f"⚡️ *HAUSSE RAPIDE EN COURS* : {name}\n`var_5` : [{var5_str}]\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}*\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"
                ))
    except Exception as e:
        print(f"[ERREUR HAUSSE CONTINUE] {e}")

    # 🔻 Alertes de baisse sur tokens suivis personnellement
    if est_suivi:
        try:
            result = supabase.table(TABLE_PERSO).select("prix_entree").eq("token_address", address).limit(1).execute()
            if result.data:
                prix_entree = result.data[0]["prix_entree"]
                if prix_entree:
                    variation = (prix_actuel - prix_entree) / prix_entree * 100
                    seuils = [-30, -35, -40, -45, -50, -55, -60, -65, -70, -75]
                    for s in seuils:
                        if variation <= s and not alerte_deja_envoyee(address, f"baisse_{abs(s)}"):
                            alerts.append((f"baisse_{abs(s)}", f"📉 *BAISSE* : {name}\n{round(variation, 2)} % depuis prix d’entrée\n🔗 [Trader sur Axiom]({lien}){infos}{fleches}"))
                            break
        except Exception as e:
            print(f"[ERREUR BAISSE] {e}")

    return alerts

def verifier_alertes():
    print(f"\n[🔔 CYCLE ALERTES] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        rows = supabase.table(TABLE_SUIVI).select("*").order("created_at", desc=True).execute().data
        tokens_uniques = {}
        for r in rows:
            addr = r["token_address"]
            if addr not in tokens_uniques:
                tokens_uniques[addr] = r

        for token in tokens_uniques.values():
            token_address = token["token_address"]
            prix_actuel = token.get("price")
            est_suivi = est_suivi_personnellement(token_address)

            # 🔼 Suivi du prix maximum
            if prix_actuel:
                if token_address not in prix_max_token:
                    prix_max_token[token_address] = prix_actuel
                else:
                    if prix_actuel > prix_max_token[token_address]:
                        prix_max_token[token_address] = prix_actuel

            premier = supabase.table(TABLE_SUIVI).select("price").eq("token_address", token_address).order("created_at").limit(1).execute().data
            premier_prix = premier[0]["price"] if premier else None
            scenarios = detecter_scenarios(token, premier_prix, est_suivi)

            for type_alerte, message in scenarios:
                is_hausse = type_alerte.startswith("hausse")

                if not alerte_deja_envoyee(token_address, type_alerte):
                    if is_hausse:
                        dernier_mcap = dernier_mcap_alerte_hausse(token_address)
                        if token["marketcap"] < dernier_mcap:
                            print(f"[🔕] Alerte haussière ignorée (mcap {token['marketcap']} < {dernier_mcap}) pour {token.get('nom_jeton')}")
                            continue

                    n = nombre_alertes_envoyees(token_address) + 1
                    message_modifie = message.replace(": ", f" ({n}e alerte) : ", 1)
                    send_telegram_alert(message_modifie)
                    enregistrer_alerte(token_address, type_alerte)
                else:
                    print(f"[🔕] Alerte ignorée (déjà envoyée) : {type_alerte} pour {token.get('nom_jeton')}")

    except Exception as e:
        print(f"[ERREUR PRINCIPALE] {e}")

# ▶️ BOUCLE PRINCIPALE
def main():
    verifier_alertes()

if __name__ == "__main__":
    while True:
        main()
        time.sleep(60)
