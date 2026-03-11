"""Position sizing engine — calculates trade amounts for followers."""

from bot.models.settings import SizingMode, UserSettings


class SizingError(Exception):
    pass


def calculate_trade_size(
    user_settings: UserSettings,
    master_amount_usdc: float,
    master_portfolio_usdc: float,
    current_balance_usdc: float,
) -> float:
    """Calculate the follower's trade size based on their sizing mode.

    Args:
        user_settings: The follower's settings.
        master_amount_usdc: How much the master traded.
        master_portfolio_usdc: Master's total portfolio value.
        current_balance_usdc: Follower's current available balance.

    Returns:
        Trade amount in USDC (before fees).

    Raises:
        SizingError: If calculation produces an invalid result.
    """
    mode = user_settings.sizing_mode
    multiplier = user_settings.multiplier

    if mode == SizingMode.FIXED:
        raw_amount = user_settings.fixed_amount

    elif mode == SizingMode.PERCENT:
        raw_amount = user_settings.allocated_capital * (
            user_settings.percent_per_trade / 100.0
        )

    elif mode == SizingMode.PROPORTIONAL:
        if master_portfolio_usdc <= 0:
            raise SizingError("Master portfolio value must be positive")
        ratio = master_amount_usdc / master_portfolio_usdc
        raw_amount = user_settings.allocated_capital * ratio

    elif mode == SizingMode.KELLY:
        # Simplified Kelly: uses same logic as percent for now
        # Full Kelly criterion requires win rate & odds ratio
        raw_amount = user_settings.allocated_capital * (
            user_settings.percent_per_trade / 100.0
        )

    else:
        raise SizingError(f"Unknown sizing mode: {mode}")

    # Apply multiplier
    amount = raw_amount * multiplier

    # Enforce min/max constraints
    amount = max(amount, user_settings.min_trade_usdc)
    amount = min(amount, user_settings.max_trade_usdc)

    # Don't exceed available balance
    amount = min(amount, current_balance_usdc)

    if amount <= 0:
        raise SizingError("Calculated trade size is zero or negative")

    return round(amount, 6)
