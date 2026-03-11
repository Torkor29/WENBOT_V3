"""Platform fee service — 1% fee on every copytrade.

Fee flow:
1. Calculate fee on gross trade amount
2. Transfer fee USDC to FEES_WALLET on-chain
3. Only after confirmed transfer → execute the trade
4. Log everything in fee_records table (audit trail)
"""

import logging
from dataclasses import dataclass
from typing import Optional

from bot.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FeeResult:
    """Result of fee calculation."""
    gross_amount: float
    fee_rate: float
    fee_amount: float
    net_amount: float
    fees_wallet: str


class FeeCalculationError(Exception):
    """Raised when fee calculation fails validation."""
    pass


class FeeTransferError(Exception):
    """Raised when on-chain fee transfer fails."""
    pass


def calculate_fee(
    gross_amount_usdc: float,
    fee_rate: Optional[float] = None,
) -> FeeResult:
    """Calculate platform fee on a gross trade amount.

    Args:
        gross_amount_usdc: The total trade amount before fees.
        fee_rate: Override fee rate (default from config).

    Returns:
        FeeResult with fee breakdown.

    Raises:
        FeeCalculationError: If inputs are invalid.
    """
    rate = fee_rate if fee_rate is not None else settings.platform_fee_rate

    if gross_amount_usdc <= 0:
        raise FeeCalculationError(
            f"Gross amount must be positive, got {gross_amount_usdc}"
        )
    if not (0 <= rate <= 1):
        raise FeeCalculationError(
            f"Fee rate must be between 0 and 1, got {rate}"
        )
    if not settings.fees_wallet:
        raise FeeCalculationError("FEES_WALLET not configured")

    fee_amount = round(gross_amount_usdc * rate, 6)
    net_amount = round(gross_amount_usdc - fee_amount, 6)

    return FeeResult(
        gross_amount=gross_amount_usdc,
        fee_rate=rate,
        fee_amount=fee_amount,
        net_amount=net_amount,
        fees_wallet=settings.fees_wallet,
    )


async def transfer_fee_on_chain(
    fee_result: FeeResult,
    user_wallet: str,
    private_key: str,
) -> str:
    """Transfer platform fee USDC to FEES_WALLET on Polygon.

    This must succeed BEFORE the trade is executed.

    Args:
        fee_result: Calculated fee breakdown.
        user_wallet: Sender wallet address.
        private_key: Decrypted private key (in memory only).

    Returns:
        Transaction hash of the fee transfer.

    Raises:
        FeeTransferError: If transfer fails.
    """
    if fee_result.fee_amount <= 0:
        # Zero-fee edge case (rate = 0)
        return "no_fee"

    from bot.services.web3_client import polygon_client

    result = await polygon_client.transfer_usdc(
        from_address=user_wallet,
        to_address=fee_result.fees_wallet,
        amount_usdc=fee_result.fee_amount,
        private_key=private_key,
    )

    if not result.success:
        raise FeeTransferError(
            f"Fee transfer failed: {result.error}"
        )

    logger.info(
        f"Fee transferred: {fee_result.fee_amount} USDC → "
        f"{fee_result.fees_wallet[:10]}... tx: {result.tx_hash}"
    )
    return result.tx_hash


def format_fee_display(fee_result: FeeResult) -> str:
    """Format fee info for Telegram notification display."""
    return (
        f"💵 Mise brute     : {fee_result.gross_amount:.2f} USDC\n"
        f"💸 Frais ({fee_result.fee_rate:.0%})     : "
        f"-{fee_result.fee_amount:.2f} USDC\n"
        f"✅ Mise nette     : {fee_result.net_amount:.2f} USDC"
    )
