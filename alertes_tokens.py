import time
from datetime import datetime, timezone, timedelta
import os
import requests
from supabase import create_client, Client
from dotenv import load_dotenv
load_dotenv ()

# 🔐 Variables d’environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# 📦 Suivi des prix maximums pour chaque token
prix_max_token = {}  # 🆕 token_address → prix_max


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

# 🔎 Vérifie si token est suivi personnellement
def est_suivi_personnellement(token_address):
    try:
        result = supabase.table(TABLE_PERSO).select("suivi") \
            .eq("token_address", token_address).execute()
        if result.data and result.data[0].get("suivi", "").lower() == "oui":
            return True
        return False
    except Exception as e:
        print(f"[ERREUR VERIF SUIVI PERSO] {e}")
        return False


def generer_infos_supplementaires(token):
    try:
        token_address = token.get("token_address", "N/A")

        # 🔍 Récupération des infos depuis `tokens_detectes`
        infos = supabase.table("tokens_detectes") \
            .select("top10_percent, total_holders, created_at") \
            .eq("token_address", token_address) \
            .order("created_at") \
            .limit(1) \
            .execute()

        if infos.data:
            top10_percent = infos.data[0].get("top10_percent", "?")
            total_holders = infos.data[0].get("total_holders", "?")
            created_at = infos.data[0].get("created_at")
            holders_updated, top_updated = get_updated_holder_stats(token_address)

            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    date_detect = dt.strftime("%d/%m/%Y à %H:%M")
                except:
                    date_detect = "?"
            else:
                date_detect = "?"

            try:
                if isinstance(total_holders, (int, float)):
                    holders_str = f"{int(total_holders):,}".replace(",", " ")
                else:
                    holders_str = str(total_holders) if total_holders else "?"

                if isinstance(top10_percent, (int, float)):
                    top10_str = f"{float(top10_percent):.1f}%"
                else:
                    top10_str = str(top10_percent) if top10_percent else "?"

                if holders_updated is not None:
                    holders_str += f" ➡️ {holders_updated}"
                if top_updated is not None:
                    top10_str += f" ➡️ {top_updated}"

                return (
                    f"\n📌 *Token address* : `{token_address}`"
                    f"\n🕵️‍♂️ *Détecté le* : {date_detect}"
                    f"\n👥 *Holders* : {holders_str}"
                    f"\n🔟 *Top10* : {top10_str}"
                )

            except Exception as e:
                print(f"[ERREUR FORMATAGE INFOS SUPP] {e}")
                return ""

        else:
            return (
                f"\n📌 *Token address* : `{token_address}`"
                f"\n🕵️‍♂️ *Détecté le* : ?"
                f"\n👥 *Holders* : ?"
                f"\n🔟 *Top10* : ?"
            )

    except Exception as e:
        print(f"[ERREUR INFOS SUPP] {e}")
        return ""

    




def get_updated_holder_stats(token_address):
    try:
        url = f"https://deep-index.moralis.io/api/v2.2/token/mainnet/{token_address}/holder-stats"
        headers = {
            "accept": "application/json",
            "X-API-Key": os.getenv("MORALIS_API_KEY")
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            total_holders = data.get("total_holders")
            top10 = data.get("top_10_holders_percent")
            return total_holders, top10
        else:
            print(f"❌ Erreur Moralis ({response.status_code}) pour {token_address}")
            return None, None
    except Exception as e:
        print(f"[ERREUR Moralis Holders] {e}")
        return None, None



# 🧠 Détection des alertes
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

    
    # ⛔️ Ignorer si multiplicateur <= 1
    if isinstance(multiplicateur, (int, float)) and multiplicateur <= 1:
        print(f"[IGNORÉ] Multiplicateur trop faible ({multiplicateur}) pour {name}")
        return []

    # 🔺 Alertes haussières pour tous
    if token["var_15"] and token["var_15"] >= 100 or token["var_1h"] and token["var_1h"] >= 200:
        alerts.append(("hausse_soudaine", f"🚀 *HAUSSE SOUDAINE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}"))

    elif token["var_6h"] and token["var_6h"] >= 300 or token["var_12h"] and token["var_12h"] >= 500:
        alerts.append(("hausse_lente", f"📈 *HAUSSE LENTE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}"))

    elif token["var_1h"] and abs(token["var_1h"]) <= 5 and token["var_5"] and token["var_5"] >= 30:
        alerts.append(("hausse_differee", f"⏳ *HAUSSE APRÈS STAGNATION* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}"))

    elif all(token.get(p) and token[p] > 0 for p in PLAGES):
        alerts.append(("solidite", f"🧱 *TOKEN SOLIDE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien}){infos}"))

    # 🔺 Nouvelle alerte : hausse continue sur var_5
    try:
        rows = supabase.table(TABLE_SUIVI).select("var_5").eq("token_address", address).order("created_at", desc=True).limit(5).execute().data
        var5_list = [r["var_5"] for r in rows if r.get("var_5") is not None]
        if len(var5_list) >= 3:
            count_15p = sum(1 for v in var5_list if v >= 15)
            if count_15p >= 2:
                var5_str = ", ".join(f"{v:.1f}%" for v in var5_list)
                alerts.append((
                    "hausse_continue_var5",
                    f"⚡️ *HAUSSE RAPIDE EN COURS* : {name}\n`var_5` : [{var5_str}]\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}*\n🔗 [Trader sur Axiom]({lien}){infos}"))
                
    except Exception as e:
        print(f"[ERREUR HAUSSE CONTINUE] {e}")

    # 🔻 Alertes baissières personnalisées uniquement si suivi personnellement
    if est_suivi:
        seuils_baisse = list(range(30, 80, 5))  # [-30%, -35%, ..., -75%]
        if token["price"] and premier_prix:
            prix_max = prix_max_token.get(address, token["price"])
            baisse_pct = round((token["price"] - prix_max) / prix_max * 100, 2)
            for seuil in seuils_baisse:
                type_alerte = f"baisse_depuis_max_{seuil}"
                if baisse_pct <= -seuil and not alerte_deja_envoyee(address, type_alerte):
                    alerts.append((
                        type_alerte,
                        f"🔻 *CHUTE -{seuil}%* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"
                    ))

    return alerts
    


# 🔍 Récupère le dernier marketcap d'une alerte haussière envoyée
def dernier_mcap_alerte_hausse(token_address):
    try:
        result = supabase.table(TABLE_LOGS) \
            .select("created_at") \
            .eq("token_address", token_address) \
            .in_("type_alerte", ["hausse_soudaine", "hausse_lente", "hausse_differee", "solidite", "hausse_continue_var5"]) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        if result.data:
            alerte_time = result.data[0]["created_at"]
            # Va chercher le marketcap à ce moment-là
            snap = supabase.table(TABLE_SUIVI) \
                .select("marketcap") \
                .eq("token_address", token_address) \
                .lte("created_at", alerte_time) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if snap.data:
                return snap.data[0]["marketcap"]
    except Exception as e:
        print(f"[ERREUR DERNIER MCAP] {e}")
    return 0


def mettre_a_jour_date_suivi():
    try:
        result = supabase.table("tokens_suivis_personnels") \
            .select("token_address, date_suivi") \
            .eq("suivi", "oui") \
            .is_("date_suivi", "null") \
            .execute()

        tokens_a_mettre_a_jour = result.data

        if not tokens_a_mettre_a_jour:
            return

        now = datetime.now(timezone.utc).isoformat()

        for token in tokens_a_mettre_a_jour:
            address = token["token_address"]
            supabase.table("tokens_suivis_personnels").update({
                "date_suivi": now
            }).eq("token_address", address).execute()
            print(f"🕒 Date de suivi ajoutée pour {address}")

    except Exception as e:
        print(f"[ERREUR DATE_SUIVI] {e}")






# ▶️ MAIN
def verifier_alertes():
    print(f"\n[🔔 CYCLE ALERTES] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mettre_a_jour_date_suivi()  # Met à jour la date_suivi si manquante
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

            # 🧠 Analyse des scénarios classiques (hausses, solidité, etc.)
            premier = supabase.table(TABLE_SUIVI).select("price").eq("token_address", token_address).order("created_at").limit(1).execute().data
            premier_prix = premier[0]["price"] if premier else None
            scenarios = detecter_scenarios(token, premier_prix, est_suivi)

            # ➕ Scénario supplémentaire : baisse depuis prix max
            if est_suivi and prix_actuel and token_address in prix_max_token:
                prix_max = prix_max_token[token_address]
                baisse_pct = round((prix_actuel - prix_max) / prix_max * 100, 2)

                if baisse_pct <= -30 and not alerte_deja_envoyee(token_address, "baisse_depuis_max_30"):
                    n = nombre_alertes_envoyees(token_address) + 1
                    send_telegram_alert(
                        f"📉 *CHUTE -30%* (depuis max) : {token.get('nom_jeton')} ({n}e alerte)\n*Prix max* : {prix_max:.4f} ➡ *Actuel* : {prix_actuel:.4f}\n🔗 [Trader sur Axiom](https://axiom.trade/meme/{token.get('pair_address')})"
                    )
                    enregistrer_alerte(token_address, "baisse_depuis_max_30")

                if baisse_pct <= -60 and not alerte_deja_envoyee(token_address, "baisse_depuis_max_60"):
                    n = nombre_alertes_envoyees(token_address) + 1
                    send_telegram_alert(
                        f"⚠️ *CHUTE -60%* (depuis max) : {token.get('nom_jeton')} ({n}e alerte)\n*Prix max* : {prix_max:.4f} ➡ *Actuel* : {prix_actuel:.4f}\n🔗 [Trader sur Axiom](https://axiom.trade/meme/{token.get('pair_address')})"
                    )
                    enregistrer_alerte(token_address, "baisse_depuis_max_60")

            # ✅ NOUVELLE LOGIQUE : ALERTE BAISSE SELON DATE_SUIVI
            if est_suivi and prix_actuel:
                # On récupère la date d'entrée
                suivi = supabase.table(TABLE_PERSO).select("date_suivi", "prix_entree").eq("token_address", token_address).execute()
                if suivi.data:
                    date_suivi = suivi.data[0].get("date_suivi")
                    prix_entree = suivi.data[0].get("prix_entree")

                    if date_suivi:
                        # Récupère le prix le plus proche de la date_suivi
                        snap = supabase.table(TABLE_SUIVI).select("price") \
                            .eq("token_address", token_address) \
                            .lte("created_at", date_suivi) \
                            .order("created_at", desc=True) \
                            .limit(1).execute()

                        if snap.data and snap.data[0].get("price"):
                            prix_base = snap.data[0]["price"]
                            multiplicateur = round(prix_actuel / prix_base, 2)

                            baisse_pct = round((prix_actuel - prix_base) / prix_base * 100, 2)

                            for seuil in range(-30, -80, 5):
                                type_alerte = f"baisse_{abs(seuil)}"
                                if baisse_pct <= seuil and not alerte_deja_envoyee(token_address, type_alerte):
                                    n = nombre_alertes_envoyees(token_address) + 1
                                    send_telegram_alert(
                                        f"📉 *CHUTE {seuil}%* : {token.get('nom_jeton')} ({n}e alerte)\n*MCAP* : {int(token['marketcap']):,} $\n*x{multiplicateur}* depuis suivi perso\n🔗 [Trader sur Axiom](https://axiom.trade/meme/{token.get('pair_address')})"
                                    )
                                    enregistrer_alerte(token_address, type_alerte)

            # 🔁 Alertes classiques (hausses et autres)
            for type_alerte, message in scenarios:
                is_hausse = type_alerte in ["hausse_soudaine", "hausse_lente", "hausse_differee", "solidite", "hausse_continue_var5"]

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



def main():
    verifier_alertes()


# 🔁 Boucle infinie (toutes les 60 sec)
if __name__ == "__main__":
    while True:
        main()
        time.sleep(60)
