"""Input validation and sanitization utilities.

All user inputs are validated before processing to prevent injection attacks.
"""

import re
from typing import Optional


# Patterns
ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
MARKET_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def validate_eth_address(address: str) -> tuple[bool, str]:
    """Validate an Ethereum/Polygon wallet address."""
    address = address.strip()
    if not address:
        return False, "Adresse vide"
    if not ETH_ADDRESS_RE.match(address):
        return False, "Adresse invalide — doit commencer par 0x suivi de 40 caractères hex"
    return True, ""


def validate_solana_address(address: str) -> tuple[bool, str]:
    """Validate a Solana wallet address (Base58)."""
    address = address.strip()
    if not address:
        return False, "Adresse vide"
    if not SOLANA_ADDRESS_RE.match(address):
        return False, "Adresse Solana invalide (Base58 attendu)"
    return True, ""


def validate_amount(
    value: str,
    min_val: float = 0.0,
    max_val: float = 1_000_000.0,
) -> tuple[bool, Optional[float], str]:
    """Validate and parse a numeric amount.

    Returns:
        (valid, parsed_value, error_message)
    """
    try:
        amount = float(value.strip())
    except (ValueError, AttributeError):
        return False, None, "Valeur numérique invalide"

    if amount <= min_val:
        return False, None, f"Le montant doit être supérieur à {min_val}"
    if amount > max_val:
        return False, None, f"Le montant ne doit pas dépasser {max_val}"

    return True, amount, ""


def sanitize_text(text: str, max_length: int = 500) -> str:
    """Sanitize user text input — strip HTML/Markdown injection."""
    if not text:
        return ""
    # Remove potential Markdown/HTML injection
    sanitized = text.strip()
    # Remove common injection characters
    sanitized = sanitized.replace("<", "&lt;").replace(">", "&gt;")
    # Truncate
    return sanitized[:max_length]


def validate_private_key(key: str) -> tuple[bool, str]:
    """Basic validation of a private key format (not content)."""
    key = key.strip()
    if not key:
        return False, "Clé privée vide"
    if len(key) < 32:
        return False, "Clé privée trop courte (minimum 32 caractères)"
    if len(key) > 256:
        return False, "Clé privée trop longue"
    return True, ""


def validate_fee_rate(rate: float) -> tuple[bool, str]:
    """Validate a fee rate value."""
    if not isinstance(rate, (int, float)):
        return False, "Le taux doit être un nombre"
    if rate < 0 or rate > 0.1:
        return False, "Le taux doit être entre 0% et 10%"
    return True, ""
