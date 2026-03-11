"""Web3 client for Polygon — USDC transfers and wallet operations."""

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# USDC on Polygon
USDC_POLYGON_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC
USDC_POLYGON_DECIMALS = 6

# Standard ERC-20 ABI (transfer + balanceOf only)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

# Polygon RPC endpoints (public, fallback list)
POLYGON_RPC_URLS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon-mainnet.g.alchemy.com/v2/demo",
]


@dataclass
class TransferResult:
    success: bool
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    gas_used: int = 0


def usdc_to_wei(amount: float) -> int:
    """Convert USDC amount (float) to smallest unit (6 decimals)."""
    return int(amount * 10**USDC_POLYGON_DECIMALS)


def wei_to_usdc(amount_wei: int) -> float:
    """Convert smallest unit back to USDC float."""
    return amount_wei / 10**USDC_POLYGON_DECIMALS


class PolygonClient:
    """Web3 client for Polygon network operations."""

    def __init__(self, rpc_url: Optional[str] = None):
        self._rpc_url = rpc_url or POLYGON_RPC_URLS[0]
        self._w3 = None
        self._usdc_contract = None

    def _get_web3(self):
        """Lazy-init Web3 connection."""
        if self._w3 is None:
            from web3 import Web3
            self._w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            self._usdc_contract = self._w3.eth.contract(
                address=Web3.to_checksum_address(USDC_POLYGON_ADDRESS),
                abi=ERC20_ABI,
            )
        return self._w3

    async def get_usdc_balance(self, wallet_address: str) -> float:
        """Get USDC balance for a wallet on Polygon."""
        try:
            w3 = self._get_web3()
            balance_wei = self._usdc_contract.functions.balanceOf(
                w3.to_checksum_address(wallet_address)
            ).call()
            return wei_to_usdc(balance_wei)
        except Exception as e:
            logger.error(f"Failed to get USDC balance for {wallet_address[:10]}...: {e}")
            return 0.0

    async def get_matic_balance(self, wallet_address: str) -> float:
        """Get MATIC (POL) balance for gas fees."""
        try:
            w3 = self._get_web3()
            balance = w3.eth.get_balance(w3.to_checksum_address(wallet_address))
            return w3.from_wei(balance, "ether")
        except Exception as e:
            logger.error(f"Failed to get MATIC balance: {e}")
            return 0.0

    async def transfer_usdc(
        self,
        from_address: str,
        to_address: str,
        amount_usdc: float,
        private_key: str,
    ) -> TransferResult:
        """Transfer USDC on Polygon from one address to another.

        Args:
            from_address: Sender wallet address.
            to_address: Recipient wallet address.
            amount_usdc: Amount in USDC.
            private_key: Sender's decrypted private key.

        Returns:
            TransferResult with tx_hash on success.
        """
        try:
            w3 = self._get_web3()
            from_addr = w3.to_checksum_address(from_address)
            to_addr = w3.to_checksum_address(to_address)
            amount_wei = usdc_to_wei(amount_usdc)

            # Build ERC-20 transfer transaction
            nonce = w3.eth.get_transaction_count(from_addr)

            tx = self._usdc_contract.functions.transfer(
                to_addr, amount_wei
            ).build_transaction({
                "from": from_addr,
                "nonce": nonce,
                "gas": 100_000,
                "maxFeePerGas": w3.eth.gas_price * 2,
                "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
                "chainId": 137,  # Polygon mainnet
            })

            # Sign and send
            signed = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            # Wait for confirmation
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                logger.info(
                    f"USDC transfer successful: {amount_usdc} USDC "
                    f"from {from_address[:10]}... to {to_address[:10]}... "
                    f"tx: {tx_hash_hex}"
                )
                return TransferResult(
                    success=True,
                    tx_hash=tx_hash_hex,
                    gas_used=receipt["gasUsed"],
                )
            else:
                return TransferResult(
                    success=False,
                    tx_hash=tx_hash_hex,
                    error="Transaction reverted on-chain",
                )

        except Exception as e:
            logger.error(f"USDC transfer failed: {e}")
            return TransferResult(success=False, error=str(e))


# Singleton
polygon_client = PolygonClient()
