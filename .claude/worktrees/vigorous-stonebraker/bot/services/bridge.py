"""Bridge service — SOL → USDC Polygon via Li.Fi and Across Protocol."""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

LIFI_API_BASE = "https://li.quest/v1"
ACROSS_API_BASE = settings.across_api_url

# Chain IDs
SOLANA_CHAIN_ID = 1151111081099710  # Li.Fi Solana chain ID
POLYGON_CHAIN_ID = 137

# Token addresses
SOL_NATIVE = "0x0000000000000000000000000000000000000000"
USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"


class BridgeProvider(str, Enum):
    LIFI = "lifi"
    ACROSS = "across"


class BridgeStatus(str, Enum):
    QUOTING = "quoting"
    PENDING = "pending"
    BRIDGING = "bridging"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BridgeQuote:
    provider: BridgeProvider
    input_amount: float  # SOL
    output_amount: float  # USDC
    fee_usd: float
    estimated_time_seconds: int
    route_data: dict = field(default_factory=dict)


@dataclass
class BridgeResult:
    success: bool
    provider: Optional[BridgeProvider] = None
    input_amount: float = 0.0
    output_amount: float = 0.0
    fee_usd: float = 0.0
    tx_hash: Optional[str] = None
    status: BridgeStatus = BridgeStatus.PENDING
    error: Optional[str] = None


async def get_lifi_quote(
    amount_sol: float,
    from_wallet: str,
    to_wallet: str,
) -> Optional[BridgeQuote]:
    """Get a bridge quote from Li.Fi for SOL → USDC Polygon."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Convert SOL to lamports (9 decimals)
            amount_lamports = str(int(amount_sol * 10**9))

            params = {
                "fromChain": str(SOLANA_CHAIN_ID),
                "toChain": str(POLYGON_CHAIN_ID),
                "fromToken": SOL_NATIVE,
                "toToken": USDC_POLYGON,
                "fromAmount": amount_lamports,
                "fromAddress": from_wallet,
                "toAddress": to_wallet,
                "slippage": str(settings.bridge_slippage),
            }

            headers = {}
            if settings.lifi_api_key:
                headers["x-lifi-api-key"] = settings.lifi_api_key

            resp = await client.get(
                f"{LIFI_API_BASE}/quote",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            estimate = data.get("estimate", {})
            output_amount = float(estimate.get("toAmount", 0)) / 10**6
            fee_costs = estimate.get("feeCosts", [])
            total_fee = sum(
                float(f.get("amountUSD", 0)) for f in fee_costs
            )

            return BridgeQuote(
                provider=BridgeProvider.LIFI,
                input_amount=amount_sol,
                output_amount=output_amount,
                fee_usd=total_fee,
                estimated_time_seconds=int(
                    estimate.get("executionDuration", 300)
                ),
                route_data=data,
            )

    except httpx.HTTPStatusError as e:
        logger.warning(f"Li.Fi quote failed (HTTP {e.response.status_code}): {e}")
        return None
    except Exception as e:
        logger.warning(f"Li.Fi quote failed: {e}")
        return None


async def get_across_quote(
    amount_sol: float,
    from_wallet: str,
    to_wallet: str,
) -> Optional[BridgeQuote]:
    """Get a bridge quote from Across Protocol for SOL → USDC Polygon."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            params = {
                "originChainId": 1,  # Across uses different chain IDs
                "destinationChainId": POLYGON_CHAIN_ID,
                "amount": str(int(amount_sol * 10**9)),
                "token": SOL_NATIVE,
                "recipient": to_wallet,
            }

            resp = await client.get(
                f"{ACROSS_API_BASE}/suggested-fees",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            # Across returns fee info differently
            relay_fee_pct = float(data.get("relayFeePct", 0)) / 10**18
            fee_usd = amount_sol * relay_fee_pct * 150  # Rough SOL price estimate

            return BridgeQuote(
                provider=BridgeProvider.ACROSS,
                input_amount=amount_sol,
                output_amount=amount_sol * 150 * (1 - relay_fee_pct),  # Rough
                fee_usd=fee_usd,
                estimated_time_seconds=180,
                route_data=data,
            )

    except Exception as e:
        logger.warning(f"Across quote failed: {e}")
        return None


async def get_best_quote(
    amount_sol: float,
    from_wallet: str,
    to_wallet: str,
) -> Optional[BridgeQuote]:
    """Compare quotes from all providers and return the best one."""
    quotes = []

    # Fetch quotes in parallel
    import asyncio
    results = await asyncio.gather(
        get_lifi_quote(amount_sol, from_wallet, to_wallet),
        get_across_quote(amount_sol, from_wallet, to_wallet),
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, BridgeQuote):
            quotes.append(result)

    if not quotes:
        return None

    # Best = highest output amount (lowest fees)
    return max(quotes, key=lambda q: q.output_amount)


async def execute_bridge(
    quote: BridgeQuote,
    private_key: str,
) -> BridgeResult:
    """Execute a bridge transaction using the selected quote.

    Currently supports Li.Fi execution. Across requires different flow.
    """
    if quote.provider == BridgeProvider.LIFI:
        return await _execute_lifi_bridge(quote, private_key)
    else:
        return BridgeResult(
            success=False,
            error=f"Bridge execution not implemented for {quote.provider.value}",
            status=BridgeStatus.FAILED,
        )


async def _execute_lifi_bridge(
    quote: BridgeQuote,
    private_key: str,
) -> BridgeResult:
    """Execute bridge via Li.Fi — sign and submit the transaction."""
    try:
        route_data = quote.route_data
        tx_data = route_data.get("transactionRequest", {})

        if not tx_data:
            return BridgeResult(
                success=False,
                error="No transaction data in Li.Fi quote",
                status=BridgeStatus.FAILED,
            )

        # TODO: Sign with Solana private key and submit
        # For now, return a pending result
        # In production:
        # 1. Sign tx_data with solana-py
        # 2. Submit to Solana RPC
        # 3. Monitor Li.Fi status endpoint
        # 4. Wait for USDC arrival on Polygon

        return BridgeResult(
            success=False,
            provider=quote.provider,
            input_amount=quote.input_amount,
            output_amount=quote.output_amount,
            fee_usd=quote.fee_usd,
            error="Bridge execution pending implementation — use get_best_quote() for quotes",
            status=BridgeStatus.PENDING,
        )

    except Exception as e:
        logger.error(f"Li.Fi bridge execution failed: {e}")
        return BridgeResult(
            success=False,
            error=str(e),
            status=BridgeStatus.FAILED,
        )


async def check_bridge_status(
    provider: BridgeProvider,
    tx_hash: str,
) -> BridgeStatus:
    """Check the status of a pending bridge transaction."""
    if provider == BridgeProvider.LIFI:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LIFI_API_BASE}/status",
                    params={"txHash": tx_hash},
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "").upper()

                if status == "DONE":
                    return BridgeStatus.COMPLETED
                elif status == "FAILED":
                    return BridgeStatus.FAILED
                else:
                    return BridgeStatus.BRIDGING
        except Exception:
            return BridgeStatus.PENDING

    return BridgeStatus.PENDING
