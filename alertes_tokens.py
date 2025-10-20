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

    # ⛔️ Ignorer si multiplicateur <= 1
    if isinstance(multiplicateur, (int, float)) and multiplicateur <= 1:
        print(f"[IGNORÉ] Multiplicateur trop faible ({multiplicateur}) pour {name}")
        return []

    # 🔺 Alertes haussières pour tous
    if token["var_15"] and token["var_15"] >= 100 or token["var_1h"] and token["var_1h"] >= 200:
        alerts.append(("hausse_soudaine", f"🚀 *HAUSSE SOUDAINE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif token["var_6h"] and token["var_6h"] >= 300 or token["var_12h"] and token["var_12h"] >= 500:
        alerts.append(("hausse_lente", f"📈 *HAUSSE LENTE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif token["var_1h"] and abs(token["var_1h"]) <= 5 and token["var_5"] and token["var_5"] >= 30:
        alerts.append(("hausse_differee", f"⏳ *HAUSSE APRÈS STAGNATION* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

    elif all(token.get(p) and token[p] > 0 for p in PLAGES):
        alerts.append(("solidite", f"🧱 *TOKEN SOLIDE* : {name}\n*MCAP* : {int(mcap):,} $\n*x{multiplicateur}* depuis détection ({heures}h)\n🔗 [Trader sur Axiom]({lien})"))

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
                    f"⚡️ *HAUSSE RAPIDE EN COURS* : {name}\n`var_5` : [{var5_str}]\n*MCAP* : {int(mcap):,} $\n*{count_15p}/5 à +15 %* • x{multiplicateur} ({heures}h)\n🔗 [Trader sur Axiom]({lien})"
                ))
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
def main():
    print(f"\n[🔔 CYCLE ALERTES] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mettre_a_jour_date_suivi()  # ⬅️ Ajoute cette ligne ici
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

# 🔁 Boucle infinie
while True:
    main()
    time.sleep(60)
