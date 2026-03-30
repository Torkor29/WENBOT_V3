"""Menus contextuels par topic — V3 Multi-tenant.

Quand un utilisateur tape /menu depuis un topic de son groupe,
ce module détecte le topic et affiche un écran adapté à son contexte.

Topics :
  📊 signals  — scoring, filtres, signaux reçus
  👤 traders  — traders suivis, stats, pause
  💼 portfolio — positions, PNL, exposition
  🚨 alerts   — SL/TP/trailing, alertes actives
  ⚙️ admin    — statut bot, wallet, paramètres
"""

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.db.session import async_session
from bot.models.group_config import GroupConfig
from bot.models.user import User
from bot.services.user_service import get_user_by_telegram_id, get_or_create_settings
from bot.utils.formatting import (
    bar, bar_bicolor, fmt_usd, fmt_pnl, badge_trader_status,
    badge_score, short_wallet as sw, SEP, header,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Topic detection
# ─────────────────────────────────────────────

async def detect_topic(user_id: int, group_id: int, thread_id: Optional[int]) -> str:
    """Return which topic a message was sent in.

    Returns one of: "signals" | "traders" | "portfolio" | "alerts" | "admin" | "general"
    Queries by group_id only (unique) — user_id param kept for API compat but unused.
    """
    if not thread_id:
        return "general"

    try:
        from sqlalchemy import select
        async with async_session() as session:
            config = (await session.execute(
                select(GroupConfig).where(GroupConfig.group_id == group_id)
            )).scalar_one_or_none()

            if not config:
                logger.info("detect_topic: no config for group=%s", group_id)
                return "general"

            mapping = {
                "signals":   config.topic_signals_id,
                "traders":   config.topic_traders_id,
                "portfolio": config.topic_portfolio_id,
                "alerts":    config.topic_alerts_id,
                "admin":     config.topic_admin_id,
            }

        logger.info(
            "detect_topic: group=%s thread=%s map=%s",
            group_id, thread_id, mapping,
        )

        for name, tid in mapping.items():
            if tid is not None and tid == thread_id:
                return name

        # Thread ID not found in mapping — all topic IDs might be NULL
        logger.warning(
            "detect_topic: thread_id=%s not in mapping %s — topic IDs may be missing",
            thread_id, mapping,
        )

    except Exception as e:
        logger.warning("detect_topic error: %s", e, exc_info=True)

    return "general"


def _detect_topic_from_name(topic_name: str) -> str:
    """Fallback: detect topic type from the forum topic name string.

    Matches against known topic name patterns (with or without emoji prefix).
    """
    if not topic_name:
        return "general"

    name_lower = topic_name.lower().strip()

    # Match with/without emoji prefix
    if "signal" in name_lower:
        return "signals"
    if "trader" in name_lower:
        return "traders"
    if "portfolio" in name_lower:
        return "portfolio"
    if "alert" in name_lower:
        return "alerts"
    if "admin" in name_lower:
        return "admin"

    return "general"


# ─────────────────────────────────────────────
# Main dispatcher
# ─────────────────────────────────────────────

async def show_topic_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Show a context-aware menu depending on which topic the message was sent in.

    Returns True if a topic menu was shown, False if caller should show generic menu.

    IMPORTANT: session stays open while calling _show_*_menu so ORM objects
    remain live (prevents DetachedInstanceError / MissingGreenlet in async).
    """
    if not update.effective_chat or update.effective_chat.type == "private":
        return False

    tg_user = update.effective_user
    group_id = update.effective_chat.id
    thread_id = getattr(update.effective_message, "message_thread_id", None)

    topic = await detect_topic(0, group_id, thread_id)  # user_id unused now

    # Fallback: if DB lookup returned "general" but we're in a named topic,
    # detect from the topic name and auto-repair the DB for next time.
    if topic == "general" and thread_id:
        topic_name = await _get_topic_name_from_message(update, context)
        if topic_name:
            topic = _detect_topic_from_name(topic_name)
            if topic != "general":
                logger.info(
                    "show_topic_menu: fallback detected topic=%s from name='%s' "
                    "(thread=%s group=%s) — auto-repairing DB",
                    topic, topic_name, thread_id, group_id,
                )
                await _auto_repair_topic_id(group_id, topic, thread_id, tg_user.id)

    logger.info("show_topic_menu: topic=%s thread=%s group=%s", topic, thread_id, group_id)

    if topic == "general":
        return False  # let caller show default menu

    try:
        async with async_session() as session:
            user = await get_user_by_telegram_id(session, tg_user.id)
            if not user:
                return False
            us = await get_or_create_settings(session, user)

            # Session stays open → ORM objects are live throughout
            if topic == "signals":
                await _show_signals_menu(update, user, us)
            elif topic == "traders":
                await _show_traders_menu(update, user, us)
            elif topic == "portfolio":
                await _show_portfolio_menu(update, user, us)
            elif topic == "alerts":
                await _show_alerts_menu(update, user, us)
            elif topic == "admin":
                await _show_admin_menu(update, user, us)
            else:
                return False

        return True

    except Exception as e:
        logger.warning("show_topic_menu error (topic=%s): %s", topic, e, exc_info=True)
        return False


# ─────────────────────────────────────────────
# Helpers: topic name detection + auto-repair
# ─────────────────────────────────────────────

async def _get_topic_name_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:
    """Try to get the forum topic name from the message context.

    Telegram messages in forum topics have reply_to_message pointing to
    the topic creation service message (forum_topic_created).
    """
    msg = update.effective_message
    if not msg:
        return None

    # Method 1: reply_to_message → forum_topic_created
    reply = msg.reply_to_message
    if reply and reply.forum_topic_created:
        return reply.forum_topic_created.name

    # Method 2: the message itself might be a forum_topic_created message
    if msg.forum_topic_created:
        return msg.forum_topic_created.name

    # Method 3: try the Telegram API to get topic info
    thread_id = getattr(msg, "message_thread_id", None)
    if thread_id and context.bot:
        try:
            chat = update.effective_chat
            # Get forum topic info by sending a dummy getForumTopicIconStickers
            # Actually, let's try get_chat which returns forum topics
            # But there's no direct API for single topic info.
            # Fall back to checking the pinned message / topic name from chat
            pass
        except Exception:
            pass

    return None


async def _auto_repair_topic_id(
    group_id: int, topic_name: str, thread_id: int, telegram_user_id: int,
) -> None:
    """Auto-repair: save the thread_id for a detected topic in GroupConfig.

    Creates the GroupConfig if it doesn't exist.
    """
    field_map = {
        "signals":   "topic_signals_id",
        "traders":   "topic_traders_id",
        "portfolio": "topic_portfolio_id",
        "alerts":    "topic_alerts_id",
        "admin":     "topic_admin_id",
    }
    field = field_map.get(topic_name)
    if not field:
        return

    try:
        from sqlalchemy import select
        async with async_session() as session:
            config = (await session.execute(
                select(GroupConfig).where(GroupConfig.group_id == group_id)
            )).scalar_one_or_none()

            if not config:
                # Create a new GroupConfig for this group
                from bot.services.user_service import get_user_by_telegram_id
                user = await get_user_by_telegram_id(session, telegram_user_id)
                config = GroupConfig(
                    group_id=group_id,
                    user_id=user.id if user else None,
                    is_forum=True,
                )
                session.add(config)

            # Only update if the field is NULL (don't overwrite valid IDs)
            current_value = getattr(config, field, None)
            if current_value is None:
                setattr(config, field, thread_id)
                logger.info(
                    "auto_repair: set %s=%s for group=%s",
                    field, thread_id, group_id,
                )

            # Check if all topics are now set
            config.setup_complete = config.all_topics_created
            await session.commit()

    except Exception as e:
        logger.warning("auto_repair_topic_id error: %s", e)


# ─────────────────────────────────────────────
# Scoring profiles + criteria definitions
# ─────────────────────────────────────────────

SCORING_PROFILES = {
    "prudent": {
        "label": "🛡️ Prudent",
        "short": "Sécurité maximale",
        "description": (
            "Score ≥ 65 — poids forts sur liquidité et forme trader.\n"
            "Moins de trades, mais de meilleure qualité."
        ),
        "min_signal_score": 65,
        "scoring_enabled": True,
        "criteria": {
            "spread": {"on": True, "w": 20},
            "liquidity": {"on": True, "w": 20},
            "conviction": {"on": True, "w": 15},
            "trader_form": {"on": True, "w": 25},
            "timing": {"on": True, "w": 10},
            "consensus": {"on": True, "w": 10},
        },
    },
    "equilibre": {
        "label": "⚖️ Équilibré",
        "short": "Bon compromis (recommandé)",
        "description": (
            "Score ≥ 40 — tous les critères activés, poids équilibrés.\n"
            "Le meilleur compromis quantité / qualité."
        ),
        "min_signal_score": 40,
        "scoring_enabled": True,
        "criteria": {
            "spread": {"on": True, "w": 15},
            "liquidity": {"on": True, "w": 15},
            "conviction": {"on": True, "w": 20},
            "trader_form": {"on": True, "w": 20},
            "timing": {"on": True, "w": 15},
            "consensus": {"on": True, "w": 15},
        },
    },
    "agressif": {
        "label": "⚡ Agressif",
        "short": "Plus de trades, plus de risques",
        "description": (
            "Score ≥ 20 — focus conviction + forme trader.\n"
            "Ignore spread et timing. Plus de trades copiés."
        ),
        "min_signal_score": 20,
        "scoring_enabled": True,
        "criteria": {
            "spread": {"on": False, "w": 0},
            "liquidity": {"on": True, "w": 10},
            "conviction": {"on": True, "w": 35},
            "trader_form": {"on": True, "w": 35},
            "timing": {"on": False, "w": 0},
            "consensus": {"on": True, "w": 20},
        },
    },
    "yolo": {
        "label": "🎲 Tout passe",
        "short": "Copie tout sans filtre",
        "description": (
            "Scoring désactivé — tous les signaux sont copiés.\n"
            "⚠️ Risqué — uniquement en paper trading."
        ),
        "min_signal_score": 0,
        "scoring_enabled": False,
        "criteria": None,
    },
    "custom": {
        "label": "🔧 Personnalisé",
        "short": "Configuration manuelle complète",
        "description": (
            "Aucun profil actif — vous gérez chaque critère\n"
            "et chaque filtre manuellement."
        ),
        "min_signal_score": None,  # keep current
        "scoring_enabled": True,
        "criteria": None,  # keep current
    },
}


# ─────────────────────────────────────────────
# Custom filters — toggleable settings beyond the 6 scoring criteria
# Each filter: field, label, emoji, description, unit, type, presets
# ─────────────────────────────────────────────

CUSTOM_FILTERS = {
    "skip_coin_flip": {
        "emoji": "🪙",
        "name": "Skip 50/50",
        "field": "skip_coin_flip",
        "type": "toggle",
        "description": (
            "Ignore les marchés où le prix est entre 0.45 et 0.55.\n"
            "Ces marchés sont des « coin-flip » (pile ou face) —\n"
            "aucun avantage statistique, autant ne pas miser."
        ),
    },
    "min_conviction": {
        "emoji": "💪",
        "name": "Conviction minimum",
        "field": "min_conviction_pct",
        "type": "value",
        "unit": "%",
        "description": (
            "Taille minimum du trade par rapport au portfolio\n"
            "du trader. Si le trader ne mise que 0.5% de son\n"
            "capital, c'est un signal faible — on le rejette.\n\n"
            "Recommandé : 2% minimum."
        ),
        "presets": [("1%", 1), ("2%", 2), ("3%", 3), ("5%", 5), ("10%", 10)],
    },
    "max_price_drift": {
        "emoji": "📐",
        "name": "Drift de prix max",
        "field": "max_price_drift_pct",
        "type": "value",
        "unit": "%",
        "description": (
            "Si le prix a bougé de plus de X% depuis le trade\n"
            "du trader, on ne copie pas (le prix a déjà bougé,\n"
            "on arriverait trop tard).\n\n"
            "Recommandé : 5% maximum."
        ),
        "presets": [("2%", 2), ("3%", 3), ("5%", 5), ("8%", 8), ("10%", 10)],
    },
    "min_trader_winrate": {
        "emoji": "🏆",
        "name": "Win rate min du trader",
        "field": "min_trader_winrate_for_type",
        "type": "value",
        "unit": "%",
        "description": (
            "Ne copie que les traders avec un win rate\n"
            "supérieur à ce seuil sur cette catégorie.\n"
            "Un trader à 40% perd de l'argent — inutile de copier.\n\n"
            "Recommandé : 55% minimum."
        ),
        "presets": [("45%", 45), ("50%", 50), ("55%", 55), ("60%", 60), ("70%", 70)],
    },
    "min_trader_trades": {
        "emoji": "📊",
        "name": "Trades min du trader",
        "field": "min_trader_trades_for_type",
        "type": "value",
        "unit": " trades",
        "description": (
            "Nombre minimum de trades passés par le trader\n"
            "avant qu'on le copie. Evite de copier quelqu'un\n"
            "qui n'a que 2 trades au compteur (pas fiable).\n\n"
            "Recommandé : 10 trades minimum."
        ),
        "presets": [("5", 5), ("10", 10), ("15", 15), ("20", 20), ("30", 30)],
    },
    "cold_trader_threshold": {
        "emoji": "🥶",
        "name": "Seuil trader froid",
        "field": "cold_trader_threshold",
        "type": "value",
        "unit": "%",
        "description": (
            "Si le win rate récent d'un trader descend sous\n"
            "ce seuil, le bot le met automatiquement en pause.\n"
            "Il ne sera plus copié tant qu'il ne remonte pas.\n\n"
            "Recommandé : 40%."
        ),
        "presets": [("30%", 30), ("35%", 35), ("40%", 40), ("45%", 45), ("50%", 50)],
    },
    "max_trade_usdc": {
        "emoji": "💰",
        "name": "Trade max (USDC)",
        "field": "max_trade_usdc",
        "type": "value",
        "unit": " USDC",
        "description": (
            "Montant maximum par trade copié en USDC.\n"
            "Même si le sizing calcule un montant plus élevé,\n"
            "il sera plafonné à cette valeur.\n\n"
            "Protection contre les mises trop grosses."
        ),
        "presets": [("25", 25), ("50", 50), ("100", 100), ("200", 200), ("500", 500)],
    },
    "min_trade_usdc": {
        "emoji": "🪙",
        "name": "Trade min (USDC)",
        "field": "min_trade_usdc",
        "type": "value",
        "unit": " USDC",
        "description": (
            "Montant minimum par trade. Si le sizing calcule\n"
            "un montant inférieur, le trade est ignoré\n"
            "(pas rentable avec les frais de gas)."
        ),
        "presets": [("0.5", 0.5), ("1", 1), ("2", 2), ("5", 5), ("10", 10)],
    },
    "max_positions": {
        "emoji": "📦",
        "name": "Positions max",
        "field": "max_positions",
        "type": "value",
        "unit": "",
        "description": (
            "Nombre maximum de positions ouvertes en même temps.\n"
            "Au-delà, les nouveaux signaux sont ignorés.\n"
            "Evite de trop s'exposer sur le marché.\n\n"
            "Recommandé : 10-15."
        ),
        "presets": [("5", 5), ("10", 10), ("15", 15), ("20", 20), ("30", 30)],
    },
    "max_category_exposure": {
        "emoji": "📂",
        "name": "Exposition max / catégorie",
        "field": "max_category_exposure_pct",
        "type": "value",
        "unit": "%",
        "description": (
            "% maximum du portfolio dans une seule catégorie\n"
            "(Crypto, Sports, Politique…). Evite d'avoir\n"
            "80% sur un seul secteur.\n\n"
            "Recommandé : 30%."
        ),
        "presets": [("20%", 20), ("25%", 25), ("30%", 30), ("40%", 40), ("50%", 50)],
    },
    "max_direction_bias": {
        "emoji": "⚖️",
        "name": "Biais direction max",
        "field": "max_direction_bias_pct",
        "type": "value",
        "unit": "%",
        "description": (
            "% maximum de positions dans la même direction\n"
            "(YES ou NO). Si 90% de vos positions sont YES,\n"
            "vous êtes trop exposé dans un sens.\n\n"
            "Recommandé : 70%."
        ),
        "presets": [("60%", 60), ("65%", 65), ("70%", 70), ("80%", 80), ("90%", 90)],
    },
    "hot_streak_boost": {
        "emoji": "🔥",
        "name": "Boost hot streak",
        "field": "hot_streak_boost",
        "type": "value",
        "unit": "×",
        "description": (
            "Multiplicateur de mise quand un trader est en\n"
            "série de victoires. Un trader qui enchaîne les\n"
            "gains voit sa mise copiée avec un bonus.\n\n"
            "×1.0 = pas de boost, ×2.0 = mise doublée."
        ),
        "presets": [("×1.0", 1.0), ("×1.2", 1.2), ("×1.5", 1.5), ("×1.8", 1.8), ("×2.0", 2.0)],
    },
}

CUSTOM_FILTER_ORDER = [
    "skip_coin_flip", "min_conviction", "max_price_drift",
    "min_trader_winrate", "min_trader_trades", "cold_trader_threshold",
    "max_trade_usdc", "min_trade_usdc", "max_positions",
    "max_category_exposure", "max_direction_bias", "hot_streak_boost",
]

CRITERIA_INFO = {
    "spread": {
        "emoji": "📏",
        "name": "Spread",
        "short": "Écart achat/vente",
        "description": (
            "Le spread mesure l'écart entre le prix d'achat\n"
            "et de vente sur le marché Polymarket.\n\n"
            "Un spread serré (< 1%) = marché actif, bon prix.\n"
            "Un gros spread (> 5%) = vous payez cher pour entrer."
        ),
        "thresholds": (
            "🟢 < 1% → 100 pts\n"
            "🟡 1-2% → 80 pts\n"
            "🟠 2-3% → 60 pts\n"
            "🔴 > 5% → 0 pts"
        ),
    },
    "liquidity": {
        "emoji": "💧",
        "name": "Liquidité",
        "short": "Volume du marché (24h)",
        "description": (
            "Le volume échangé sur 24h indique si le marché\n"
            "est actif.\n\n"
            "Volume élevé = facile d'acheter/vendre sans\n"
            "impact sur le prix. Volume faible = risque de\n"
            "slippage important."
        ),
        "thresholds": (
            "🟢 > $500K → 100 pts\n"
            "🟡 > $100K → 80 pts\n"
            "🟠 > $50K → 60 pts\n"
            "🔴 < $10K → 10 pts"
        ),
    },
    "conviction": {
        "emoji": "💪",
        "name": "Conviction",
        "short": "Taille de mise du trader",
        "description": (
            "Mesure combien le trader mise par rapport à\n"
            "son portfolio total.\n\n"
            "10% du capital = forte conviction, il y croit.\n"
            "< 2% = petit pari sans importance, signal faible."
        ),
        "thresholds": (
            "🟢 > 10% du portfolio → 100 pts\n"
            "🟡 > 5% → 80 pts\n"
            "🟠 > 2% → 60 pts\n"
            "🔴 < 2% → 20 pts"
        ),
    },
    "trader_form": {
        "emoji": "📈",
        "name": "Forme du trader",
        "short": "Win rate sur 7 jours",
        "description": (
            "Performances récentes du trader sur 7 jours.\n\n"
            "Un trader à 70%+ est en forme, ses signaux\n"
            "sont fiables. En dessous de 40%, il traverse\n"
            "une mauvaise passe — prudence."
        ),
        "thresholds": (
            "🟢 > 70% WR → 100 pts\n"
            "🟡 > 60% → 80 pts\n"
            "🟠 > 50% → 60 pts\n"
            "🔴 < 40% → 0 pts"
        ),
    },
    "timing": {
        "emoji": "⏱️",
        "name": "Timing",
        "short": "Distance à l'expiry",
        "description": (
            "Quand le marché Polymarket expire-t-il ?\n\n"
            "Sweet spot = 2h à 48h : assez proche pour que\n"
            "le prix bouge, assez loin pour sortir si besoin.\n"
            "Trop lointain = capital bloqué longtemps."
        ),
        "thresholds": (
            "🟢 2h-48h → 100 pts (zone idéale)\n"
            "🟡 2j-1 sem → 80 pts\n"
            "🟠 1 sem-1 mois → 60 pts\n"
            "🔴 > 3 mois → 20 pts"
        ),
    },
    "consensus": {
        "emoji": "👥",
        "name": "Consensus",
        "short": "Autres traders sur ce marché",
        "description": (
            "Vérifie si d'autres traders que vous suivez\n"
            "ont aussi misé sur ce marché.\n\n"
            "3+ traders = signal de consensus fort.\n"
            "1 seul trader = moins de certitude."
        ),
        "thresholds": (
            "🟢 3+ traders → 100 pts\n"
            "🟡 2 traders → 70 pts\n"
            "🟠 1 trader → 40 pts\n"
            "🔴 0 autre → 20 pts"
        ),
    },
}

CRITERIA_ORDER = ["spread", "liquidity", "conviction", "trader_form", "timing", "consensus"]
WEIGHT_OPTIONS = [5, 10, 15, 20, 25, 30, 35, 40]

from bot.services.signal_scorer import DEFAULT_CRITERIA


def _detect_active_profile(us) -> str:
    """Detect which profile matches the user's current settings."""
    criteria = getattr(us, "scoring_criteria", None)
    min_score = float(getattr(us, "min_signal_score", 40.0))
    scoring_on = bool(getattr(us, "signal_scoring_enabled", True))

    if not scoring_on:
        return "yolo"

    for key, profile in SCORING_PROFILES.items():
        if key == "yolo":
            continue
        if abs(min_score - profile["min_signal_score"]) > 0.1:
            continue
        if criteria == profile["criteria"]:
            return key
        if criteria is None and key == "equilibre":
            return key

    return "custom"


def _get_user_criteria(us) -> dict:
    """Get user's criteria config, falling back to defaults."""
    criteria = getattr(us, "scoring_criteria", None)
    if criteria:
        return criteria
    return dict(DEFAULT_CRITERIA)


# ─────────────────────────────────────────────
# 📊 Signals topic
# ─────────────────────────────────────────────

async def _show_signals_menu(update: Update, user: User, us) -> None:
    """Écran du topic 📊 Signals — scoring, filtres, derniers signaux."""
    from bot.models.signal_score import SignalScore
    from bot.services.signal_scorer import compute_weights
    from sqlalchemy import select, func

    scoring_on = bool(getattr(us, "signal_scoring_enabled", True))
    smart_on   = bool(getattr(us, "smart_filter_enabled", True))
    min_score  = float(getattr(us, "min_signal_score", 40.0))
    criteria   = _get_user_criteria(us)
    profile    = _detect_active_profile(us)
    profile_label = SCORING_PROFILES.get(profile, {}).get("label", "🔧 Personnalisé")

    on  = "✅"
    off = "❌"

    # Compute effective weights for display
    weights = compute_weights(criteria)

    # Stats signaux récents
    total_signals = 0
    passed_signals = 0
    avg_score = 0.0
    try:
        async with async_session() as session:
            total_signals = (await session.scalar(
                select(func.count(SignalScore.id))
            )) or 0
            passed_signals = (await session.scalar(
                select(func.count(SignalScore.id)).where(SignalScore.passed == True)  # noqa
            )) or 0
            avg_score = float((await session.scalar(
                select(func.avg(SignalScore.total_score))
            )) or 0)
    except Exception:
        pass

    block_rate = ((total_signals - passed_signals) / total_signals * 100) if total_signals > 0 else 0
    pass_rate  = 100 - block_rate

    # Count active custom filters
    active_filters = 0
    for fk in CUSTOM_FILTER_ORDER:
        finfo = CUSTOM_FILTERS[fk]
        if finfo["type"] == "toggle":
            if bool(getattr(us, finfo["field"], False)):
                active_filters += 1
        else:
            active_filters += 1  # value filters are always "active"

    lines = [
        f"📊 *SIGNAUX & SCORING*\n{SEP}\n",
        f"*Profil :* {profile_label}",
        f"*Scoring :* {on if scoring_on else off} | *Seuil :* {min_score:.0f}/100",
        f"*Smart Filter :* {on if smart_on else off} | *Filtres custom :* {active_filters}\n",
    ]

    # ── Formula explanation (concise) ──
    lines.append("*── Comment ça marche ──*\n")
    lines.append(
        "_Chaque signal de trade reçu est noté sur 100._\n"
        "_6 critères sont évalués et pondérés :_\n"
    )

    # Build a compact formula view
    formula_parts = []
    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        cfg = criteria.get(key, {"on": True, "w": 15})
        is_on = cfg.get("on", True)
        eff_w = round(weights.get(key, 0) * 100)

        if is_on:
            formula_parts.append(f"{info['emoji']}{eff_w}%")
            lines.append(
                f"  {info['emoji']} *{info['name']}* — {eff_w}%"
                f"  _{info['short']}_"
            )
        else:
            lines.append(f"  {info['emoji']} ~~{info['name']}~~ — _désactivé_")

    lines.append("")
    lines.append(f"_Score = {' + '.join(formula_parts)}_")
    lines.append(f"_Si score < {min_score:.0f} → signal rejeté_\n")

    # Stats historique
    if total_signals > 0:
        accept_bar = bar(pass_rate, 100, 12)
        lines += [
            f"*── Stats ──*",
            f"{total_signals} signaux | moy. *{avg_score:.0f}/100* | "
            f"{accept_bar} *{pass_rate:.0f}%* acceptés\n",
        ]

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton("📋 Profils", callback_data="sc_profiles"),
            InlineKeyboardButton("🎯 Critères (6)", callback_data="sc_criteria"),
        ],
        [
            InlineKeyboardButton("🔧 Filtres custom", callback_data="sc_filters"),
            InlineKeyboardButton("📖 Formule détaillée", callback_data="sc_formula"),
        ],
        [
            InlineKeyboardButton(f"🎯 Seuil : {min_score:.0f}", callback_data="set_min_signal_score"),
            InlineKeyboardButton(f"🧠 Scoring : {on if scoring_on else off}", callback_data="set_signal_scoring_enabled"),
        ],
        [
            InlineKeyboardButton(f"🔍 Smart Filter : {on if smart_on else off}", callback_data="set_smart_filter_enabled"),
        ],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# 👤 Traders topic
# ─────────────────────────────────────────────

async def _show_traders_menu(update: Update, user: User, us) -> None:
    """Écran du topic 👤 Traders — suivi, stats, pause."""
    from bot.models.trader_stats import TraderStats
    from sqlalchemy import select

    followed = list(getattr(us, "followed_wallets", None) or [])
    auto_pause = bool(getattr(us, "auto_pause_cold_traders", True))
    cold_thresh = float(getattr(us, "cold_trader_threshold", 40.0))
    hot_boost  = float(getattr(us, "hot_streak_boost", 1.5))

    # Récupère les stats trader pour les wallets suivis
    trader_lines = []
    try:
        async with async_session() as session:
            for wallet in followed[:8]:
                stat = (await session.execute(
                    select(TraderStats).where(
                        TraderStats.wallet == wallet,
                        TraderStats.period == "7d",
                    )
                )).scalar_one_or_none()

                short = sw(wallet)
                if stat:
                    badge = badge_trader_status(stat.win_rate, stat.trade_count)
                    wr_bar = bar(stat.win_rate, 100, 8)
                    pnl_sign = "+" if stat.total_pnl >= 0 else ""
                    paused = " ⏸️" if stat.auto_paused else ""
                    trader_lines.append(
                        f"  {badge} `{short}` — *{stat.win_rate:.0f}%* WR "
                        f"{wr_bar}\n"
                        f"    {stat.trade_count} trades | PNL: *{pnl_sign}{fmt_usd(stat.total_pnl)}*{paused}"
                    )
                else:
                    trader_lines.append(f"  ⏳ `{short}` — stats en cours de calcul")
    except Exception:
        trader_lines = [f"  • `{sw(w)}`" for w in followed[:8]]

    n = len(followed)
    on = "✅"
    off = "❌"

    lines = [
        f"👤 *TRADERS SUIVIS*\n{SEP}\n",
        f"*{n} trader{'s' if n > 1 else ''} suivi{'s' if n > 1 else ''}*\n",
    ]
    if trader_lines:
        lines += trader_lines
        lines.append("")
    else:
        lines.append("_Aucun trader suivi pour l'instant._\n")

    lines += [
        f"*Protection automatique :*",
        f"  Auto-pause cold traders : {on if auto_pause else off}",
        f"  Seuil cold : *{cold_thresh:.0f}%* WR",
        f"  Boost hot trader : *×{hot_boost:.1f}*",
    ]

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton("➕ Suivre un trader", callback_data="set_add_wallet"),
            InlineKeyboardButton("➖ Retirer un trader", callback_data="set_followed"),
        ],
        [
            InlineKeyboardButton("📊 Analytics détaillés", callback_data="v3_analytics"),
            InlineKeyboardButton("🔄 Rafraîchir", callback_data="menu_traders"),
        ],
        [
            InlineKeyboardButton(f"⏸️ Auto-pause : {on if auto_pause else off}", callback_data="set_auto_pause_cold_traders"),
            InlineKeyboardButton(f"🥶 Seuil : {cold_thresh:.0f}%", callback_data="set_cold_trader_threshold"),
        ],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# 💼 Portfolio topic
# ─────────────────────────────────────────────

async def _show_portfolio_menu(update: Update, user: User, us) -> None:
    """Écran du topic 💼 Portfolio — positions, PNL, exposition."""
    from bot.models.active_position import ActivePosition
    from bot.models.trade import Trade, TradeStatus, TradeSide
    from sqlalchemy import select, and_

    max_pos     = int(getattr(us, "max_positions", 15))
    max_cat_exp = float(getattr(us, "max_category_exposure_pct", 30.0))
    max_dir     = float(getattr(us, "max_direction_bias_pct", 70.0))

    # Compte les positions ouvertes + PNL approximatif
    open_count = 0
    total_invested = 0.0
    yes_count = 0
    no_count  = 0
    categories: dict[str, int] = {}

    try:
        async with async_session() as session:
            # Active positions (V3 tracking)
            positions = list((await session.execute(
                select(ActivePosition).where(
                    and_(ActivePosition.user_id == user.id,
                         ActivePosition.is_closed == False)  # noqa
                )
            )).scalars().all())
            open_count = len(positions)

            for p in positions:
                shares = p.shares or 0
                entry  = p.entry_price or 0
                total_invested += shares * entry
                if p.outcome and p.outcome.upper() in ("YES", "Y", "BUY"):
                    yes_count += 1
                else:
                    no_count += 1
                cat = "Autre"
                if p.market_question:
                    q = p.market_question.lower()
                    if any(k in q for k in ("btc", "bitcoin", "eth", "crypto", "sol")):
                        cat = "Crypto"
                    elif any(k in q for k in ("trump", "biden", "election", "president")):
                        cat = "Politique"
                    elif any(k in q for k in ("nfl", "nba", "soccer", "football")):
                        cat = "Sports"
                    elif any(k in q for k in ("fed", "gdp", "inflation", "rate")):
                        cat = "Économie"
                categories[cat] = categories.get(cat, 0) + 1
    except Exception as e:
        logger.debug("portfolio topic fetch error: %s", e)

    pos_bar  = bar(open_count, max_pos, 12)
    yes_pct  = round(yes_count / open_count * 100, 0) if open_count else 0
    no_pct   = 100 - yes_pct
    dir_bar  = bar_bicolor(yes_count, no_count, max(open_count, 1), 12)

    lines = [
        f"💼 *PORTFOLIO*\n{SEP}\n",
        f"*{open_count}/{max_pos}* positions ouvertes",
        f"{pos_bar} {open_count}/{max_pos}\n",
    ]

    if total_invested > 0:
        lines.append(f"💵 Investi : *{fmt_usd(total_invested)}*\n")

    if open_count > 0:
        lines += [
            f"*Direction :*",
            f"  {dir_bar}",
            f"  YES *{yes_pct:.0f}%* / NO *{no_pct:.0f}%*\n",
        ]
        if categories:
            lines.append("*Exposition par catégorie :*")
            for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
                pct = round(cnt / open_count * 100, 0)
                cat_bar = bar(pct, 100, 10)
                over = " ⚠️" if pct > max_cat_exp else ""
                lines.append(f"  {cat_bar} {cat} *{pct:.0f}%*{over}")
            lines.append("")
    else:
        lines.append("_Aucune position ouverte._\n")

    lines += [
        f"*Limites de risque :*",
        f"  Max positions : *{max_pos}*",
        f"  Max catégorie : *{max_cat_exp:.0f}%*",
        f"  Biais direction max : *{max_dir:.0f}%*",
    ]

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton("📊 Détail des positions", callback_data="menu_positions"),
            InlineKeyboardButton("📜 Historique", callback_data="menu_history"),
        ],
        [
            InlineKeyboardButton(f"📦 Max positions : {max_pos}", callback_data="set_max_positions"),
            InlineKeyboardButton(f"📂 Max catégorie : {max_cat_exp:.0f}%", callback_data="set_max_category_exposure_pct"),
        ],
        [
            InlineKeyboardButton(f"⚖️ Biais max : {max_dir:.0f}%", callback_data="set_max_direction_bias_pct"),
            InlineKeyboardButton("🔄 Rafraîchir", callback_data="menu_portfolio_refresh"),
        ],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# 🚨 Alerts topic
# ─────────────────────────────────────────────

async def _show_alerts_menu(update: Update, user: User, us) -> None:
    """Écran du topic 🚨 Alerts — SL/TP/trailing/time exit."""
    sl_on       = bool(getattr(us, "stop_loss_enabled", True))
    sl_pct      = float(getattr(us, "stop_loss_pct", 20.0))
    tp_on       = bool(getattr(us, "take_profit_enabled", False))
    tp_pct      = float(getattr(us, "take_profit_pct", 50.0))
    trail_on    = bool(getattr(us, "trailing_stop_enabled", False))
    trail_pct   = float(getattr(us, "trailing_stop_pct", 10.0))
    time_on     = bool(getattr(us, "time_exit_enabled", False))
    time_h      = int(getattr(us, "time_exit_hours", 24))
    scale_on    = bool(getattr(us, "scale_out_enabled", False))
    scale_pct   = float(getattr(us, "scale_out_pct", 50.0))

    on  = "✅"
    off = "❌"

    def _status(enabled, value, unit=""):
        if enabled:
            return f"{on} *{value:.0f}{unit}*"
        return f"{off} désactivé"

    lines = [
        f"🚨 *ALERTES & PROTECTIONS*\n{SEP}\n",
        f"*🛑 Stop-Loss :* {_status(sl_on, sl_pct, '%')}",
        f"   Clôture si position baisse de *{sl_pct:.0f}%*\n",
        f"*🎯 Take-Profit :* {_status(tp_on, tp_pct, '%')}",
        f"   Clôture si position monte de *{tp_pct:.0f}%*\n",
        f"*📉 Trailing Stop :* {_status(trail_on, trail_pct, '%')}",
        f"   Suit le prix — déclenche si repli de *{trail_pct:.0f}%* depuis le sommet\n",
        f"*⏰ Time Exit :* {_status(time_on, time_h, 'h')}",
        f"   Clôture automatiquement après *{time_h}h* si toujours ouverte\n",
        f"*📤 Scale-Out :* {_status(scale_on, scale_pct, '%')}",
        f"   Prend *{scale_pct:.0f}%* des gains au TP puis laisse courir",
    ]

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton(f"🛑 Stop-Loss : {sl_pct:.0f}%", callback_data="set_stop_loss_menu"),
            InlineKeyboardButton(f"🎯 Take-Profit : {tp_pct:.0f}%", callback_data="set_take_profit_menu"),
        ],
        [
            InlineKeyboardButton(f"📉 Trailing : {on if trail_on else off}", callback_data="set_trailing_stop_enabled"),
            InlineKeyboardButton(f"📉 Trailing : {trail_pct:.0f}%", callback_data="set_trailing_stop_pct"),
        ],
        [
            InlineKeyboardButton(f"⏰ Time Exit : {on if time_on else off}", callback_data="set_time_exit_enabled"),
            InlineKeyboardButton(f"⏰ Durée : {time_h}h", callback_data="set_time_exit_hours"),
        ],
        [
            InlineKeyboardButton(f"📤 Scale-Out : {on if scale_on else off}", callback_data="set_scale_out_enabled"),
            InlineKeyboardButton(f"📤 Scale-Out : {scale_pct:.0f}%", callback_data="set_scale_out_pct"),
        ],
        [InlineKeyboardButton("📊 Positions ouvertes", callback_data="menu_positions")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# ⚙️ Admin topic
# ─────────────────────────────────────────────

async def _show_admin_menu(update: Update, user: User, us) -> None:
    """Écran du topic ⚙️ Admin — statut bot, wallet, paramètres."""
    from bot.services.web3_client import polygon_client

    is_active   = user.is_active
    is_paused   = user.is_paused
    paper       = user.paper_trading
    wallet_addr = user.wallet_address or ""
    notif_mode  = getattr(us, "notification_mode", "group")

    # Status
    if is_paused:
        status_icon, status_text = "⏸️", "Pause"
    elif is_active:
        status_icon, status_text = "🟢", "Actif"
    else:
        status_icon, status_text = "🔴", "Inactif"

    mode_icon = "📝" if paper else "💵"
    mode_text = "Paper Trading" if paper else "Live"
    notif_icon = "💬" if notif_mode == "dm" else ("📊" if notif_mode == "group" else "🔀")
    notif_text = {"dm": "DM seulement", "group": "Groupe seulement", "both": "DM + Groupe"}.get(notif_mode, notif_mode)

    # Solde wallet
    usdc_str = "—"
    pol_str  = "—"
    if wallet_addr:
        try:
            if paper:
                usdc_str = fmt_usd(user.paper_balance or 0)
                pol_str  = "N/A (paper)"
            else:
                usdc, _ = await polygon_client.get_usdc_balances(wallet_addr)
                pol      = await polygon_client.get_matic_balance(wallet_addr)
                usdc_str = fmt_usd(usdc)
                pol_str  = f"{pol:.4f} POL"
        except Exception:
            pass

    wallet_short = f"`{wallet_addr[:6]}...{wallet_addr[-4:]}`" if wallet_addr else "non configuré"

    lines = [
        f"⚙️ *ADMINISTRATION*\n{SEP}\n",
        f"*Statut :* {status_icon} {status_text}",
        f"*Mode :* {mode_icon} {mode_text}",
        f"*Notifications :* {notif_icon} {notif_text}\n",
        f"*Wallet :* {wallet_short}",
        f"  💵 USDC : *{usdc_str}*",
        f"  ⛽ Gas : *{pol_str}*\n",
        f"*Scoring :* {'✅ actif' if getattr(us, 'signal_scoring_enabled', True) else '❌ inactif'} "
        f"| Seuil : *{getattr(us, 'min_signal_score', 40):.0f}/100*",
        f"*SL :* {'✅' if getattr(us, 'stop_loss_enabled', True) else '❌'} "
        f"*{getattr(us, 'stop_loss_pct', 20):.0f}%* "
        f"| *TP :* {'✅' if getattr(us, 'take_profit_enabled', False) else '❌'}",
    ]

    text = "\n".join(lines)

    # Bouton pause/resume selon état
    if is_paused:
        ctrl_btn = InlineKeyboardButton("▶️ Reprendre le copy", callback_data="resume_copy")
    elif is_active:
        ctrl_btn = InlineKeyboardButton("⏸️ Mettre en pause", callback_data="stop_copy")
    else:
        ctrl_btn = InlineKeyboardButton("▶️ Activer le copy", callback_data="resume_copy")

    keyboard = [
        [
            InlineKeyboardButton("⚙️ Tous les paramètres", callback_data="menu_settings"),
            InlineKeyboardButton("👛 Mon wallet", callback_data="menu_balance"),
        ],
        [
            InlineKeyboardButton("💳 Déposer des USDC", callback_data="menu_deposit"),
            InlineKeyboardButton("💸 Retirer", callback_data="menu_withdraw"),
        ],
        [
            ctrl_btn,
            InlineKeyboardButton(f"{mode_icon} Changer de mode", callback_data="set_paper_trading"),
        ],
        [
            InlineKeyboardButton(f"{notif_icon} Notifs : {notif_text[:12]}", callback_data="set_v3_notif"),
            InlineKeyboardButton("📊 Mon groupe", callback_data="menu_mygroup"),
        ],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─────────────────────────────────────────────
# Scoring sub-menus (profiles, criteria, detail)
# ─────────────────────────────────────────────

async def show_scoring_profiles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les profils de scoring prédéfinis."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        active = _detect_active_profile(us)

    lines = [
        f"📋 *PROFILS DE SCORING*\n{SEP}\n",
        "_Choisissez un profil qui définit automatiquement_",
        "_le score minimum et les poids de chaque critère._\n",
    ]

    for key, profile in SCORING_PROFILES.items():
        marker = " ← *actif*" if key == active else ""
        lines.append(f"*{profile['label']}* — {profile['short']}{marker}")
        lines.append(f"  _{profile['description']}_\n")

    if active == "custom":
        lines.append("🔧 *Personnalisé* ← *actif*")
        lines.append("  _Configuration manuelle des critères._\n")

    text = "\n".join(lines)

    keyboard = [
        [
            InlineKeyboardButton("🛡️ Prudent", callback_data="sc_apply:prudent"),
            InlineKeyboardButton("⚖️ Équilibré", callback_data="sc_apply:equilibre"),
        ],
        [
            InlineKeyboardButton("⚡ Agressif", callback_data="sc_apply:agressif"),
            InlineKeyboardButton("🎲 Tout passe", callback_data="sc_apply:yolo"),
        ],
        [InlineKeyboardButton("🔧 Personnalisé (tout régler)", callback_data="sc_apply:custom")],
        [InlineKeyboardButton("⬅️ Retour aux signaux", callback_data="sc_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def apply_scoring_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Applique un profil de scoring prédéfini."""
    query = update.callback_query
    profile_key = query.data.replace("sc_apply:", "")

    profile = SCORING_PROFILES.get(profile_key)
    if not profile:
        await query.answer("❌ Profil inconnu", show_alert=True)
        return

    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)

        # "custom" profile: keep current criteria/score, just enable scoring
        if profile_key == "custom":
            us.signal_scoring_enabled = True
            # Ensure scoring_criteria exists (copy from defaults if None)
            if not us.scoring_criteria:
                us.scoring_criteria = dict(DEFAULT_CRITERIA)
        else:
            us.min_signal_score = profile["min_signal_score"]
            us.signal_scoring_enabled = profile["scoring_enabled"]
            us.scoring_criteria = profile["criteria"]

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(us, "scoring_criteria")
        await session.commit()

    await query.answer(f"✅ Profil {profile['label']} activé", show_alert=False)

    # Custom → go directly to criteria list for editing
    if profile_key == "custom":
        await show_scoring_criteria_list(update, context)
    else:
        await show_scoring_profiles(update, context)


async def show_scoring_criteria_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche la liste des critères de scoring avec toggle + poids."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_user_criteria(us)

    on = "✅"
    off = "❌"

    lines = [
        f"🎯 *CRITÈRES DE SCORING*\n{SEP}\n",
        "_Chaque signal est noté de 0 à 100 en combinant_",
        "_ces critères. Activez/désactivez chacun et_",
        "_ajustez son poids (importance relative)._\n",
        "_Les poids sont redistribués automatiquement_",
        "_pour que le total fasse toujours 100%._\n",
    ]

    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        cfg = criteria.get(key, {"on": True, "w": 15})
        is_on = cfg.get("on", True)
        weight = cfg.get("w", 15)
        status = on if is_on else off
        lines.append(f"{info['emoji']} *{info['name']}* {status} — Poids : *{weight}%*")
        lines.append(f"  _{info['short']}_")

    text = "\n".join(lines)

    keyboard = []
    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        cfg = criteria.get(key, {"on": True, "w": 15})
        is_on = cfg.get("on", True)
        weight = cfg.get("w", 15)
        status = on if is_on else off
        keyboard.append([
            InlineKeyboardButton(
                f"{info['emoji']} {info['name']} {status} {weight}%",
                callback_data=f"sc_detail:{key}",
            ),
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Retour aux signaux", callback_data="sc_back")])

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_criterion_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche le détail d'un critère avec explication + barème + réglages."""
    query = update.callback_query
    crit_key = query.data.replace("sc_detail:", "")

    info = CRITERIA_INFO.get(crit_key)
    if not info:
        await query.answer("❌ Critère inconnu", show_alert=True)
        return

    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_user_criteria(us)

    cfg = criteria.get(crit_key, {"on": True, "w": 15})
    is_on = cfg.get("on", True)
    weight = cfg.get("w", 15)

    on = "✅"
    off = "❌"

    lines = [
        f"{info['emoji']} *{info['name'].upper()}*\n{SEP}\n",
        f"_{info['short']}_\n",
        f"{info['description']}\n",
        f"*── Barème de notation ──*\n",
        f"{info['thresholds']}\n",
        f"*── Réglages actuels ──*\n",
        f"État : {on if is_on else off} {'Activé' if is_on else 'Désactivé'}",
        f"Poids : *{weight}%* de la note finale",
    ]

    text = "\n".join(lines)

    toggle_label = "❌ Désactiver" if is_on else "✅ Activer"
    keyboard = [
        [InlineKeyboardButton(toggle_label, callback_data=f"sc_toggle:{crit_key}")],
    ]

    # Weight buttons
    weight_buttons = []
    for w in WEIGHT_OPTIONS:
        label = f"{'✓ ' if w == weight else ''}{w}%"
        weight_buttons.append(
            InlineKeyboardButton(label, callback_data=f"sc_weight:{crit_key}:{w}")
        )
    keyboard.append(weight_buttons[:4])
    keyboard.append(weight_buttons[4:])

    keyboard.append([InlineKeyboardButton("⬅️ Retour aux critères", callback_data="sc_criteria")])

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def toggle_criterion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle un critère ON/OFF dans scoring_criteria."""
    query = update.callback_query
    crit_key = query.data.replace("sc_toggle:", "")

    if crit_key not in CRITERIA_INFO:
        await query.answer("❌ Critère inconnu", show_alert=True)
        return

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)

        criteria = _get_user_criteria(us)
        cfg = criteria.get(crit_key, {"on": True, "w": 15})
        cfg["on"] = not cfg.get("on", True)
        criteria[crit_key] = cfg

        us.scoring_criteria = criteria
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(us, "scoring_criteria")
        await session.commit()

        new_on = cfg["on"]

    name = CRITERIA_INFO[crit_key]["name"]
    new_state = "activé" if new_on else "désactivé"
    await query.answer(f"✅ {name} {new_state}", show_alert=False)

    # Refresh criterion detail
    query.data = f"sc_detail:{crit_key}"
    await show_criterion_detail(update, context)


async def set_criterion_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Définit le poids d'un critère de scoring."""
    query = update.callback_query
    parts = query.data.replace("sc_weight:", "").split(":")
    if len(parts) != 2:
        await query.answer("❌ Format invalide", show_alert=True)
        return

    crit_key, weight_str = parts
    if crit_key not in CRITERIA_INFO:
        await query.answer("❌ Critère inconnu", show_alert=True)
        return

    try:
        weight = int(weight_str)
    except ValueError:
        await query.answer("❌ Poids invalide", show_alert=True)
        return

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)

        criteria = _get_user_criteria(us)
        cfg = criteria.get(crit_key, {"on": True, "w": 15})
        cfg["w"] = weight
        criteria[crit_key] = cfg

        us.scoring_criteria = criteria
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(us, "scoring_criteria")
        await session.commit()

    name = CRITERIA_INFO[crit_key]["name"]
    await query.answer(f"✅ {name} → {weight}%", show_alert=False)

    # Refresh criterion detail
    query.data = f"sc_detail:{crit_key}"
    await show_criterion_detail(update, context)


async def show_formula_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche l'explication détaillée de la formule de scoring."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        criteria = _get_user_criteria(us)

    from bot.services.signal_scorer import compute_weights
    weights = compute_weights(criteria)

    lines = [
        f"📖 *COMMENT LE SCORE EST CALCULÉ*\n{SEP}\n",
        "*1. Réception du signal*",
        "_Quand un trader que vous suivez fait un trade_",
        "_sur Polymarket, le bot reçoit le signal._\n",

        "*2. Évaluation sur 6 critères*",
        "_Chaque critère donne une note de 0 à 100 :_\n",
    ]

    for key in CRITERIA_ORDER:
        info = CRITERIA_INFO[key]
        cfg = criteria.get(key, {"on": True, "w": 15})
        is_on = cfg.get("on", True)
        eff_w = round(weights.get(key, 0) * 100)

        if is_on:
            lines.append(f"  {info['emoji']} *{info['name']}* — poids *{eff_w}%*")
            lines.append(f"    _{info['short']}_")
            lines.append(f"    {info['thresholds'].split(chr(10))[0]}")  # first threshold line
        else:
            lines.append(f"  {info['emoji']} ~~{info['name']}~~ — _désactivé (0%)_")

    lines += [
        "",
        "*3. Calcul de la note finale*",
        "_Score = somme pondérée de chaque critère._",
        "",
        "_Exemple concret :_",
        "  Spread = 80/100 (poids 15%)",
        "  Liquidité = 60/100 (poids 15%)",
        "  Conviction = 90/100 (poids 20%)",
        "  Forme trader = 70/100 (poids 20%)",
        "  Timing = 100/100 (poids 15%)",
        "  Consensus = 40/100 (poids 15%)",
        "",
        "  Score = 80×15% + 60×15% + 90×20%",
        "          + 70×20% + 100×15% + 40×15%",
        "  *Score = 74/100*",
        "",
        "*4. Décision*",
        f"  Si score >= seuil (*{float(getattr(us, 'min_signal_score', 40)):.0f}*) → copié",
        f"  Si score < seuil → rejeté",
        "",
        "*5. Filtres supplémentaires*",
        "_Même si le score passe, les filtres custom_",
        "_peuvent encore bloquer le trade (conviction_",
        "_trop faible, prix trop volatile, etc.)._",
    ]

    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton("🎯 Modifier les critères", callback_data="sc_criteria")],
        [InlineKeyboardButton("🔧 Filtres custom", callback_data="sc_filters")],
        [InlineKeyboardButton("⬅️ Retour aux signaux", callback_data="sc_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_custom_filters_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche tous les filtres custom activables/réglables."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)

    on = "✅"
    off = "❌"

    lines = [
        f"🔧 *FILTRES PERSONNALISÉS*\n{SEP}\n",
        "_Ces filtres s'appliquent EN PLUS du score._",
        "_Un signal peut avoir 80/100 mais être bloqué_",
        "_par un filtre (ex: conviction trop basse)._\n",
        "_Cliquez sur un filtre pour le configurer._\n",
    ]

    keyboard = []

    for fk in CUSTOM_FILTER_ORDER:
        finfo = CUSTOM_FILTERS[fk]
        val = getattr(us, finfo["field"], None)

        if finfo["type"] == "toggle":
            is_on = bool(val) if val is not None else False
            status = on if is_on else off
            lines.append(f"{finfo['emoji']} *{finfo['name']}* {status}")
            keyboard.append([
                InlineKeyboardButton(
                    f"{finfo['emoji']} {finfo['name']} {status}",
                    callback_data=f"sc_fd:{fk}",
                ),
            ])
        else:
            unit = finfo.get("unit", "")
            if val is not None:
                if isinstance(val, float) and val == int(val):
                    val_str = f"{int(val)}{unit}"
                else:
                    val_str = f"{val}{unit}"
            else:
                val_str = "—"
            lines.append(f"{finfo['emoji']} *{finfo['name']}* : *{val_str}*")
            keyboard.append([
                InlineKeyboardButton(
                    f"{finfo['emoji']} {finfo['name']} : {val_str}",
                    callback_data=f"sc_fd:{fk}",
                ),
            ])

    keyboard.append([InlineKeyboardButton("⬅️ Retour aux signaux", callback_data="sc_back")])

    text = "\n".join(lines)

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_custom_filter_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche le détail d'un filtre custom avec explication + réglages."""
    query = update.callback_query
    filter_key = query.data.replace("sc_fd:", "")

    finfo = CUSTOM_FILTERS.get(filter_key)
    if not finfo:
        await query.answer("❌ Filtre inconnu", show_alert=True)
        return

    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)

    val = getattr(us, finfo["field"], None)
    on = "✅"
    off = "❌"

    lines = [
        f"{finfo['emoji']} *{finfo['name'].upper()}*\n{SEP}\n",
        f"{finfo['description']}\n",
    ]

    keyboard = []

    if finfo["type"] == "toggle":
        is_on = bool(val) if val is not None else False
        lines.append(f"*État :* {on if is_on else off} {'Activé' if is_on else 'Désactivé'}")
        toggle_label = "❌ Désactiver" if is_on else "✅ Activer"
        keyboard.append([
            InlineKeyboardButton(toggle_label, callback_data=f"sc_ft:{filter_key}"),
        ])
    else:
        unit = finfo.get("unit", "")
        if val is not None:
            if isinstance(val, float) and val == int(val):
                val_str = f"{int(val)}{unit}"
            else:
                val_str = f"{val}{unit}"
        else:
            val_str = "—"
        lines.append(f"*Valeur actuelle :* {val_str}\n")
        lines.append("_Choisissez une nouvelle valeur :_")

        # Preset buttons in rows of 3
        presets = finfo.get("presets", [])
        preset_btns = []
        for label, pval in presets:
            marker = "✓ " if val is not None and abs(float(pval) - float(val)) < 0.01 else ""
            preset_btns.append(
                InlineKeyboardButton(
                    f"{marker}{label}",
                    callback_data=f"sc_fv:{filter_key}:{pval}",
                )
            )
        for i in range(0, len(preset_btns), 3):
            keyboard.append(preset_btns[i:i+3])

    keyboard.append([InlineKeyboardButton("⬅️ Retour aux filtres", callback_data="sc_filters")])

    text = "\n".join(lines)

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def toggle_custom_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle un filtre booléen ON/OFF."""
    query = update.callback_query
    filter_key = query.data.replace("sc_ft:", "")

    finfo = CUSTOM_FILTERS.get(filter_key)
    if not finfo or finfo["type"] != "toggle":
        await query.answer("❌ Filtre inconnu", show_alert=True)
        return

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        current = bool(getattr(us, finfo["field"], False))
        setattr(us, finfo["field"], not current)
        await session.commit()
        new_state = not current

    state_text = "activé" if new_state else "désactivé"
    await query.answer(f"✅ {finfo['name']} {state_text}", show_alert=False)

    # Refresh detail
    query.data = f"sc_fd:{filter_key}"
    await show_custom_filter_detail(update, context)


async def set_custom_filter_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the value of a custom filter."""
    query = update.callback_query
    parts = query.data.replace("sc_fv:", "").split(":", 1)
    if len(parts) != 2:
        await query.answer("❌ Format invalide", show_alert=True)
        return

    filter_key, raw_val = parts
    finfo = CUSTOM_FILTERS.get(filter_key)
    if not finfo:
        await query.answer("❌ Filtre inconnu", show_alert=True)
        return

    try:
        value = float(raw_val)
        if value == int(value):
            value = int(value)
    except ValueError:
        await query.answer("❌ Valeur invalide", show_alert=True)
        return

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        setattr(us, finfo["field"], value)
        await session.commit()

    unit = finfo.get("unit", "")
    await query.answer(f"✅ {finfo['name']} → {value}{unit}", show_alert=False)

    # Refresh detail
    query.data = f"sc_fd:{filter_key}"
    await show_custom_filter_detail(update, context)


async def scoring_back_to_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retour au menu Signaux du topic."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        await _show_signals_menu(update, user, us)
