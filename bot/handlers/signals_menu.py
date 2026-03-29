"""Signals topic menu — V3 Multi-tenant.

Menu complet du topic 📊 Signals avec explications précises de chaque paramètre.
Toutes les définitions sont tirées directement du code (signal_scorer.py, smart_filter.py).

Callbacks gérés (pattern "^sig_"):
  sig_profile_menu            → liste des profils
  sig_set_profile:{key}       → appliquer un profil preset
  sig_criteria_menu           → liste des 6 critères de scoring
  sig_criterion:{name}        → fiche complète d'un critère
  sig_toggle_crit:{name}      → activer / désactiver un critère
  sig_weight:{name}:{value}   → changer le poids d'un critère
  sig_smartfilter_menu        → panneau Smart Filter
  sig_sf_detail:{filter}      → fiche complète d'un filtre Smart Filter
  sig_back                    → retour au menu principal Signals
"""

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id, get_or_create_settings
from bot.utils.formatting import bar, SEP

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PROFILS PRÉDÉFINIS
# ═══════════════════════════════════════════════════════════════

PROFILES: dict[str, dict] = {
    "prudent": {
        "label":       "🛡️ Prudent",
        "description": (
            "Critères stricts — moins de trades, meilleure qualité.\n"
            "Focus sur la liquidité et la forme récente du trader.\n"
            "Idéal pour préserver le capital."
        ),
        "min_signal_score":       65,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":   True,
        "skip_coin_flip":         True,
        "min_conviction_pct":     3.0,
        "scoring_criteria": {
            "spread":      {"on": True, "w": 20},
            "liquidity":   {"on": True, "w": 25},
            "conviction":  {"on": True, "w": 20},
            "trader_form": {"on": True, "w": 25},
            "timing":      {"on": True, "w": 5},
            "consensus":   {"on": True, "w": 5},
        },
    },
    "balanced": {
        "label":       "⚖️ Équilibré",
        "description": (
            "Configuration recommandée. Tous les critères actifs\n"
            "avec les poids par défaut. Bon équilibre volume/qualité."
        ),
        "min_signal_score":       40,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":   True,
        "skip_coin_flip":         True,
        "min_conviction_pct":     2.0,
        "scoring_criteria":       None,
    },
    "aggressive": {
        "label":       "⚡ Agressif",
        "description": (
            "Seuil bas, spread et timing ignorés.\n"
            "Focus conviction + forme trader. Plus de trades, plus de risque."
        ),
        "min_signal_score":       20,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":   False,
        "skip_coin_flip":         False,
        "min_conviction_pct":     1.0,
        "scoring_criteria": {
            "spread":      {"on": False, "w": 0},
            "liquidity":   {"on": True,  "w": 15},
            "conviction":  {"on": True,  "w": 40},
            "trader_form": {"on": True,  "w": 35},
            "timing":      {"on": False, "w": 0},
            "consensus":   {"on": True,  "w": 10},
        },
    },
    "all_pass": {
        "label":       "🎲 Tout passe",
        "description": (
            "⚠️ Scoring désactivé — TOUS les signaux sont copiés sans filtre.\n"
            "Recommandé uniquement en paper trading pour observer le comportement brut."
        ),
        "min_signal_score":       0,
        "signal_scoring_enabled": False,
        "smart_filter_enabled":   False,
        "skip_coin_flip":         False,
        "min_conviction_pct":     0.0,
        "scoring_criteria":       None,
    },
}

DEFAULT_CRITERIA_CONFIG = {
    "spread":      {"on": True, "w": 15},
    "liquidity":   {"on": True, "w": 15},
    "conviction":  {"on": True, "w": 20},
    "trader_form": {"on": True, "w": 20},
    "timing":      {"on": True, "w": 15},
    "consensus":   {"on": True, "w": 15},
}

CRITERIA_ORDER = ["spread", "liquidity", "conviction", "trader_form", "timing", "consensus"]


# ═══════════════════════════════════════════════════════════════
# FICHES PRÉCISES DES 6 CRITÈRES DE SCORING
# Chaque définition vient directement du code signal_scorer.py
# ═══════════════════════════════════════════════════════════════

CRITERIA_INFO: dict[str, dict] = {

    "spread": {
        "label": "📏 Spread bid-ask",
        "short": "Écart entre le meilleur prix d'achat et de vente",
        "what": (
            "*📏 SPREAD BID-ASK*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`spread% = (best_ask − best_bid) / best_ask × 100`\n\n"
            "*Données sources :*\n"
            "Carnet d'ordres CLOB Polymarket en temps réel au moment du signal.\n"
            "`best_bid` = meilleur prix proposé par les acheteurs\n"
            "`best_ask` = meilleur prix proposé par les vendeurs\n\n"
            "*Pourquoi ça compte :*\n"
            "Si le spread est de 5%, tu perds immédiatement 5% à l'entrée avant même "
            "que le marché bouge. Exemple : YES cote $0.50 bid / $0.55 ask → tu achètes "
            "à $0.55 pour quelque chose que tu pourrais revendre à $0.50 maintenant.\n\n"
            "*Barème de scoring :*\n"
            "🟢 `< 1%` → *100 pts* — marché très liquide, excellent\n"
            "🟡 `1–2%` → *80 pts* — bon\n"
            "🟠 `2–3%` → *60 pts* — acceptable\n"
            "🔴 `3–5%` → *30 pts* — méfiance, coût élevé\n"
            "⛔ `> 5%` → *0 pts* — éviter absolument"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },

    "liquidity": {
        "label": "💧 Liquidité",
        "short": "Volume total échangé sur ce marché en 24h (USDC)",
        "what": (
            "*💧 LIQUIDITÉ*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`score = f(intel.volume_24h)`\n\n"
            "*Données sources :*\n"
            "API Polymarket — volume total USDC échangé sur ce marché\n"
            "durant les dernières 24 heures.\n\n"
            "*Pourquoi ça compte :*\n"
            "Un marché peu liquide = peu de contreparties disponibles.\n"
            "Si tu veux vendre et qu'il n'y a personne en face, tu es bloqué "
            "ou tu vends à un prix catastrophique. Un volume élevé garantit "
            "que tu peux entrer ET sortir à tout moment.\n\n"
            "*Barème de scoring :*\n"
            "🟢 `≥ $500 000` → *100 pts* — très actif\n"
            "🟡 `≥ $100 000` → *80 pts* — bon volume\n"
            "🟠 `≥ $50 000` → *60 pts* — acceptable\n"
            "🔴 `≥ $10 000` → *40 pts* — faible, risque de slippage\n"
            "⛔ `< $10 000` → *10 pts* — très peu liquide, éviter"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },

    "conviction": {
        "label": "💪 Conviction du trader",
        "short": "Poids du trade dans le portfolio total du master",
        "what": (
            "*💪 CONVICTION DU TRADER*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`conviction% = (size × price) / portfolio_value × 100`\n\n"
            "*Détail des variables :*\n"
            "`size` = nombre de shares achetées par le master\n"
            "`price` = prix d'achat du master (en USDC par share)\n"
            "`size × price` = valeur totale USDC de ce trade\n"
            "`portfolio_value` = somme de `currentValue` de toutes\n"
            "les positions ouvertes du master sur Polymarket\n\n"
            "*Exemple concret :*\n"
            "Master a $10 000 de positions ouvertes.\n"
            "Il achète 500 shares YES à $0.60 → trade = $300\n"
            "Conviction = 300 / 10 000 = *3%* ✅\n\n"
            "Si le même master achète 10 shares à $0.60 → $6\n"
            "Conviction = 6 / 10 000 = *0.06%* ❌ signal anecdotique\n\n"
            "*Barème de scoring :*\n"
            "🟢 `≥ 10%` → *100 pts* — très haute conviction\n"
            "🟡 `≥ 5%` → *80 pts* — bonne conviction\n"
            "🟠 `≥ 2%` → *60 pts* — conviction modérée\n"
            "⛔ `< 2%` → *20 pts* — trade anecdotique, signal faible"
        ),
        "default_w": 20,
        "weight_options": [10, 15, 20, 25, 30, 35, 40],
    },

    "trader_form": {
        "label": "📈 Forme du trader",
        "short": "Win rate du master sur les 7 derniers jours",
        "what": (
            "*📈 FORME DU TRADER*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`score = f(TraderStats.win_rate_7d)`\n\n"
            "*Données sources :*\n"
            "`TraderStats` table DB, période `7d`\n"
            "Calculé à partir des trades réels du master sur Polymarket\n"
            "(positions ouvertes + clôturées sur 7 jours glissants)\n\n"
            "*Ce qui est mesuré :*\n"
            "Win rate = % de trades gagnants sur les 7 derniers jours.\n"
            "Minimum 3 trades requis pour que ce critère soit fiable.\n"
            "Si < 3 trades sur 7j → score neutre de 50 pts par défaut.\n\n"
            "La série en cours (streak) est affichée en info mais\n"
            "n'influence pas directement le score.\n\n"
            "*Barème de scoring :*\n"
            "🟢 `≥ 70%` → *100 pts* — trader en feu 🔥\n"
            "🟡 `≥ 60%` → *80 pts* — bonne forme\n"
            "🟠 `≥ 50%` → *60 pts* — correct\n"
            "🔴 `≥ 40%` → *30 pts* — forme médiocre\n"
            "⛔ `< 40%` → *0 pts* — mauvaise passe, éviter"
        ),
        "default_w": 20,
        "weight_options": [10, 15, 20, 25, 30, 35, 40],
    },

    "timing": {
        "label": "⏱️ Timing",
        "short": "Heures restantes avant expiration du marché",
        "what": (
            "*⏱️ TIMING*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`hours = (intel.expiry − now).total_seconds() / 3600`\n\n"
            "*Données sources :*\n"
            "Date d'expiration du marché via API Polymarket.\n"
            "Calculé au moment exact où le signal est reçu.\n\n"
            "*Pourquoi ça compte :*\n"
            "• Trop court (< 30 min) : le résultat est quasi certain, "
            "les cotes ne bougent plus, risque élevé de ne pas être exécuté.\n"
            "• Zone idéale (2h–48h) : assez de temps pour que le trade "
            "évolue, pas assez pour immobiliser le capital.\n"
            "• Trop long (> 3 mois) : ton argent est bloqué des mois.\n\n"
            "*Barème de scoring :*\n"
            "⛔ Expiré → *0 pts*\n"
            "🔴 `< 30 min` → *20 pts* — trop risqué\n"
            "🟠 `30 min – 2h` → *50 pts* — court mais acceptable\n"
            "🟢 `2h – 48h` → *100 pts* — zone idéale ✓\n"
            "🟡 `2 – 7 jours` → *80 pts* — bon\n"
            "🟠 `7 – 30 jours` → *60 pts* — long terme\n"
            "🔴 `30 – 90 jours` → *40 pts* — capital bloqué longtemps\n"
            "⛔ `> 90 jours` → *20 pts* — trop lointain"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25],
    },

    "consensus": {
        "label": "👥 Consensus",
        "short": "Nombre de tes autres traders sur ce même marché",
        "what": (
            "*👥 CONSENSUS*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`count = nb de wallets suivis ayant token_id dans leurs positions`\n\n"
            "*Données sources :*\n"
            "Snapshot des positions de chaque wallet suivi stocké dans\n"
            "`MultiMasterMonitor._wallet_states`\n"
            "Comparaison par `token_id` (identifiant unique du côté YES/NO)\n\n"
            "*Ce qui est mesuré :*\n"
            "Combien de tes traders suivis (hors le master émetteur du signal)\n"
            "ont déjà une position ouverte sur le même token au moment du signal.\n\n"
            "*Exemple :*\n"
            "Tu suis 5 traders. Le signal vient de trader A.\n"
            "Traders B et C ont déjà YES sur ce marché → consensus = *2* 🟡\n\n"
            "⚠️ Consensus = 0 ne veut pas dire que c'est mauvais,\n"
            "juste qu'aucun autre trader suivi n'est positionné.\n\n"
            "*Barème de scoring :*\n"
            "🟢 `3 traders ou +` → *100 pts* — fort consensus\n"
            "🟡 `2 traders` → *70 pts* — bon signal\n"
            "🟠 `1 trader` → *40 pts* — signal isolé\n"
            "🔴 `0 autre trader` → *20 pts* — aucun consensus"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },
}


# ═══════════════════════════════════════════════════════════════
# FICHES PRÉCISES DES FILTRES SMART FILTER
# Chaque définition vient directement du code smart_filter.py
# ═══════════════════════════════════════════════════════════════

SMART_FILTER_INFO: dict[str, dict] = {

    "coin_flip": {
        "label": "🪙 Skip Coin-Flip",
        "setting": "skip_coin_flip",
        "short": "Ignore les marchés où YES coûte entre $0.45 et $0.55",
        "detail": (
            "*🪙 SKIP COIN-FLIP*\n"
            f"{SEP}\n\n"
            "*Définition exacte :*\n"
            "Un marché est considéré comme un 'coin-flip' si :\n"
            "`0.45 ≤ signal.price ≤ 0.55`\n\n"
            "C'est-à-dire que le prix du token YES est entre *$0.45 et $0.55*.\n\n"
            "*Ce que ça signifie :*\n"
            "Sur Polymarket, le prix d'un token YES représente la probabilité "
            "implicite que l'événement arrive. Un prix de $0.50 = le marché "
            "pense 50/50. Il n'y a *aucun edge* à copier un trade dans une situation "
            "où personne ne sait ce qui va se passer.\n\n"
            "*Exemple :*\n"
            "Marché : 'BTC au-dessus de $95K à 17h ?'\n"
            "Prix YES = $0.51 → coin-flip → *bloqué* ❌\n\n"
            "Marché : 'Trump gagnera en 2028 ?'\n"
            "Prix YES = $0.72 → pas un coin-flip → *autorisé* ✅\n\n"
            "*Quand le désactiver ?*\n"
            "Si tu veux copier même les marchés incertains (mode agressif)."
        ),
    },

    "conviction": {
        "label": "💪 Conviction minimum",
        "setting": "min_conviction_pct",
        "short": "% minimum du portfolio du trader que doit représenter le trade",
        "detail": (
            "*💪 CONVICTION MINIMUM (Smart Filter)*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`conviction = (signal.size × signal.price) / portfolio_value`\n"
            "`bloqué si conviction < min_conviction_pct / 100`\n\n"
            "*Variables :*\n"
            "`signal.size` = nombre de shares du trade master\n"
            "`signal.price` = prix de la share (USDC)\n"
            "`portfolio_value` = somme de `currentValue` de toutes les\n"
            "positions ouvertes du master récupérées via l'API Polymarket\n\n"
            "*Note :* Ce filtre fait le même calcul que le critère de scoring\n"
            "'Conviction' mais ici c'est un *filtre binaire* — en dessous du\n"
            "seuil le trade est bloqué directement, avant même le scoring.\n\n"
            "*Exemple avec seuil = 2% :*\n"
            "Master a $5 000 de portfolio.\n"
            "Trade de $80 → 80/5000 = 1.6% < 2% → *bloqué* ❌\n"
            "Trade de $150 → 150/5000 = 3% ≥ 2% → *autorisé* ✅\n\n"
            "*Valeurs recommandées :*\n"
            "🛡️ Prudent : 3% | ⚖️ Équilibré : 2% | ⚡ Agressif : 1%"
        ),
    },

    "drift": {
        "label": "📏 Drift de prix maximum",
        "setting": "max_price_drift_pct",
        "short": "% max d'écart entre le prix du master et le prix actuel",
        "detail": (
            "*📏 DRIFT DE PRIX MAXIMUM*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`drift% = |current_price − signal.price| / signal.price × 100`\n"
            "`bloqué si drift% > max_price_drift_pct`\n\n"
            "*Variables :*\n"
            "`signal.price` = prix auquel le master a acheté sa position\n"
            "`current_price` = prix actuel sur le CLOB Polymarket\n"
            "au moment où notre bot essaie de copier\n\n"
            "*Pourquoi ça compte :*\n"
            "Il y a toujours un délai entre le moment où le master achète\n"
            "et le moment où notre bot copie (détection + réseau + tx).\n"
            "Si le prix a déjà bougé de 8% depuis l'entrée du master,\n"
            "tu arrives trop tard et tu achètes plus cher que lui.\n\n"
            "*Exemple avec seuil = 5% :*\n"
            "Master achète YES à $0.60.\n"
            "Quand notre bot copie, YES vaut $0.63.\n"
            "Drift = |0.63−0.60| / 0.60 × 100 = *5%* → limite atteinte ❌\n\n"
            "YES vaut $0.61 → drift = 1.7% → *autorisé* ✅\n\n"
            "*Valeurs recommandées :*\n"
            "3-5% pour du temps réel | 8-10% si détection plus lente"
        ),
    },

    "trader_edge": {
        "label": "📊 Win rate par type de marché",
        "setting": "min_trader_winrate_for_type",
        "short": "WR minimum du trader sur la catégorie de ce marché",
        "detail": (
            "*📊 WIN RATE PAR TYPE DE MARCHÉ*\n"
            f"{SEP}\n\n"
            "*Formule exacte :*\n"
            "`market_type = categorize(signal.market_question)`\n"
            "`bloqué si history.win_rate < min_wr`\n"
            "`(uniquement si history.trades_count ≥ min_trades)`\n\n"
            "*Catégories détectées automatiquement :*\n"
            "`crypto_btc_5min` `crypto_btc_hourly` `crypto_btc_daily`\n"
            "`crypto_eth` `crypto_sol` `crypto_other`\n"
            "`politics_us` `politics_intl`\n"
            "`sports_nfl` `sports_nba` `sports_soccer` `sports_mlb`\n"
            "`economy_macro` `economy_stocks`\n"
            "`entertainment` `tech` `weather` `other`\n\n"
            "*Logique :*\n"
            "Un trader peut être excellent sur le BTC 5-min et nul sur la politique.\n"
            "Ce filtre vérifie que le master a un edge *sur ce type précis de marché*.\n\n"
            "Si le master n'a pas assez de données sur ce type (< min_trades) :\n"
            "→ le filtre est ignoré et le trade est autorisé par défaut.\n\n"
            "*Exemple avec seuil = 55%, min 10 trades :*\n"
            "Signal 'NBA : Lakers vainqueurs ce soir ?'\n"
            "Master a 15 trades sur sports_nba à 40% WR → *bloqué* ❌\n"
            "Master a 5 trades sur sports_nba → pas assez → *autorisé* ✅\n\n"
            "*Paramètres liés :*\n"
            "• Win rate minimum : ce que tu configures ici\n"
            "• Trades minimum (min_trader_trades_for_type) : seuil\n"
            "  de données requis pour activer le filtre"
        ),
    },

    "min_trades": {
        "label": "🔢 Trades minimum par catégorie",
        "setting": "min_trader_trades_for_type",
        "short": "Nb de trades requis pour activer le filtre WR par type",
        "detail": (
            "*🔢 TRADES MINIMUM PAR CATÉGORIE*\n"
            f"{SEP}\n\n"
            "*Rôle :*\n"
            "Ce paramètre définit combien de trades historiques le master\n"
            "doit avoir sur un type de marché pour que le filtre WR par\n"
            "catégorie soit activé.\n\n"
            "*Logique :*\n"
            "Si le master n'a que 3 trades sur `sports_nba`, on ne peut\n"
            "pas conclure qu'il est mauvais ou bon — c'est trop peu.\n"
            "Dans ce cas, le filtre est ignoré et le trade est autorisé.\n\n"
            "`bloqué` si trades ≥ min_trades ET win_rate < min_wr\n"
            "`autorisé` si trades < min_trades (pas assez de données)\n\n"
            "*Valeurs recommandées :*\n"
            "🛡️ Prudent : 8-10 trades min\n"
            "⚖️ Équilibré : 10 trades min\n"
            "⚡ Agressif : 5 trades min (filtre moins strict)"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
# DÉTECTION DU PROFIL ACTIF
# ═══════════════════════════════════════════════════════════════

def detect_active_profile(us) -> str:
    if not getattr(us, "signal_scoring_enabled", True):
        return "all_pass"
    min_score = float(getattr(us, "min_signal_score", 40))
    smart     = bool(getattr(us, "smart_filter_enabled", True))
    criteria  = getattr(us, "scoring_criteria", None)
    if min_score >= 65:
        return "prudent"
    if not smart and min_score <= 25:
        return "aggressive"
    if criteria is None and smart and 35 <= min_score <= 55:
        return "balanced"
    return "custom"


def _get_criteria_config(us) -> dict:
    raw = getattr(us, "scoring_criteria", None)
    if not raw:
        return dict(DEFAULT_CRITERIA_CONFIG)
    merged = dict(DEFAULT_CRITERIA_CONFIG)
    merged.update(raw)
    return merged


# ═══════════════════════════════════════════════════════════════
# MENU PRINCIPAL SIGNALS
# ═══════════════════════════════════════════════════════════════

async def show_signals_menu(update: Update, user, us) -> None:
    from bot.models.signal_score import SignalScore
    from sqlalchemy import select, func

    profile_key   = detect_active_profile(us)
    profile       = PROFILES.get(profile_key, {})
    profile_label = profile.get("label", "🔧 Personnalisé") if profile_key != "custom" else "🔧 Personnalisé"

    scoring_on = bool(getattr(us, "signal_scoring_enabled", True))
    min_score  = float(getattr(us, "min_signal_score", 40))
    smart_on   = bool(getattr(us, "smart_filter_enabled", True))
    skip_cf    = bool(getattr(us, "skip_coin_flip", True))
    conv_min   = float(getattr(us, "min_conviction_pct", 2.0))
    drift_max  = float(getattr(us, "max_price_drift_pct", 5.0))
    wr_min     = float(getattr(us, "min_trader_winrate_for_type", 55.0))

    criteria = _get_criteria_config(us)

    total_signals = passed_signals = 0
    avg_score = 0.0
    try:
        async with async_session() as s:
            total_signals  = (await s.scalar(select(func.count(SignalScore.id)))) or 0
            passed_signals = (await s.scalar(
                select(func.count(SignalScore.id)).where(SignalScore.passed == True)  # noqa
            )) or 0
            avg_val        = await s.scalar(select(func.avg(SignalScore.total_score)))
            avg_score      = float(avg_val or 0)
    except Exception:
        pass

    pass_rate  = round(passed_signals / total_signals * 100) if total_signals else 0
    block_rate = 100 - pass_rate
    on = "✅"; off = "❌"

    lines = [f"📊 *SIGNAUX & SCORING*\n{SEP}\n"]

    if not scoring_on:
        lines += [
            f"*Profil :* {profile_label}",
            f"🎲 _Scoring désactivé — tous les trades sont copiés_\n",
        ]
    else:
        score_bar = bar(min_score, 100, 12)
        lines += [
            f"*Profil :* {profile_label}",
            f"*Seuil de score :* *{min_score:.0f}/100* — un signal en dessous est bloqué",
            f"{score_bar}\n",
        ]

        if avg_score > 0:
            lines.append(f"*Score moyen reçu :* {avg_score:.0f}/100\n")

        # 6 critères compacts
        total_w = sum(
            cfg.get("w", DEFAULT_CRITERIA_CONFIG[k]["w"])
            for k, cfg in criteria.items()
            if cfg.get("on", True)
        )
        lines.append("*── Scoring (6 critères) ──*\n")
        for key in CRITERIA_ORDER:
            info = CRITERIA_INFO[key]
            cfg  = criteria.get(key, DEFAULT_CRITERIA_CONFIG[key])
            is_on  = cfg.get("on", True)
            raw_w  = cfg.get("w", info["default_w"])
            eff_w  = round(raw_w / total_w * 100) if (is_on and total_w > 0) else 0
            state  = on if is_on else off
            poids  = f"*{eff_w}%* du score" if is_on else "désactivé"
            lines.append(f"{state} {info['label']} — {poids}")

        # Smart Filter
        sf_count = sum([smart_on, skip_cf, conv_min > 0, drift_max > 0, wr_min > 0])
        lines += [
            f"\n*── Smart Filter ({sf_count} filtres actifs) ──*\n",
            f"{on if smart_on else off} Smart Filter global",
            f"  {on if skip_cf else off} Skip coin-flip (YES entre $0.45–$0.55)",
            f"  💪 Conviction ≥ *{conv_min:.0f}%* du portfolio master",
            f"  📏 Drift prix ≤ *{drift_max:.0f}%* depuis entrée master",
            f"  📊 WR min ≥ *{wr_min:.0f}%* par catégorie de marché\n",
        ]

    if total_signals > 0:
        lines += [
            f"*── Historique ──*\n",
            f"{bar(pass_rate, 100, 10)} *{pass_rate}%* acceptés / *{block_rate}%* bloqués",
            f"_{total_signals} signaux analysés_",
        ]

    keyboard = [
        [InlineKeyboardButton("📋 Changer de profil", callback_data="sig_profile_menu")],
        [InlineKeyboardButton("📐 Critères de scoring — 6 variables", callback_data="sig_criteria_menu")],
        [InlineKeyboardButton("🔍 Smart Filter — 5 variables", callback_data="sig_smartfilter_menu")],
        [
            InlineKeyboardButton(
                f"{'❌ Réactiver' if not scoring_on else f'🎯 Seuil : {min_score:.0f}/100'}",
                callback_data="set_signal_scoring_enabled" if not scoring_on else "sig_score_min_picker",
            ),
        ],
    ]

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# SÉLECTEUR DE PROFIL
# ═══════════════════════════════════════════════════════════════

async def show_profile_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        current = detect_active_profile(us)

    lines = [
        f"📋 *CHOISIR UN PROFIL*\n{SEP}\n",
        "_Le profil configure automatiquement le seuil de score,_",
        "_les poids des critères et le smart filter.\n_",
        "_Pour tout contrôler manuellement → 🔧 Personnalisé_\n",
    ]
    for key, p in PROFILES.items():
        tick = "▶️ " if key == current else "     "
        lines += [f"{tick}*{p['label']}*", f"_{p['description'].replace(chr(10), ' ')}_\n"]

    lines += [
        "▶️ " if current == "custom" else "     ",
        "*🔧 Personnalisé*",
        "_Configurez chaque critère et filtre manuellement._",
    ]

    keyboard = [
        [InlineKeyboardButton(f"{'▶ ' if current == k else ''}{v['label']}", callback_data=f"sig_set_profile:{k}")]
        for k, v in PROFILES.items()
    ] + [
        [InlineKeyboardButton("🔧 Personnaliser manuellement", callback_data="sig_criteria_menu")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="sig_back")],
    ]

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def apply_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    profile_key = (query.data or "").replace("sig_set_profile:", "")
    await query.answer()

    profile = PROFILES.get(profile_key)
    if not profile:
        await query.answer("❌ Profil inconnu", show_alert=True)
        return

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        us.min_signal_score       = profile["min_signal_score"]
        us.signal_scoring_enabled = profile["signal_scoring_enabled"]
        us.smart_filter_enabled   = profile["smart_filter_enabled"]
        us.skip_coin_flip         = profile["skip_coin_flip"]
        us.min_conviction_pct     = profile["min_conviction_pct"]
        us.scoring_criteria       = profile["scoring_criteria"]
        await session.commit()

    await query.answer(f"✅ Profil {profile['label']} appliqué")
    # Retour au menu signals
    query.data = "sig_back"
    await sig_back(update, context)


# ═══════════════════════════════════════════════════════════════
# LISTE DES CRITÈRES DE SCORING
# ═══════════════════════════════════════════════════════════════

async def show_criteria_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria   = _get_criteria_config(us)
        scoring_on = bool(getattr(us, "signal_scoring_enabled", True))
        min_score  = float(getattr(us, "min_signal_score", 40))

    total_w = sum(
        cfg.get("w", DEFAULT_CRITERIA_CONFIG[k]["w"])
        for k, cfg in criteria.items()
        if cfg.get("on", True)
    )

    lines = [
        f"📐 *CRITÈRES DE SCORING*\n{SEP}\n",
        f"*Comment ça marche :*\n",
        "_Chaque signal reçoit un score de 0 à 100._",
        "_Ce score est la somme pondérée de 6 critères._",
        "_Si le score total < seuil ({:.0f}/100), le trade est bloqué._\n".format(min_score),
        "_Cliquez sur un critère pour voir la formule exacte,_",
        "_activer/désactiver, ou modifier son poids dans le score._\n",
    ]

    if not scoring_on:
        lines.append("⚠️ _Scoring désactivé — réactivez-le pour que les critères soient pris en compte._\n")

    for key in CRITERIA_ORDER:
        info   = CRITERIA_INFO[key]
        cfg    = criteria.get(key, DEFAULT_CRITERIA_CONFIG[key])
        is_on  = cfg.get("on", True)
        raw_w  = cfg.get("w", info["default_w"])
        eff_w  = round(raw_w / total_w * 100) if (is_on and total_w > 0) else 0
        state  = "✅" if is_on else "❌"
        poids  = f"{eff_w}% du score" if is_on else "désactivé"
        lines += [
            f"{state} *{info['label']}* — {poids}",
            f"   _{info['short']}_",
        ]

    lines += [
        "",
        "_Note : les poids sont redistribués automatiquement entre_",
        "_les critères actifs pour toujours sommer à 100%._",
    ]

    buttons = [
        [InlineKeyboardButton(
            f"{'✅' if criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get('on', True) else '❌'} {CRITERIA_INFO[k]['label']}",
            callback_data=f"sig_criterion:{k}",
        )]
        for k in CRITERIA_ORDER
    ] + [
        [InlineKeyboardButton("🔍 Smart Filter (5 filtres)", callback_data="sig_smartfilter_menu")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="sig_back")],
    ]

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
    )


# ═══════════════════════════════════════════════════════════════
# FICHE DÉTAILLÉE D'UN CRITÈRE
# ═══════════════════════════════════════════════════════════════

async def show_criterion_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    crit_key = (query.data or "").replace("sig_criterion:", "")
    await query.answer()

    info = CRITERIA_INFO.get(crit_key)
    if not info:
        return

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_criteria_config(us)

    cfg    = criteria.get(crit_key, DEFAULT_CRITERIA_CONFIG[crit_key])
    is_on  = cfg.get("on", True)
    weight = cfg.get("w", info["default_w"])

    total_w = sum(
        criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("w", DEFAULT_CRITERIA_CONFIG[k]["w"])
        for k in CRITERIA_ORDER
        if criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("on", True)
    )
    eff_w = round(weight / total_w * 100) if (is_on and total_w > 0) else 0

    # Texte : fiche complète + état actuel
    text = info["what"]
    text += f"\n\n*── Réglages actuels ──*\n"
    text += f"Statut : {'✅ Actif' if is_on else '❌ Désactivé'}\n"
    if is_on:
        w_bar = bar(weight, 40, 10)
        text += f"Poids brut : *{weight}%* (sur 100% répartis)\n"
        text += f"Poids effectif : *{eff_w}%* du score total\n"
        text += f"{w_bar}"
    else:
        text += "_Ce critère ne contribue pas au score._"

    # Bouton toggle
    toggle_label = (
        f"❌ Désactiver" if is_on else f"✅ Activer"
    )

    # Boutons poids (si actif)
    weight_buttons = []
    if is_on:
        opts = info["weight_options"]
        row = []
        for i, w in enumerate(opts):
            mark = "●" if w == weight else ""
            row.append(InlineKeyboardButton(
                f"{mark}{w}%{mark}" if mark else f"{w}%",
                callback_data=f"sig_weight:{crit_key}:{w}",
            ))
            if len(row) == 3 or i == len(opts) - 1:
                weight_buttons.append(row)
                row = []

    keyboard = [
        [InlineKeyboardButton(toggle_label, callback_data=f"sig_toggle_crit:{crit_key}")],
        *weight_buttons,
        [InlineKeyboardButton("⬅️ Retour critères", callback_data="sig_criteria_menu")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# TOGGLE UN CRITÈRE
# ═══════════════════════════════════════════════════════════════

async def toggle_criterion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    crit_key = (query.data or "").replace("sig_toggle_crit:", "")

    if crit_key not in CRITERIA_INFO:
        await query.answer("❌ Critère inconnu", show_alert=True)
        return

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_criteria_config(us)

        cfg    = dict(criteria.get(crit_key, DEFAULT_CRITERIA_CONFIG[crit_key]))
        new_on = not cfg.get("on", True)

        if not new_on:
            active = sum(
                1 for k in CRITERIA_ORDER
                if k != crit_key and criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("on", True)
            )
            if active == 0:
                await query.answer("⚠️ Gardez au moins 1 critère actif", show_alert=True)
                return

        cfg["on"] = new_on
        criteria[crit_key] = cfg
        us.scoring_criteria = dict(criteria)
        await session.commit()

    await query.answer("✅ Activé" if new_on else "❌ Désactivé")
    query.data = f"sig_criterion:{crit_key}"
    await show_criterion_detail(update, context)


# ═══════════════════════════════════════════════════════════════
# CHANGER LE POIDS D'UN CRITÈRE
# ═══════════════════════════════════════════════════════════════

async def set_criterion_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        return
    _, crit_key, raw_val = parts

    try:
        new_w = int(raw_val)
    except ValueError:
        return

    if crit_key not in CRITERIA_INFO:
        return

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_criteria_config(us)
        cfg = dict(criteria.get(crit_key, DEFAULT_CRITERIA_CONFIG[crit_key]))
        cfg["w"] = new_w
        criteria[crit_key] = cfg
        us.scoring_criteria = dict(criteria)
        await session.commit()

    await query.answer(f"✅ Poids → {new_w}%")
    query.data = f"sig_criterion:{crit_key}"
    await show_criterion_detail(update, context)


# ═══════════════════════════════════════════════════════════════
# SMART FILTER — MENU PRINCIPAL
# ═══════════════════════════════════════════════════════════════

async def show_smartfilter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        smart_on   = bool(getattr(us, "smart_filter_enabled", True))
        skip_cf    = bool(getattr(us, "skip_coin_flip", True))
        conv_min   = float(getattr(us, "min_conviction_pct", 2.0))
        drift_max  = float(getattr(us, "max_price_drift_pct", 5.0))
        wr_min     = float(getattr(us, "min_trader_winrate_for_type", 55.0))
        trades_min = int(getattr(us, "min_trader_trades_for_type", 10))

    on = "✅"; off = "❌"

    lines = [
        f"🔍 *SMART FILTER*\n{SEP}\n",
        f"*{on if smart_on else off} Smart Filter global*\n",
        "_Ces filtres s'appliquent AVANT le scoring._",
        "_Un signal bloqué ici n'est jamais soumis au score._\n",
        "_Cliquez sur un filtre pour voir sa définition exacte._\n",

        f"*1.* 🪙 *Skip Coin-Flip :* {on if skip_cf else off}",
        f"   _Bloque si prix YES entre $0.45 et $0.55 (≈ 50/50)_\n",

        f"*2.* 💪 *Conviction min :* *{conv_min:.0f}%* du portfolio master",
        f"   _Bloque si trade < {conv_min:.0f}% du portefeuille total du trader_\n",

        f"*3.* 📏 *Drift prix max :* *{drift_max:.0f}%* depuis entrée master",
        f"   _Bloque si le prix a bougé de + de {drift_max:.0f}% depuis l'achat du master_\n",

        f"*4.* 📊 *WR min par catégorie :* *{wr_min:.0f}%*",
        f"   _Bloque si le master a < {wr_min:.0f}% WR sur ce type de marché_\n",

        f"*5.* 🔢 *Trades min pour activer (4) :* *{trades_min}*",
        f"   _Le filtre WR catégorie n'est actif qu'avec ≥ {trades_min} trades d'historique_",
    ]

    keyboard = [
        [InlineKeyboardButton(
            f"{on if smart_on else off} Smart Filter global",
            callback_data="set_smart_filter_enabled",
        )],
        [InlineKeyboardButton("🪙 1. Skip Coin-Flip — définition", callback_data="sig_sf_detail:coin_flip")],
        [InlineKeyboardButton("💪 2. Conviction — définition", callback_data="sig_sf_detail:conviction")],
        [InlineKeyboardButton("📏 3. Drift prix — définition", callback_data="sig_sf_detail:drift")],
        [InlineKeyboardButton("📊 4. WR par catégorie — définition", callback_data="sig_sf_detail:trader_edge")],
        [InlineKeyboardButton("🔢 5. Trades minimum — définition", callback_data="sig_sf_detail:min_trades")],
        [
            InlineKeyboardButton(f"{on if skip_cf else off} Coin-Flip", callback_data="set_skip_coin_flip"),
            InlineKeyboardButton(f"💪 Conv. ≥ {conv_min:.0f}%", callback_data="set_min_conviction_pct"),
            InlineKeyboardButton(f"📏 Drift ≤ {drift_max:.0f}%", callback_data="set_max_price_drift_pct"),
        ],
        [InlineKeyboardButton("⬅️ Retour", callback_data="sig_back")],
    ]

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# FICHE DÉTAILLÉE D'UN FILTRE SMART FILTER
# ═══════════════════════════════════════════════════════════════

async def show_sf_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    filter_key = (query.data or "").replace("sig_sf_detail:", "")
    await query.answer()

    info = SMART_FILTER_INFO.get(filter_key)
    if not info:
        return

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        current_val = getattr(us, info["setting"], None)

    text = info["detail"]
    if current_val is not None:
        text += f"\n\n*Valeur actuelle :* `{current_val}`"

    # Bouton pour modifier via preset picker si c'est un nombre
    setting_cb = info["setting"]
    keyboard = [
        [InlineKeyboardButton(f"✏️ Modifier ce paramètre", callback_data=f"set_{setting_cb}")],
        [InlineKeyboardButton("⬅️ Retour Smart Filter", callback_data="sig_smartfilter_menu")],
    ]

    # Pour les toggles, bouton direct
    if isinstance(current_val, bool):
        keyboard[0] = [InlineKeyboardButton(
            f"{'❌ Désactiver' if current_val else '✅ Activer'}",
            callback_data=f"set_{setting_cb}",
        )]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# PICKER DU SEUIL DE SCORE MINIMUM
# ═══════════════════════════════════════════════════════════════

async def show_score_min_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        current = float(getattr(us, "min_signal_score", 40))

    presets = [10, 20, 25, 30, 40, 50, 60, 65, 70, 80, 90]
    rows = []
    row = []
    for i, p in enumerate(presets):
        mark = "●" if p == int(current) else ""
        row.append(InlineKeyboardButton(
            f"{mark}{p}{mark}" if mark else str(p),
            callback_data=f"grp_set:min_signal_score:{p}",
        ))
        if len(row) == 4 or i == len(presets) - 1:
            rows.append(row)
            row = []

    rows.append([InlineKeyboardButton("⬅️ Retour", callback_data="sig_back")])

    score_bar = bar(current, 100, 14)
    await query.edit_message_text(
        f"🎯 *SEUIL DE SCORE MINIMUM*\n{SEP}\n\n"
        f"Valeur actuelle : *{current:.0f}/100*\n"
        f"{score_bar}\n\n"
        f"Un signal avec un score *inférieur* à ce seuil est bloqué automatiquement.\n\n"
        f"*Repères :*\n"
        f"🛡️ Prudent ≥ *65* — peu de trades, haute qualité\n"
        f"⚖️ Équilibré ≥ *40* — recommandé\n"
        f"⚡ Agressif ≥ *20* — beaucoup de trades\n"
        f"🎲 Tout passe = *0* (scoring désactivé)\n\n"
        f"Choisissez un seuil :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════════════════════════════════════════════
# RETOUR AU MENU SIGNALS
# ═══════════════════════════════════════════════════════════════

async def sig_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
    tg_id = update.effective_user.id
    try:
        async with async_session() as session:
            user = await get_user_by_telegram_id(session, tg_id)
            if not user:
                return
            us = await get_or_create_settings(session, user)
            await show_signals_menu(update, user, us)
    except Exception as e:
        logger.warning("sig_back error: %s", e)


# ═══════════════════════════════════════════════════════════════
# ENREGISTREMENT
# ═══════════════════════════════════════════════════════════════

def get_signals_handlers() -> list:
    return [
        CallbackQueryHandler(show_profile_picker,   pattern=r"^sig_profile_menu$"),
        CallbackQueryHandler(apply_profile,         pattern=r"^sig_set_profile:"),
        CallbackQueryHandler(show_criteria_list,    pattern=r"^sig_criteria_menu$"),
        CallbackQueryHandler(show_criterion_detail, pattern=r"^sig_criterion:"),
        CallbackQueryHandler(toggle_criterion,      pattern=r"^sig_toggle_crit:"),
        CallbackQueryHandler(set_criterion_weight,  pattern=r"^sig_weight:"),
        CallbackQueryHandler(show_smartfilter_menu, pattern=r"^sig_smartfilter_menu$"),
        CallbackQueryHandler(show_sf_detail,        pattern=r"^sig_sf_detail:"),
        CallbackQueryHandler(show_score_min_picker, pattern=r"^sig_score_min_picker$"),
        CallbackQueryHandler(sig_back,              pattern=r"^sig_back$"),
    ]
