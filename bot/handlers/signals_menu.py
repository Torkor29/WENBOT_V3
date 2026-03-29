"""Signals topic menu — V3 Multi-tenant.

Menu complet du topic 📊 Signals :
  • Profil actif (Prudent / Équilibré / Agressif / Tout passe / Personnalisé)
  • 6 critères de scoring avec état, poids, explication, barème détaillé
  • Smart Filter : filtres additionnels (conviction, coin-flip, drift…)
  • Stats : signaux reçus, taux d'acceptation, score moyen

Callbacks gérés (pattern "^sig_"):
  sig_profile_menu            → liste des profils
  sig_set_profile:{key}       → appliquer un profil preset
  sig_criteria_menu           → liste des 6 critères
  sig_criterion:{name}        → fiche détaillée d'un critère
  sig_toggle_crit:{name}      → activer / désactiver un critère
  sig_weight:{name}:{value}   → changer le poids d'un critère
  sig_smartfilter_menu        → panneau Smart Filter
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
        "min_signal_score":      65,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":  True,
        "skip_coin_flip":        True,
        "min_conviction_pct":    3.0,
        "scoring_criteria": {
            "spread":      {"on": True,  "w": 20},
            "liquidity":   {"on": True,  "w": 25},
            "conviction":  {"on": True,  "w": 20},
            "trader_form": {"on": True,  "w": 25},
            "timing":      {"on": True,  "w": 5},
            "consensus":   {"on": True,  "w": 5},
        },
    },
    "balanced": {
        "label":       "⚖️ Équilibré",
        "description": (
            "Configuration recommandée. Tous les critères actifs\n"
            "avec les poids par défaut. Bon équilibre volume/qualité."
        ),
        "min_signal_score":      40,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":  True,
        "skip_coin_flip":        True,
        "min_conviction_pct":    2.0,
        "scoring_criteria":      None,   # poids par défaut
    },
    "aggressive": {
        "label":       "⚡ Agressif",
        "description": (
            "Seuil bas, spread et timing ignorés.\n"
            "Focus conviction + forme trader. Plus de trades,\n"
            "plus de risque. Déconseillé en démarrage."
        ),
        "min_signal_score":      20,
        "signal_scoring_enabled": True,
        "smart_filter_enabled":  False,
        "skip_coin_flip":        False,
        "min_conviction_pct":    1.0,
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
            "⚠️ Scoring désactivé — TOUS les signaux sont copiés\n"
            "sans filtre. Recommandé uniquement en paper trading\n"
            "pour observer le comportement brut des traders."
        ),
        "min_signal_score":      0,
        "signal_scoring_enabled": False,
        "smart_filter_enabled":  False,
        "skip_coin_flip":        False,
        "min_conviction_pct":    0.0,
        "scoring_criteria":      None,
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


# ═══════════════════════════════════════════════════════════════
# FICHES DES 6 CRITÈRES — description complète + barème
# ═══════════════════════════════════════════════════════════════

CRITERIA_INFO: dict[str, dict] = {
    "spread": {
        "label":  "📏 Spread bid-ask",
        "short":  "Écart entre prix achat et vente",
        "what": (
            "*C'est quoi ?*\n"
            "L'écart entre le meilleur prix d'achat (bid) et le meilleur prix de vente (ask) "
            "dans le carnet d'ordres au moment du signal.\n\n"
            "*Pourquoi c'est important ?*\n"
            "Un spread élevé signifie que tu perds immédiatement de l'argent à l'entrée. "
            "Sur un marché à 0.50¢ avec un spread de 5%, tu as déjà -5% avant même que "
            "le marché bouge. Un spread faible = marché liquide = meilleur prix d'exécution."
        ),
        "scale": (
            "🟢 *< 1%* → 100 pts — excellent, très liquide\n"
            "🟡 *1 - 2%* → 80 pts — bon, acceptable\n"
            "🟠 *2 - 3%* → 60 pts — correct mais attention\n"
            "🔴 *3 - 5%* → 30 pts — méfiance, marché peu liquide\n"
            "⛔ *> 5%* → 0 pts — éviter, coût d'entrée trop élevé"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },
    "liquidity": {
        "label":  "💧 Liquidité",
        "short":  "Volume de transactions sur 24h",
        "what": (
            "*C'est quoi ?*\n"
            "Le volume total de USDC échangés sur ce marché durant les dernières 24h.\n\n"
            "*Pourquoi c'est important ?*\n"
            "Un marché peu liquide est difficile à sortir rapidement. Si tu veux vendre "
            "et qu'il n'y a personne en face, tu es bloqué ou tu vends à un mauvais prix. "
            "Un volume élevé garantit que tu peux entrer ET sortir facilement."
        ),
        "scale": (
            "🟢 *≥ $500K* → 100 pts — très liquide, marché actif\n"
            "🟡 *≥ $100K* → 80 pts — bon volume\n"
            "🟠 *≥ $50K* → 60 pts — acceptable\n"
            "🔴 *≥ $10K* → 40 pts — faible, risque de slippage\n"
            "⛔ *< $10K* → 10 pts — éviter, très peu liquide"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },
    "conviction": {
        "label":  "💪 Conviction du trader",
        "short":  "Taille du trade vs portfolio du master",
        "what": (
            "*C'est quoi ?*\n"
            "Le pourcentage que représente ce trade dans le portfolio total du trader qu'on copie.\n\n"
            "*Pourquoi c'est important ?*\n"
            "Si un trader met 15% de tout son argent sur un trade, c'est qu'il y croit vraiment. "
            "Si il mise 0.1%, c'est peut-être un test ou une position anecdotique. "
            "On veut copier les trades que le master prend au sérieux, pas ses paris à 1€."
        ),
        "scale": (
            "🟢 *≥ 10%* → 100 pts — très haute conviction\n"
            "🟡 *≥ 5%* → 80 pts — bonne conviction\n"
            "🟠 *≥ 2%* → 60 pts — conviction modérée\n"
            "⛔ *< 2%* → 20 pts — signal faible, trade anecdotique"
        ),
        "default_w": 20,
        "weight_options": [10, 15, 20, 25, 30, 35, 40],
    },
    "trader_form": {
        "label":  "📈 Forme du trader",
        "short":  "Win rate sur les 7 derniers jours",
        "what": (
            "*C'est quoi ?*\n"
            "Le pourcentage de trades gagnants du master sur les 7 derniers jours, "
            "ainsi que sa série en cours (victoires/défaites consécutives).\n\n"
            "*Pourquoi c'est important ?*\n"
            "Un trader à 70% sur la semaine est en pleine forme. Un trader à 30% traverse "
            "une mauvaise passe — même s'il est globalement bon, ce n'est pas le moment de "
            "le copier. Ce critère capture la dynamique récente, pas la performance historique."
        ),
        "scale": (
            "🟢 *≥ 70%* → 100 pts — trader en feu 🔥\n"
            "🟡 *≥ 60%* → 80 pts — bonne forme\n"
            "🟠 *≥ 50%* → 60 pts — correct\n"
            "🔴 *≥ 40%* → 30 pts — forme médiocre, méfiance\n"
            "⛔ *< 40%* → 0 pts — trader en mauvaise passe"
        ),
        "default_w": 20,
        "weight_options": [10, 15, 20, 25, 30, 35, 40],
    },
    "timing": {
        "label":  "⏱️ Timing",
        "short":  "Temps restant avant expiration du marché",
        "what": (
            "*C'est quoi ?*\n"
            "Le nombre d'heures/jours restants avant que le marché se règle (YES ou NO).\n\n"
            "*Pourquoi c'est important ?*\n"
            "Trop court (< 30min) : le résultat est quasi certain, les cotes ne bougent plus "
            "et le risque d'exécution est élevé. Trop long (> 3 mois) : ton capital est "
            "immobilisé longtemps. La zone idéale est 2h-48h : assez de temps pour que le "
            "trade évolue favorablement, pas assez pour bloquer le capital inutilement."
        ),
        "scale": (
            "⛔ *Expiré* → 0 pts — trop tard\n"
            "🔴 *< 30 min* → 20 pts — trop risqué, résultat quasi certain\n"
            "🟠 *30 min - 2h* → 50 pts — court, acceptable\n"
            "🟢 *2h - 48h* → 100 pts — zone idéale ✓\n"
            "🟡 *2 - 7 jours* → 80 pts — bon, moyen terme\n"
            "🟠 *7 - 30 jours* → 60 pts — long terme, OK\n"
            "🔴 *30 - 90 jours* → 40 pts — capital bloqué longtemps\n"
            "⛔ *> 90 jours* → 20 pts — trop lointain"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25],
    },
    "consensus": {
        "label":  "👥 Consensus",
        "short":  "Combien de tes traders ont la même position",
        "what": (
            "*C'est quoi ?*\n"
            "Le nombre de traders que tu suis qui ont déjà une position ouverte "
            "sur ce même marché, dans le même sens.\n\n"
            "*Pourquoi c'est important ?*\n"
            "Si 3 traders indépendants misent tous sur YES pour le même événement, "
            "c'est un signal bien plus fort qu'un seul trader isolé. Le consensus réduit "
            "le risque d'erreur individuelle et indique une thèse partagée par plusieurs esprits."
        ),
        "scale": (
            "🟢 *3 traders ou +* → 100 pts — fort consensus\n"
            "🟡 *2 traders* → 70 pts — bon signal\n"
            "🟠 *1 trader* → 40 pts — signal isolé\n"
            "🔴 *0 autre trader* → 20 pts — aucun consensus"
        ),
        "default_w": 15,
        "weight_options": [5, 10, 15, 20, 25, 30],
    },
}

CRITERIA_ORDER = ["spread", "liquidity", "conviction", "trader_form", "timing", "consensus"]


# ═══════════════════════════════════════════════════════════════
# DÉTECTION DU PROFIL ACTIF
# ═══════════════════════════════════════════════════════════════

def detect_active_profile(us) -> str:
    """Détermine quel profil correspond aux réglages actuels."""
    if not getattr(us, "signal_scoring_enabled", True):
        return "all_pass"

    min_score = float(getattr(us, "min_signal_score", 40))
    smart     = bool(getattr(us, "smart_filter_enabled", True))
    criteria  = getattr(us, "scoring_criteria", None)

    # Tout passe
    if not getattr(us, "signal_scoring_enabled", True):
        return "all_pass"

    # Prudent : seuil ≥ 65
    if min_score >= 65:
        return "prudent"

    # Agressif : smart filter off + seuil bas
    if not smart and min_score <= 25:
        return "aggressive"

    # Équilibré : pas de critères custom + smart on
    if criteria is None and smart and 35 <= min_score <= 55:
        return "balanced"

    return "custom"


def _get_criteria_config(us) -> dict:
    """Retourne la config critères de l'user, avec fallback sur les défauts."""
    raw = getattr(us, "scoring_criteria", None)
    if not raw:
        return dict(DEFAULT_CRITERIA_CONFIG)
    # Merge avec défauts pour les critères manquants
    merged = dict(DEFAULT_CRITERIA_CONFIG)
    merged.update(raw)
    return merged


# ═══════════════════════════════════════════════════════════════
# MENU PRINCIPAL SIGNALS
# ═══════════════════════════════════════════════════════════════

async def show_signals_menu(update: Update, user, us) -> None:
    """Affiche le menu principal du topic 📊 Signals."""
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

    criteria = _get_criteria_config(us)

    # Récupère les stats signaux
    total_signals  = 0
    passed_signals = 0
    avg_score      = 0.0
    try:
        async with async_session() as s:
            total_signals = (await s.scalar(
                select(func.count(SignalScore.id))
            )) or 0
            passed_signals = (await s.scalar(
                select(func.count(SignalScore.id)).where(SignalScore.passed == True)  # noqa
            )) or 0
            avg_val = await s.scalar(select(func.avg(SignalScore.total_score)))
            avg_score = float(avg_val or 0)
    except Exception:
        pass

    pass_rate  = round(passed_signals / total_signals * 100, 0) if total_signals else 0
    block_rate = 100 - pass_rate

    # ── Texte ──────────────────────────────────────────────────
    on  = "✅"
    off = "❌"

    lines = [f"📊 *SIGNAUX & SCORING*\n{SEP}\n"]

    if not scoring_on:
        lines += [
            f"*Profil actif :* {profile_label}",
            f"🎲 _Scoring désactivé — tous les trades sont copiés_\n",
        ]
    else:
        score_bar = bar(min_score, 100, 12)
        lines += [
            f"*Profil actif :* {profile_label}",
            f"*Seuil minimum :* *{min_score:.0f}/100*",
            f"{score_bar} ← seuil\n",
            f"*Score moyen reçu :* {avg_score:.0f}/100\n",
            f"*── Critères actifs ──*\n",
        ]

        # Liste compacte des 6 critères
        for key in CRITERIA_ORDER:
            info = CRITERIA_INFO[key]
            cfg  = criteria.get(key, DEFAULT_CRITERIA_CONFIG[key])
            is_on = cfg.get("on", True)
            weight = cfg.get("w", info["default_w"])
            state = on if is_on else off
            # Redistribution: si désactivé poids = 0
            effective = f"{weight}%" if is_on else "désactivé"
            lines.append(f"{state} *{info['label']}* — {effective} du score")

        lines.append("")

        # Smart filter
        lines += [
            f"*── Smart Filter ──*\n",
            f"{on if smart_on else off} Smart Filter global",
            f"  {on if skip_cf else off} Ignorer les coin-flips (≈ 50/50)",
            f"  💪 Conviction min : *{conv_min:.0f}%* du portfolio\n",
        ]

    # Stats
    if total_signals > 0:
        accept_bar = bar(pass_rate, 100, 10)
        lines += [
            f"*── Historique ──*\n",
            f"{accept_bar} *{pass_rate:.0f}%* acceptés / *{block_rate:.0f}%* bloqués",
            f"_{total_signals} signaux analysés_\n",
        ]

    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton("📋 Changer de profil", callback_data="sig_profile_menu")],
        [InlineKeyboardButton("🎯 Configurer les critères", callback_data="sig_criteria_menu")],
        [
            InlineKeyboardButton(
                f"🔍 Smart Filter : {on if smart_on else off}",
                callback_data="sig_smartfilter_menu",
            ),
            InlineKeyboardButton(
                f"📊 Score min : {min_score:.0f}",
                callback_data="set_min_signal_score",
            ),
        ],
    ]

    if not scoring_on:
        keyboard.insert(0, [InlineKeyboardButton(
            "✅ Réactiver le scoring", callback_data="set_signal_scoring_enabled"
        )])

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
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
    ]

    for key, p in PROFILES.items():
        tick = "▶️ " if key == current else "   "
        lines += [
            f"{tick}*{p['label']}*",
            f"_{p['description'].replace(chr(10), ' ')}_\n",
        ]

    lines += [
        "   *🔧 Personnalisé*",
        "_Configurez chaque critère manuellement via 'Configurer les critères'._",
    ]

    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton(f"{'▶ ' if current == 'prudent'    else ''}{PROFILES['prudent']['label']}",    callback_data="sig_set_profile:prudent")],
        [InlineKeyboardButton(f"{'▶ ' if current == 'balanced'   else ''}{PROFILES['balanced']['label']}",   callback_data="sig_set_profile:balanced")],
        [InlineKeyboardButton(f"{'▶ ' if current == 'aggressive' else ''}{PROFILES['aggressive']['label']}", callback_data="sig_set_profile:aggressive")],
        [InlineKeyboardButton(f"{'▶ ' if current == 'all_pass'   else ''}{PROFILES['all_pass']['label']}",   callback_data="sig_set_profile:all_pass")],
        [InlineKeyboardButton("🔧 Personnaliser les critères", callback_data="sig_criteria_menu")],
        [InlineKeyboardButton("⬅️ Retour Signals", callback_data="sig_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
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
        await session.refresh(us)
        # Re-display signals menu
        await _edit_to_signals_menu(query, user, us)


# ═══════════════════════════════════════════════════════════════
# LISTE DES CRITÈRES
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
        criteria = _get_criteria_config(us)
        scoring_on = bool(getattr(us, "signal_scoring_enabled", True))

    lines = [
        f"🎯 *CRITÈRES DE SCORING*\n{SEP}\n",
        "_Cliquez sur un critère pour voir sa description complète,_",
        "_activer/désactiver, ou modifier son poids._\n",
    ]

    if not scoring_on:
        lines.append("⚠️ _Le scoring est désactivé — activez-le d'abord._\n")

    # Calcule les poids effectifs normalisés
    active_weights = {}
    total_w = sum(
        cfg.get("w", DEFAULT_CRITERIA_CONFIG[k]["w"])
        for k, cfg in criteria.items()
        if cfg.get("on", True)
    )
    for key in CRITERIA_ORDER:
        cfg = criteria.get(key, DEFAULT_CRITERIA_CONFIG[key])
        is_on  = cfg.get("on", True)
        raw_w  = cfg.get("w", CRITERIA_INFO[key]["default_w"])
        effective_w = round(raw_w / total_w * 100) if (is_on and total_w > 0) else 0
        active_weights[key] = (is_on, raw_w, effective_w)

    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        is_on, raw_w, eff_w = active_weights[key]
        state = "✅" if is_on else "❌"
        weight_str = f"*{eff_w}%* effectif" if is_on else "désactivé"
        lines.append(f"{state} *{info['label']}* — {weight_str}")
        lines.append(f"   _{info['short']}_")

    text = "\n".join(lines)

    buttons = []
    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        is_on, _, _ = active_weights[key]
        state = "✅" if is_on else "❌"
        buttons.append([
            InlineKeyboardButton(
                f"{state} {info['label']}",
                callback_data=f"sig_criterion:{key}",
            )
        ])

    buttons.append([InlineKeyboardButton("⬅️ Retour Signals", callback_data="sig_back")])

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
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

    # Poids effectif
    total_w = sum(
        criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("w", DEFAULT_CRITERIA_CONFIG[k]["w"])
        for k in CRITERIA_ORDER
        if criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("on", True)
    )
    eff_w = round(weight / total_w * 100) if (is_on and total_w > 0) else 0

    on  = "✅"
    off = "❌"

    lines = [
        f"*{info['label']}*\n{SEP}\n",
        info["what"],
        f"\n*── Barème ──*\n",
        info["scale"],
        f"\n*── Réglages actuels ──*\n",
        f"Statut : {on if is_on else off} {'Actif' if is_on else 'Désactivé'}",
    ]

    if is_on:
        w_bar = bar(weight, 40, 10)
        lines += [
            f"Poids brut : *{weight}%*",
            f"Poids effectif : *{eff_w}%* du score total",
            f"{w_bar} (poids parmi critères actifs)",
        ]
    else:
        lines.append("_Ce critère ne contribue pas au score._")

    text = "\n".join(lines)

    # Bouton toggle
    toggle_label = f"❌ Désactiver {info['label'].split(' ', 1)[1]}" if is_on else f"✅ Activer {info['label'].split(' ', 1)[1]}"

    # Boutons de poids (seulement si actif)
    weight_buttons = []
    if is_on:
        weight_row1 = []
        weight_row2 = []
        for i, w in enumerate(info["weight_options"]):
            mark = "●" if w == weight else ""
            btn = InlineKeyboardButton(
                f"{mark}{w}%{mark}" if mark else f"{w}%",
                callback_data=f"sig_weight:{crit_key}:{w}",
            )
            if i < len(info["weight_options"]) // 2:
                weight_row1.append(btn)
            else:
                weight_row2.append(btn)

        if weight_row1:
            weight_buttons.append(weight_row1)
        if weight_row2:
            weight_buttons.append(weight_row2)

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
    await query.answer()

    if crit_key not in CRITERIA_INFO:
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

        # Empêche de désactiver TOUS les critères
        if not new_on:
            active_count = sum(
                1 for k in CRITERIA_ORDER
                if k != crit_key and criteria.get(k, DEFAULT_CRITERIA_CONFIG[k]).get("on", True)
            )
            if active_count == 0:
                await query.answer("⚠️ Gardez au moins 1 critère actif", show_alert=True)
                return

        cfg["on"] = new_on
        criteria[crit_key] = cfg
        us.scoring_criteria = dict(criteria)
        await session.commit()

    await query.answer("✅ Activé" if new_on else "❌ Désactivé")
    # Rafraîchit la fiche du critère
    query.data = f"sig_criterion:{crit_key}"
    await show_criterion_detail(update, context)


# ═══════════════════════════════════════════════════════════════
# CHANGER LE POIDS D'UN CRITÈRE
# ═══════════════════════════════════════════════════════════════

async def set_criterion_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":")  # ["sig_weight", key, value]
    if len(parts) != 3:
        return
    _, crit_key, raw_val = parts
    await query.answer()

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
    # Rafraîchit la fiche
    query.data = f"sig_criterion:{crit_key}"
    await show_criterion_detail(update, context)


# ═══════════════════════════════════════════════════════════════
# SMART FILTER MENU
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
        smart_on  = bool(getattr(us, "smart_filter_enabled", True))
        skip_cf   = bool(getattr(us, "skip_coin_flip", True))
        conv_min  = float(getattr(us, "min_conviction_pct", 2.0))
        drift_max = float(getattr(us, "max_price_drift_pct", 5.0))
        wr_min    = float(getattr(us, "min_trader_winrate_for_type", 55.0))
        trades_min = int(getattr(us, "min_trader_trades_for_type", 10))

    on  = "✅"
    off = "❌"

    lines = [
        f"🔍 *SMART FILTER*\n{SEP}\n",
        f"*Smart Filter global :* {on if smart_on else off}\n",

        f"*── Filtres actifs ──*\n",

        f"{on if skip_cf else off} *Skip coin-flip*",
        f"   _Ignore les marchés où le score est entre 45-55%_",
        f"   _= marchés quasi-aléatoires, pas de edge réel_\n",

        f"{on} *Conviction minimum : {conv_min:.0f}%*",
        f"   _N'accepte que les trades où le master a misé ≥ {conv_min:.0f}%_",
        f"   _de son portfolio — filtre les micro-positions_\n",

        f"{on} *Drift de prix max : {drift_max:.0f}%*",
        f"   _Si le prix a déjà bougé de + de {drift_max:.0f}% depuis l'entrée du master,_",
        f"   _le trade est ignoré (tu achètes trop tard)_\n",

        f"{on} *Win rate min pour type : {wr_min:.0f}%*",
        f"   _Le trader doit avoir ≥ {wr_min:.0f}% WR sur ce type de marché_",
        f"   _(Crypto, Politique, Sports…) sur au moins {trades_min} trades_\n",
    ]

    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton(
            f"🔍 Smart Filter : {on if smart_on else off}",
            callback_data="set_smart_filter_enabled",
        )],
        [InlineKeyboardButton(
            f"🪙 Skip coin-flip : {on if skip_cf else off}",
            callback_data="set_skip_coin_flip",
        )],
        [
            InlineKeyboardButton(
                f"💪 Conviction ≥ {conv_min:.0f}%",
                callback_data="set_min_conviction_pct",
            ),
            InlineKeyboardButton(
                f"📏 Drift ≤ {drift_max:.0f}%",
                callback_data="set_max_price_drift_pct",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📈 WR min {wr_min:.0f}%",
                callback_data="set_min_trader_winrate_for_type",
            ),
            InlineKeyboardButton(
                f"🔢 Trades min {trades_min}",
                callback_data="set_min_trader_trades_for_type",
            ),
        ],
        [InlineKeyboardButton("⬅️ Retour Signals", callback_data="sig_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# RETOUR AU MENU SIGNALS (depuis un sous-menu)
# ═══════════════════════════════════════════════════════════════

async def sig_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retour au menu principal Signals — envoie un nouveau message."""
    query = update.callback_query
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
# HELPER — RE-RENDER DANS LE MESSAGE EXISTANT APRÈS APPLY PROFILE
# ═══════════════════════════════════════════════════════════════

async def _edit_to_signals_menu(query, user, us) -> None:
    """Affiche le menu Signals en éditant le message courant (après apply profile)."""
    from bot.models.signal_score import SignalScore
    from sqlalchemy import select, func

    profile_key   = detect_active_profile(us)
    profile       = PROFILES.get(profile_key, {})
    profile_label = profile.get("label", "🔧 Personnalisé") if profile_key != "custom" else "🔧 Personnalisé"

    scoring_on = bool(getattr(us, "signal_scoring_enabled", True))
    min_score  = float(getattr(us, "min_signal_score", 40))
    smart_on   = bool(getattr(us, "smart_filter_enabled", True))

    on = "✅"; off = "❌"

    lines = [f"📊 *SIGNAUX & SCORING*\n{SEP}\n"]
    if not scoring_on:
        lines += [f"*Profil actif :* {profile_label}", "🎲 _Scoring désactivé_\n"]
    else:
        score_bar = bar(min_score, 100, 12)
        criteria = _get_criteria_config(us)
        lines += [
            f"*Profil actif :* {profile_label}",
            f"*Seuil minimum :* *{min_score:.0f}/100*",
            f"{score_bar} ← seuil\n",
        ]
        for key in CRITERIA_ORDER:
            info = CRITERIA_INFO[key]
            cfg  = criteria.get(key, DEFAULT_CRITERIA_CONFIG[key])
            is_on = cfg.get("on", True)
            weight = cfg.get("w", info["default_w"])
            state = on if is_on else off
            lines.append(f"{state} *{info['label']}* — {'{}%'.format(weight) if is_on else 'désactivé'}")

        lines += ["", f"{on if smart_on else off} Smart Filter"]

    text = "\n".join(lines)
    keyboard = [
        [InlineKeyboardButton("📋 Changer de profil", callback_data="sig_profile_menu")],
        [InlineKeyboardButton("🎯 Configurer les critères", callback_data="sig_criteria_menu")],
        [
            InlineKeyboardButton(f"🔍 Smart Filter : {on if smart_on else off}", callback_data="sig_smartfilter_menu"),
            InlineKeyboardButton(f"📊 Score min : {min_score:.0f}", callback_data="set_min_signal_score"),
        ],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ═══════════════════════════════════════════════════════════════
# AJOUT AU PRESET PICKER — score min (dans group_actions)
# ═══════════════════════════════════════════════════════════════

async def show_score_min_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Picker du score minimum — depuis le bouton 'set_min_signal_score' en groupe."""
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        current = float(getattr(us, "min_signal_score", 40))

    presets = [15, 25, 30, 40, 50, 60, 65, 70, 80]
    rows = []
    row = []
    for p in presets:
        mark = "●" if p == int(current) else ""
        row.append(InlineKeyboardButton(
            f"{mark}{p}{mark}" if mark else str(p),
            callback_data=f"grp_set:min_signal_score:{p}",
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton("⬅️ Retour Signals", callback_data="sig_back")])

    score_bar = bar(current, 100, 12)
    await query.edit_message_text(
        f"🎯 *Score minimum du signal*\n{SEP}\n\n"
        f"Valeur actuelle : *{current:.0f}/100*\n"
        f"{score_bar}\n\n"
        f"_Chaque signal doit dépasser ce seuil pour être copié._\n"
        f"_🛡️ Prudent ≥ 65 | ⚖️ Équilibré ≥ 40 | ⚡ Agressif ≥ 20_\n\n"
        f"Choisissez un seuil :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════════════════════════════════════════════
# ENREGISTREMENT
# ═══════════════════════════════════════════════════════════════

def get_signals_handlers() -> list:
    """Handlers pour les callbacks sig_* — groupe ET DM."""
    return [
        CallbackQueryHandler(show_profile_picker,    pattern=r"^sig_profile_menu$"),
        CallbackQueryHandler(apply_profile,          pattern=r"^sig_set_profile:"),
        CallbackQueryHandler(show_criteria_list,     pattern=r"^sig_criteria_menu$"),
        CallbackQueryHandler(show_criterion_detail,  pattern=r"^sig_criterion:"),
        CallbackQueryHandler(toggle_criterion,       pattern=r"^sig_toggle_crit:"),
        CallbackQueryHandler(set_criterion_weight,   pattern=r"^sig_weight:"),
        CallbackQueryHandler(show_smartfilter_menu,  pattern=r"^sig_smartfilter_menu$"),
        CallbackQueryHandler(show_score_min_picker,  pattern=r"^sig_score_min_picker$"),
        CallbackQueryHandler(sig_back,               pattern=r"^sig_back$"),
    ]
