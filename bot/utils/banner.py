"""Banner helper — sends messages with the WENPOLYMARKET banner image."""

import logging
from pathlib import Path

from telegram import InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes

from bot.config import settings

logger = logging.getLogger(__name__)

# Local banner file (inside the repo, shipped with Docker)
_BANNER_PATH = Path(__file__).resolve().parent.parent.parent / "branding" / "banner.png"

# Cache the Telegram file_id after first upload to avoid re-uploading every time
_cached_file_id: str | None = None


def _get_banner_source() -> str | None:
    """Return the best available banner source: cached file_id > URL > local file."""
    global _cached_file_id
    if _cached_file_id:
        return _cached_file_id
    if settings.welcome_banner_url:
        return settings.welcome_banner_url
    if _BANNER_PATH.exists():
        return str(_BANNER_PATH)
    return None


async def send_with_banner(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "Markdown",
) -> Message:
    """Send a message with the banner image (photo + caption).

    Falls back to plain text if no banner is available or if sending fails.
    """
    global _cached_file_id
    source = _get_banner_source()

    if source:
        try:
            # If source is a local file path, open it
            if source.startswith("/") or source.startswith("C:") or (
                not source.startswith("http") and not source.startswith("AgAC")
            ):
                photo_input = open(source, "rb")
            else:
                photo_input = source

            sent = await message.reply_photo(
                photo=photo_input,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )

            # Cache the file_id for future sends (avoids re-uploading)
            if sent.photo and not _cached_file_id:
                _cached_file_id = sent.photo[-1].file_id
                logger.info("Banner file_id cached: %s", _cached_file_id[:20])

            return sent
        except Exception:
            logger.warning("Failed to send banner photo, falling back to text", exc_info=True)

    # Fallback: plain text
    return await message.reply_text(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
