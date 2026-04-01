"""TopicRouter — routes bot messages to the correct Telegram Forum Group topic.

Supports 7 topics: Signals, Traders, Portfolio, Alerts, Admin, Strategies, Perf Strategies.

Multi-tenant architecture:
- Each subscriber can have their own Forum Group (linked via GroupConfig.user_id).
- TopicRouter.for_user(user_id, bot) returns a per-user router loaded from DB.
- A class-level LRU cache avoids repeated DB lookups.
- The global instance (used in main.py) is Julie's admin router (env config or
  first setup group found in DB).

Configuration priority for the global instance:
1. Database (GroupConfig without user_id / first row) — auto-setup
2. Environment variables (.env) — manual config
3. Disabled — DM-only fallback
"""

import logging
from typing import Optional

from telegram import Bot, Message, InlineKeyboardMarkup

from bot.config import settings

logger = logging.getLogger(__name__)


class TopicRouter:
    """Routes messages to Telegram Forum Group topics or DMs."""

    # ── Class-level per-user cache ────────────────────────────────
    # user_id → TopicRouter instance (populated lazily)
    _user_cache: dict[int, Optional["TopicRouter"]] = {}

    def __init__(self, bot: Bot):
        self._bot = bot
        self._group_id: Optional[int] = None
        self._topics: dict[str, Optional[int]] = {
            "signals": None,
            "traders": None,
            "portfolio": None,
            "alerts": None,
            "admin": None,
            "strategies": None,
            "strategies_perf": None,
        }
        self._enabled = False

        # Try loading from .env first (backward compat)
        if settings.group_chat_id:
            try:
                self._group_id = int(settings.group_chat_id)
                self._topics = {
                    "signals": settings.topic_signals_id or None,
                    "traders": settings.topic_traders_id or None,
                    "portfolio": settings.topic_portfolio_id or None,
                    "alerts": settings.topic_alerts_id or None,
                    "admin": settings.topic_admin_id or None,
                    "strategies": None,
                    "strategies_perf": None,
                }
                self._enabled = bool(any(self._topics.values()))
            except (ValueError, TypeError):
                pass

        if self._enabled:
            logger.info(
                "TopicRouter enabled from .env — group=%s topics=%s",
                self._group_id,
                {k: v for k, v in self._topics.items() if v},
            )
        else:
            logger.info(
                "TopicRouter not configured from .env — "
                "will try DB on first use or after auto-setup"
            )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ── Per-user factory ──────────────────────────────────────────

    @classmethod
    async def for_user(cls, user_id: int, bot: Bot) -> Optional["TopicRouter"]:
        """Return a TopicRouter configured for a specific subscriber's group.

        Loads GroupConfig from DB, caches the result.
        Returns None if the user hasn't set up a group yet.
        """
        # Use sentinel None to remember "no group for this user" (avoids repeat DB hits)
        if user_id in cls._user_cache:
            return cls._user_cache[user_id]

        try:
            from bot.db.session import async_session
            from bot.models.group_config import GroupConfig
            from sqlalchemy import select

            async with async_session() as session:
                config = (
                    await session.execute(
                        select(GroupConfig).where(
                            GroupConfig.user_id == user_id,
                            GroupConfig.setup_complete == True,  # noqa: E712
                            GroupConfig.is_active == True,  # noqa: E712
                        )
                    )
                ).scalar_one_or_none()

            if not config:
                cls._user_cache[user_id] = None  # cache "no group" result
                return None

            router = cls._make_from_config(config, bot)
            cls._user_cache[user_id] = router
            logger.debug(
                "TopicRouter loaded for user=%d group=%s",
                user_id, config.group_id,
            )
            return router

        except Exception as e:
            logger.debug("TopicRouter.for_user failed for user=%d: %s", user_id, e)
            return None

    @classmethod
    def evict_user(cls, user_id: int) -> None:
        """Invalidate cached router for a user (call after group (re)setup)."""
        cls._user_cache.pop(user_id, None)
        logger.debug("TopicRouter cache evicted for user=%d", user_id)

    @classmethod
    def _make_from_config(cls, config, bot: Bot) -> "TopicRouter":
        """Build a TopicRouter from a GroupConfig ORM row (no __init__ side-effects)."""
        router = cls.__new__(cls)
        router._bot = bot
        router._group_id = config.group_id
        router._topics = config.topics_dict
        router._enabled = True
        return router

    # ── Global instance helpers ───────────────────────────────────

    async def try_load_from_db(self) -> bool:
        """Try to load the global group config from the database.

        Called at startup and after auto-setup for the admin/global group.
        Returns True if config was loaded.
        """
        try:
            from bot.db.session import async_session
            from bot.models.group_config import GroupConfig
            from sqlalchemy import select

            async with async_session() as session:
                # Prefer rows without a specific owner (global admin group),
                # then fall back to any complete group.
                config = (
                    await session.execute(
                        select(GroupConfig)
                        .where(GroupConfig.is_active == True)  # noqa: E712
                        .where(GroupConfig.setup_complete == True)  # noqa: E712
                        .order_by(GroupConfig.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()

                if not config:
                    return False

                self._group_id = config.group_id
                self._topics = config.topics_dict
                self._enabled = True

                logger.info(
                    "TopicRouter (global) loaded from DB: group=%s topics=%s",
                    config.group_id,
                    {k: v for k, v in config.topics_dict.items() if v},
                )
                return True

        except Exception as e:
            logger.debug("TopicRouter DB load failed: %s", e)
            return False

    # ── Internal send ─────────────────────────────────────────────

    async def _send_to_topic(
        self,
        topic_key: str,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> Optional[Message]:
        """Send a message to a specific topic in the group."""
        # Lazy-load from DB if not yet enabled
        if not self._enabled:
            await self.try_load_from_db()
            if not self._enabled:
                return None

        topic_id = self._topics.get(topic_key)
        if not topic_id:
            logger.debug("Topic '%s' not configured, skipping", topic_key)
            return None

        try:
            return await self._bot.send_message(
                chat_id=self._group_id,
                message_thread_id=topic_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error("Failed to send to topic '%s': %s", topic_key, e)
            return None

    # ── Topic-specific methods ────────────────────────────────────

    async def send_signal(
        self, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> Optional[Message]:
        """Post a scored signal to the 📊 Signals topic."""
        return await self._send_to_topic("signals", text, reply_markup=reply_markup)

    async def send_trader_report(self, text: str) -> Optional[Message]:
        """Post trader analytics to the 👤 Traders topic."""
        return await self._send_to_topic("traders", text)

    async def send_portfolio(self, text: str) -> Optional[Message]:
        """Post portfolio overview to the 💼 Portfolio topic."""
        return await self._send_to_topic("portfolio", text)

    async def send_alert(self, text: str) -> Optional[Message]:
        """Post critical alert to the 🚨 Alerts topic."""
        return await self._send_to_topic("alerts", text)

    async def send_admin(self, text: str) -> Optional[Message]:
        """Post system info to the ⚙️ Admin topic."""
        return await self._send_to_topic("admin", text)

    async def send_strategy_signal(
        self, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> Optional[Message]:
        """Post strategy signal/execution to the 📊 Strategies topic."""
        return await self._send_to_topic("strategies", text, reply_markup=reply_markup)

    async def send_strategy_perf(self, text: str) -> Optional[Message]:
        """Post strategy performance/resolution to the 📈 Perf Strategies topic."""
        return await self._send_to_topic("strategies_perf", text)

    # ── Smart routing (DM + Group based on user preference) ───────

    async def notify_user(
        self,
        user_telegram_id: int,
        text: str,
        notification_mode: str = "dm",
        topic: str = "signals",
        parse_mode: str = "Markdown",
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> list[Message]:
        """Send notification respecting user's notification_mode preference.

        Args:
            user_telegram_id: User's Telegram ID for DM
            text: Message text
            notification_mode: "dm" | "group" | "both"
            topic: Which topic to post in if sending to group
            parse_mode: Telegram parse mode
            reply_markup: Optional inline keyboard

        Returns:
            List of Message objects sent
        """
        sent: list[Message] = []

        # DM
        if notification_mode in ("dm", "both"):
            try:
                msg = await self._bot.send_message(
                    chat_id=user_telegram_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                sent.append(msg)
            except Exception as e:
                logger.error("Failed to DM user %s: %s", user_telegram_id, e)

        # Group topic
        if notification_mode in ("group", "both"):
            msg = await self._send_to_topic(topic, text, parse_mode, reply_markup)
            if msg:
                sent.append(msg)

        return sent
