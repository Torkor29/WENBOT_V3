"""Wallet balance queries for USDC.e and MATIC on Polygon."""

from __future__ import annotations

from web3 import Web3

from shared.config import POLYGON_RPC_URL, USDC_CONTRACT, USDC_DECIMALS

# Minimal ERC-20 ABI for balanceOf
_USDC_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


def _get_w3() -> Web3:
    """Return a Web3 instance connected to Polygon."""
    return Web3(Web3.HTTPProvider(POLYGON_RPC_URL))


def get_usdc_balance(wallet_address: str) -> float:
    """Return the USDC.e balance for *wallet_address* in human-readable units.

    Args:
        wallet_address: Polygon wallet address (checksummed or not).

    Returns:
        Balance as a float (e.g. ``12.5`` for 12.5 USDC).
    """
    w3 = _get_w3()
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT),
        abi=_USDC_BALANCE_ABI,
    )
    raw_balance: int = usdc.functions.balanceOf(
        Web3.to_checksum_address(wallet_address)
    ).call()
    return raw_balance / (10**USDC_DECIMALS)


def get_matic_balance(wallet_address: str) -> float:
    """Return the native MATIC/POL balance for *wallet_address*.

    Args:
        wallet_address: Polygon wallet address (checksummed or not).

    Returns:
        Balance as a float in MATIC (e.g. ``0.15``).
    """
    w3 = _get_w3()
    raw_balance = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
    return float(w3.from_wei(raw_balance, "ether"))
