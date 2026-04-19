"""EOA wallet creation on Polygon using eth_account."""

from __future__ import annotations

from eth_account import Account


def create_wallet() -> tuple[str, str]:
    """Generate a new EOA wallet.

    Returns:
        A tuple of ``(wallet_address, private_key)`` where the private key
        is a hex string starting with ``0x``.
    """
    account = Account.create()
    wallet_address: str = account.address
    private_key: str = account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    return wallet_address, private_key
