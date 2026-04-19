"""
Polymarket CLOB signer -- ephemeral clients for multi-wallet trading.

Based on the proven LiveExecutor (reference/live_executor.py).
Adapted for async multi-wallet (1 ClobClient per trade, destroyed after).

Endpoints:
  - https://clob.polymarket.com/book  -> orderbook (best ask / best bid)
  - https://clob.polymarket.com       -> post order (FOK / FAK)

Also contains web3-based ERC-20 and native MATIC transfers (unchanged).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from eth_account import Account
from web3 import Web3

from shared.config import (
    BUILDER_API_KEY,
    BUILDER_API_SECRET,
    BUILDER_API_PASSPHRASE,
    POLYGON_RPC_URL,
    POLYMARKET_CHAIN_ID,
    POLYMARKET_CLOB_HOST,
    USDC_CONTRACT,
    USDC_DECIMALS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal ERC-20 ABI for the transfer function
# ---------------------------------------------------------------------------
_USDC_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    }
]


def _get_w3() -> Web3:
    """Return a Web3 instance connected to Polygon."""
    return Web3(Web3.HTTPProvider(POLYGON_RPC_URL))


# ---------------------------------------------------------------------------
# Polymarket CLOB — ephemeral client
# ---------------------------------------------------------------------------

async def create_clob_client(private_key: str):
    """Create an ephemeral ClobClient for one wallet.

    signature_type=0 (EOA), chain_id=137 (Polygon).
    Derives API creds automatically.
    """
    from py_clob_client.client import ClobClient

    def _init():
        client = ClobClient(
            host=POLYMARKET_CLOB_HOST,
            chain_id=POLYMARKET_CHAIN_ID,
            key=private_key,
            signature_type=0,  # EOA wallet (not proxy/funder)
        )
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        return client

    return await asyncio.to_thread(_init)


async def get_best_ask(client, token_id: str) -> Optional[float]:
    """Get the best ask from the CLOB orderbook."""
    try:
        book = await asyncio.to_thread(client.get_order_book, token_id)
        asks = book.asks if hasattr(book, "asks") else []
        if asks:
            return min(float(a.price) for a in asks)
    except Exception:
        logger.exception("Failed to get best ask for token=%s", token_id[:20])
    return None


async def get_best_bid(client, token_id: str) -> Optional[float]:
    """Get the best bid from the CLOB orderbook."""
    try:
        book = await asyncio.to_thread(client.get_order_book, token_id)
        bids = book.bids if hasattr(book, "bids") else []
        if bids:
            return max(float(b.price) for b in bids)
    except Exception:
        logger.exception("Failed to get best bid for token=%s", token_id[:20])
    return None


async def approve_conditional_token(client, token_id: str) -> None:
    """Pre-approve the conditional token for trading."""
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        await asyncio.to_thread(
            client.update_balance_allowance,
            BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id),
        )
    except Exception:
        logger.debug("Conditional token approval failed (non-fatal) token=%s", token_id[:20])


# ---------------------------------------------------------------------------
# BUY order — exactly like the original LiveExecutor.buy()
# ---------------------------------------------------------------------------

async def place_buy_order(
    private_key: str,
    token_id: str,
    amount_usdc: float,
    max_price: float = 0.95,
) -> Dict[str, Any]:
    """Place a BUY market order on Polymarket CLOB.

    Flow (exactly like the original):
    1. Create ephemeral ClobClient
    2. Get best_ask from orderbook
    3. Guard: refuse if best_ask > max_price
    4. Pre-approve conditional token
    5. buy_price = min(best_ask + 0.05, 0.95)
    6. Try FOK first
    7. If FOK fails -> fallback FAK
    8. Return result dict
    """
    from py_clob_client.clob_types import MarketOrderArgs, OrderType

    client = await create_clob_client(private_key)

    try:
        # 1. Get best ask
        best_ask = await get_best_ask(client, token_id)

        # 2. Guard: refuse if best_ask > max_price
        if best_ask is not None and best_ask > max_price:
            logger.info(
                "BUY REJECTED: best_ask=%.4f > max_price=%.2f token=%s",
                best_ask, max_price, token_id[:20],
            )
            return {
                "success": False,
                "partial": False,
                "status": "REJECTED",
                "order_id": "",
                "shares": 0.0,
                "cost": 0.0,
                "entry_price": 0.0,
            }

        # 3. Pre-approve conditional token
        await approve_conditional_token(client, token_id)

        # 4. Calculate buy price
        buy_price = min(best_ask + 0.05, 0.95) if best_ask and best_ask > 0.01 else 0.95

        logger.info(
            "BUY %.2f$ | best_ask=%s | price=%.2f | token=%s",
            amount_usdc, best_ask, buy_price, token_id[:20],
        )

        # 5. FOK -> FAK fallback
        total_shares = 0.0
        total_cost = 0.0
        all_order_ids = []
        buy_status = "FAILED"

        for attempt, order_type in [(1, OrderType.FOK), (2, OrderType.FAK)]:
            try:
                order = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_usdc - total_cost,
                    side="BUY",
                    price=buy_price,
                )
                signed = await asyncio.to_thread(client.create_market_order, order)
                result = await asyncio.to_thread(client.post_order, signed, order_type)

                if result.get("success", False):
                    filled_shares = float(result.get("takingAmount", "0"))
                    filled_cost = float(result.get("makingAmount", "0"))
                    total_shares += filled_shares
                    total_cost += filled_cost
                    all_order_ids.append(result.get("orderID", ""))

                    if total_cost >= amount_usdc * 0.99:
                        buy_status = "FULL_SUCCESS"
                    else:
                        buy_status = "PARTIAL_SUCCESS"

                    type_name = "FOK" if attempt == 1 else "FAK"
                    logger.info(
                        "BUY %s OK: %.4f shares for %.2f$ | total=%.4f shares",
                        type_name, filled_shares, filled_cost, total_shares,
                    )
                    break
                else:
                    err = str(result.get("errorMsg", result))
                    if attempt == 1:
                        logger.info("BUY FOK failed: %s, trying FAK...", err[:80])
                        continue
                    else:
                        logger.warning("BUY FAK failed: %s", err[:80])
                        break

            except Exception as e:
                if attempt == 1:
                    logger.info("BUY FOK error: %s, trying FAK...", e)
                    continue
                else:
                    logger.warning("BUY FAK error: %s", e)
                    break

        order_id = ",".join(all_order_ids) if all_order_ids else ""
        entry_price = (total_cost / total_shares) if total_shares > 0 else 0.0

        if buy_status == "FAILED":
            logger.warning("BUY FAILED: 0 shares for token=%s", token_id[:20])
        elif buy_status == "PARTIAL_SUCCESS":
            logger.info(
                "BUY PARTIAL: %.4f shares for %.2f$ (requested %.2f$)",
                total_shares, total_cost, amount_usdc,
            )

        return {
            "success": buy_status == "FULL_SUCCESS",
            "partial": buy_status == "PARTIAL_SUCCESS",
            "status": buy_status,
            "order_id": order_id,
            "shares": total_shares,
            "cost": total_cost,
            "entry_price": entry_price,
        }

    except Exception as e:
        logger.exception("BUY ERROR for token=%s", token_id[:20])
        return {
            "success": False,
            "partial": False,
            "status": "FAILED",
            "order_id": "",
            "shares": 0.0,
            "cost": 0.0,
            "entry_price": 0.0,
        }


# ---------------------------------------------------------------------------
# SELL order — exactly like the original LiveExecutor.sell()
# ---------------------------------------------------------------------------

async def place_sell_order(
    private_key: str,
    token_id: str,
    shares: float,
) -> Dict[str, Any]:
    """Place a SELL market order on Polymarket CLOB.

    Flow (exactly like the original sell()):
    1. Create ephemeral ClobClient
    2. Approve conditional token
    3. Retry loop (max 12 attempts, 5s between):
       a. Check real share balance
       b. Get best_bid from orderbook
       c. sell_price = max(best_bid - 0.05, 0.01)
       d. FOK first attempt, FAK after
       e. If partial -> continue with remaining
       f. If fatal error (market closed/resolved) -> abort
    4. Return result dict
    """
    from py_clob_client.clob_types import MarketOrderArgs, OrderType

    if shares <= 0:
        return {
            "success": False,
            "partial": False,
            "status": "FAILED",
            "order_id": "",
            "sold": 0.0,
            "remaining": 0.0,
            "received": 0.0,
        }

    client = await create_clob_client(private_key)

    try:
        # Pre-approve conditional token
        await approve_conditional_token(client, token_id)

        max_attempts = 12
        remaining = shares
        total_received = 0.0
        all_order_ids = []
        sell_status = "FAILED"

        for attempt in range(max_attempts):
            if remaining < 0.001:
                break

            try:
                # 1. Check real share balance
                available = await _get_share_balance_with_client(client, token_id)

                if available is None:
                    logger.info(
                        "SELL %d/%d: balance=UNKNOWN (API error), retry in 5s...",
                        attempt + 1, max_attempts,
                    )
                    await asyncio.sleep(5)
                    continue

                if available <= 0:
                    logger.info(
                        "SELL %d/%d: balance=0 (not settled yet), retry in 5s...",
                        attempt + 1, max_attempts,
                    )
                    await asyncio.sleep(5)
                    continue

                # 2. Determine sell amount
                sell_amount = min(remaining, available)
                logger.info(
                    "SELL %d/%d: requested=%.4f available=%.4f selling=%.4f",
                    attempt + 1, max_attempts, remaining, available, sell_amount,
                )

                # 3. Refresh approval + price
                await approve_conditional_token(client, token_id)
                best_bid = await get_best_bid(client, token_id)
                sell_price = max(best_bid - 0.05, 0.01) if best_bid and best_bid > 0.01 else 0.01

                # 4. FOK first attempt, FAK after
                order_type = OrderType.FOK if attempt == 0 else OrderType.FAK
                order = MarketOrderArgs(
                    token_id=token_id,
                    amount=sell_amount,
                    side="SELL",
                    price=sell_price,
                )
                signed = await asyncio.to_thread(client.create_market_order, order)
                result = await asyncio.to_thread(client.post_order, signed, order_type)

                if result.get("success", False):
                    filled = float(result.get("takingAmount", sell_amount))
                    received = float(result.get("makingAmount", "0"))
                    total_received += received
                    remaining -= filled
                    all_order_ids.append(result.get("orderID", ""))
                    logger.info(
                        "SELL OK: sold %.4f shares, received %.2f$, remaining=%.4f",
                        filled, received, remaining,
                    )
                    if remaining < 0.001:
                        break
                    continue
                else:
                    err = str(result.get("errorMsg", result))
                    fatal_errors = ["does not exist", "not found", "resolved", "closed", "expired"]
                    if any(fe in err.lower() for fe in fatal_errors):
                        logger.warning("SELL ABORTED_FATAL: %s", err[:80])
                        sell_status = "ABORTED_FATAL"
                        break
                    logger.info(
                        "SELL %d/%d failed: %s, retry in 5s...",
                        attempt + 1, max_attempts, err[:60],
                    )
                    await asyncio.sleep(5)

            except Exception as e:
                err_str = str(e)
                fatal_errors = ["does not exist", "not found", "resolved", "closed", "expired"]
                if any(fe in err_str.lower() for fe in fatal_errors):
                    logger.warning("SELL ABORTED_FATAL: %s", err_str[:80])
                    sell_status = "ABORTED_FATAL"
                    break
                logger.info(
                    "SELL %d/%d error: %s, retry in 5s...",
                    attempt + 1, max_attempts, e,
                )
                await asyncio.sleep(5)

        # Final status
        order_id = ",".join(all_order_ids) if all_order_ids else ""

        if sell_status == "ABORTED_FATAL":
            logger.warning("SELL ABORTED_FATAL: market closed/resolved, %.4f shares unsellable", remaining)
        elif remaining < 0.001:
            sell_status = "FULL_SUCCESS"
            logger.info("SELL FULL_SUCCESS: %.4f shares -> %.2f$", shares, total_received)
        elif total_received > 0:
            sell_status = "PARTIAL_SUCCESS"
            logger.info(
                "SELL PARTIAL_SUCCESS: sold %.4f/%.4f shares -> %.2f$, remaining=%.4f",
                shares - remaining, shares, total_received, remaining,
            )
        else:
            sell_status = "FAILED"
            logger.warning("SELL FAILED: 0/%.4f shares sold after %d attempts", shares, max_attempts)

        return {
            "success": sell_status == "FULL_SUCCESS",
            "partial": sell_status == "PARTIAL_SUCCESS",
            "status": sell_status,
            "order_id": order_id,
            "sold": shares - remaining,
            "remaining": remaining,
            "received": total_received,
        }

    except Exception:
        logger.exception("SELL ERROR for token=%s", token_id[:20])
        return {
            "success": False,
            "partial": False,
            "status": "FAILED",
            "order_id": "",
            "sold": 0.0,
            "remaining": shares,
            "received": 0.0,
        }


# ---------------------------------------------------------------------------
# Share balance & CLOB balance
# ---------------------------------------------------------------------------

async def _get_share_balance_with_client(client, token_id: str) -> Optional[float]:
    """Get share balance using an existing client."""
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        bal = await asyncio.to_thread(
            client.get_balance_allowance,
            BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id),
        )
        raw = float(bal.get("balance", 0)) if isinstance(bal, dict) else None
        if raw is None:
            return None
        return raw / 1e6
    except Exception:
        return None


async def get_share_balance(private_key: str, token_id: str) -> Optional[float]:
    """Get share balance for a token for a given wallet."""
    client = await create_clob_client(private_key)
    return await _get_share_balance_with_client(client, token_id)


async def get_clob_balance(private_key: str) -> Optional[float]:
    """Get USDC collateral balance via the CLOB API."""
    client = await create_clob_client(private_key)
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        bal = await asyncio.to_thread(
            client.get_balance_allowance,
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL),
        )
        return float(bal.get("balance", 0)) if isinstance(bal, dict) else None
    except Exception:
        logger.exception("Failed to get CLOB balance")
        return None


# ---------------------------------------------------------------------------
# Redeem resolved winning positions
# ---------------------------------------------------------------------------

async def redeem_positions(private_key: str) -> Optional[list]:
    """Redeem all resolved winning positions for a wallet.

    Uses Builder API creds (global) + wallet private key (per user).
    """
    if not (BUILDER_API_KEY and BUILDER_API_SECRET and BUILDER_API_PASSPHRASE):
        logger.warning("Redeem skipped: missing BUILDER_API_KEY/SECRET/PASSPHRASE")
        return None

    try:
        from py_clob_client.client import ClobClient
        from py_builder_relayer_client.client import RelayClient
        from py_builder_signing_sdk.config import BuilderConfig
        from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
        from poly_web3 import PolyWeb3Service

        def _redeem():
            # Create CLOB client for this wallet
            client = ClobClient(
                host=POLYMARKET_CLOB_HOST,
                chain_id=POLYMARKET_CHAIN_ID,
                key=private_key,
                signature_type=0,
            )
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)

            # Builder relay client
            builder_creds = BuilderApiKeyCreds(
                key=BUILDER_API_KEY,
                secret=BUILDER_API_SECRET,
                passphrase=BUILDER_API_PASSPHRASE,
            )
            builder_cfg = BuilderConfig(local_builder_creds=builder_creds)
            relay_client = RelayClient(
                relayer_url="https://relayer-v2.polymarket.com/",
                chain_id=POLYMARKET_CHAIN_ID,
                private_key=private_key,
                builder_config=builder_cfg,
            )

            rpc = os.environ.get("ALCHEMY_RPC_URL", "https://polygon-rpc.com")
            service = PolyWeb3Service(
                clob_client=client,
                relayer_client=relay_client,
                rpc_url=rpc,
            )
            return service.redeem_all(batch_size=10)

        results = await asyncio.to_thread(_redeem)
        if results:
            logger.info("REDEEM OK: %d positions redeemed", len(results))
        return results

    except Exception:
        logger.exception("REDEEM ERROR")
        return None


# ---------------------------------------------------------------------------
# Web3-based transfers (unchanged from original signer.py)
# ---------------------------------------------------------------------------

def send_usdc_transfer(
    private_key: str,
    to_address: str,
    amount_usdc: float,
) -> str:
    """Send USDC.e on Polygon via an ERC-20 transfer."""
    w3 = _get_w3()
    account = Account.from_key(private_key)
    sender = account.address

    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT),
        abi=_USDC_TRANSFER_ABI,
    )

    amount_raw = int(amount_usdc * (10**USDC_DECIMALS))

    nonce = w3.eth.get_transaction_count(sender)
    gas_price = w3.eth.gas_price

    tx = usdc.functions.transfer(
        Web3.to_checksum_address(to_address),
        amount_raw,
    ).build_transaction(
        {
            "chainId": POLYMARKET_CHAIN_ID,
            "from": sender,
            "nonce": nonce,
            "gasPrice": gas_price,
        }
    )

    signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    hex_hash = tx_hash.hex()

    logger.info("USDC transfer sent: to=%s amount=%s tx=%s", to_address, amount_usdc, hex_hash)
    return hex_hash


def send_matic_transfer(
    private_key: str,
    to_address: str,
    amount_matic: float,
) -> str:
    """Send native MATIC/POL on Polygon."""
    w3 = _get_w3()
    account = Account.from_key(private_key)
    sender = account.address

    nonce = w3.eth.get_transaction_count(sender)
    gas_price = w3.eth.gas_price

    tx = {
        "chainId": POLYMARKET_CHAIN_ID,
        "from": sender,
        "to": Web3.to_checksum_address(to_address),
        "value": w3.to_wei(amount_matic, "ether"),
        "nonce": nonce,
        "gas": 21_000,
        "gasPrice": gas_price,
    }

    signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    hex_hash = tx_hash.hex()

    logger.info("MATIC transfer sent: to=%s amount=%s tx=%s", to_address, amount_matic, hex_hash)
    return hex_hash
