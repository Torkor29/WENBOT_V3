"""Multi-master activity monitor — watches all followed wallets for trade signals.

Design (2026-04 refactor):

- Primary detection = Polymarket Data API `/activity` endpoint, polled per
  wallet every `poll_interval` seconds. Each trade is a distinct row with a
  tx_hash, so BUY+SELL sequences on fast markets (BTC 5min scalping) no
  longer get swallowed by a position diff that only sees the net state.
- Positions snapshot is still kept in-memory, refreshed lazily on every
  poll cycle that yields new activity, so we can compute a SELL's
  `sell_ratio` = size_sold / position_before_sell = size_sold / (current + size_sold).
- Dedup by tx_hash with a bounded set to avoid re-emitting a signal we
  already processed in a previous poll cycle.

Fallback position-diff detection remains available via `_check_wallet_diff`
but is not wired in the default loop.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from bot.services.polymarket import polymarket_client, Position, Activity

logger = logging.getLogger(__name__)

# Filtre dust technique uniquement — ignore les micro-trades
# < 0.01 share dus à l'imprécision des floats côté API Polymarket.
# 0.01 share @ $0.30 = $0.003, soit techniquement rien.
# NE PAS utiliser pour filtrer la qualité — c'est le rôle du setting user
# `min_master_share_size` (défaut 0 = OFF, configurable dans la mini-app).
MIN_SIGNAL_SIZE = 0.01

# Profondeur de l'historique de tx_hash déjà vus, par wallet. Au-delà de ça,
# les hashs les plus anciens sont évincés. 1000 couvre ~plusieurs heures
# d'un trader très actif.
_TX_HASH_HISTORY = 1000

# Fenêtre (secondes) en arrière utilisée lors du premier snapshot d'un wallet
# pour rattraper les trades arrivés entre "ajout du wallet" et "poll suivant"
# sans re-copier un historique ancien que l'utilisateur n'a jamais voulu.
_INITIAL_LOOKBACK_S = 60


@dataclass
class TradeSignal:
    """A trade detected from a followed master trader.

    For SELL signals, `sell_ratio` indicates what fraction of the master's
    position was sold (0.0-1.0). Followers should apply the same ratio to
    their own position size.
    """
    master_wallet: str
    market_id: str
    token_id: str
    outcome: str
    side: str  # "BUY" or "SELL"
    size: float  # shares (delta for partial, total for full close)
    price: float
    master_pnl_pct: float = 0.0
    market_question: str = ""
    sell_ratio: float = 1.0  # 0.0-1.0, only meaningful for SELL signals


@dataclass
class WalletState:
    """Tracks a single wallet's activity cursor + recent tx hashes.

    `positions` is still kept as a best-effort cache so the consensus scorer
    and any UI can read it, but it's no longer the source of truth for
    signal emission.
    """
    positions: dict[str, Position] = field(default_factory=dict)
    initialized: bool = False
    # Plus récent timestamp d'activité (secondes) déjà vu pour ce wallet.
    last_activity_ts: int = 0
    # Hashs de tx déjà émis en signal (dedup cross-poll). deque pour FIFO
    # bornée, set associé pour lookup O(1).
    seen_tx_hashes: deque = field(
        default_factory=lambda: deque(maxlen=_TX_HASH_HISTORY)
    )
    seen_tx_set: set = field(default_factory=set)

    def mark_seen(self, tx_hash: str) -> None:
        """Add a tx_hash to the dedup history, evicting the oldest if full."""
        if not tx_hash:
            return
        if tx_hash in self.seen_tx_set:
            return
        if len(self.seen_tx_hashes) == self.seen_tx_hashes.maxlen:
            oldest = self.seen_tx_hashes[0]
            self.seen_tx_set.discard(oldest)
        self.seen_tx_hashes.append(tx_hash)
        self.seen_tx_set.add(tx_hash)

    def has_seen(self, tx_hash: str) -> bool:
        return bool(tx_hash) and tx_hash in self.seen_tx_set


class MultiMasterMonitor:
    """Polls positions of all followed wallets and emits trade signals.

    The set of watched wallets is refreshed periodically via
    refresh_watched_wallets(), which queries the DB for all unique
    followed_wallets across all active users.
    """

    # H2 FIX: Circuit breaker constants
    _CB_ERROR_THRESHOLD = 5  # consecutive errors before degraded mode
    _CB_DEGRADED_INTERVAL = 60  # seconds between polls in degraded mode

    def __init__(
        self,
        poll_interval: int = 1,
        on_signal: Optional[Callable[[TradeSignal], Awaitable[None]]] = None,
    ):
        self._poll_interval = poll_interval
        self._on_signal = on_signal
        self._wallet_states: dict[str, WalletState] = {}
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        # H2 FIX: Circuit breaker state
        self._consecutive_errors = 0
        self._degraded_mode = False

    async def start(self) -> None:
        """Start monitoring in background."""
        if self._is_running:
            logger.warning("Monitor already running")
            return

        self._is_running = True
        await self.refresh_watched_wallets()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"Multi-master monitor started "
            f"(interval: {self._poll_interval}s, "
            f"wallets: {len(self._wallet_states)})"
        )

    async def stop(self) -> None:
        """Stop monitoring."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Multi-master monitor stopped")

    async def refresh_watched_wallets(self) -> None:
        """Refresh the set of wallets to watch from the database.

        Adds new wallets, removes wallets nobody follows anymore.
        """
        from bot.db.session import async_session
        from bot.services.user_service import get_all_followed_wallets

        try:
            async with async_session() as session:
                active_wallets = await get_all_followed_wallets(session)
        except Exception as e:
            logger.error(f"Failed to refresh watched wallets: {e}")
            return

        active_set = {w.lower() for w in active_wallets}
        current_set = set(self._wallet_states.keys())

        added = active_set - current_set
        removed = current_set - active_set

        for wallet in added:
            self._wallet_states[wallet] = WalletState()

        for wallet in removed:
            del self._wallet_states[wallet]

        if added or removed:
            logger.info(
                f"Watched wallets updated: +{len(added)} -{len(removed)} "
                f"= {len(self._wallet_states)} total"
            )

        # 🔧 CRITICAL FIX: Take initial snapshot for newly added wallets.
        # Without this, _check_wallet skips them (state.initialized=False),
        # meaning newly-added traders would NEVER be monitored until bot restart.
        if added:
            snapshot_tasks = [
                self._snapshot_wallet(w, initial=True) for w in added
            ]
            await asyncio.gather(*snapshot_tasks, return_exceptions=True)
            logger.info(
                f"Initial snapshot taken for {len(added)} newly added wallet(s) "
                f"— monitoring now active"
            )

    async def _poll_loop(self) -> None:
        """Main polling loop with circuit breaker (H2 FIX)."""
        # Initial snapshot for all wallets
        await self._snapshot_all(initial=True)

        while self._is_running:
            try:
                interval = (
                    self._CB_DEGRADED_INTERVAL
                    if self._degraded_mode
                    else self._poll_interval
                )
                await asyncio.sleep(interval)
                await self._check_all_wallets()
                # Success — reset circuit breaker
                if self._consecutive_errors > 0:
                    logger.info(
                        f"Monitor recovered after {self._consecutive_errors} errors"
                    )
                self._consecutive_errors = 0
                if self._degraded_mode:
                    self._degraded_mode = False
                    logger.info("Monitor exiting degraded mode — back to normal polling")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(
                    f"Monitor poll error ({self._consecutive_errors}/"
                    f"{self._CB_ERROR_THRESHOLD}): {e}"
                )
                if (
                    self._consecutive_errors >= self._CB_ERROR_THRESHOLD
                    and not self._degraded_mode
                ):
                    self._degraded_mode = True
                    logger.warning(
                        f"⚠️ Monitor entering DEGRADED mode after "
                        f"{self._consecutive_errors} consecutive errors. "
                        f"Polling every {self._CB_DEGRADED_INTERVAL}s instead of "
                        f"{self._poll_interval}s"
                    )
                await asyncio.sleep(5)

    async def _snapshot_all(self, initial: bool = False) -> None:
        """Fetch positions + activity cursor for all watched wallets."""
        tasks = [
            self._snapshot_wallet(wallet, initial)
            for wallet in list(self._wallet_states.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _snapshot_wallet(self, wallet: str, initial: bool = False) -> None:
        """Initialise le wallet : positions courantes + curseur d'activité.

        On démarre le curseur d'activité à now - _INITIAL_LOOKBACK_S pour
        rattraper les trades des toutes dernières secondes. Tout ce qui est
        plus ancien que ce lookback est considéré "déjà acquis" et ne
        déclenchera jamais de signal — comportement voulu : on copie les
        trades à venir, pas l'historique rétroactif.
        """
        import time as _time

        state = self._wallet_states.get(wallet)
        if state is None:
            return

        positions = await polymarket_client.get_positions_by_address(wallet)

        if initial or not state.initialized:
            state.positions = {p.token_id: p for p in positions}
            state.initialized = True
            state.last_activity_ts = max(
                0, int(_time.time()) - _INITIAL_LOOKBACK_S
            )
            logger.info(
                f"Snapshot {wallet[:10]}...: {len(positions)} positions, "
                f"activity cursor @ T-{_INITIAL_LOOKBACK_S}s"
            )

    async def _check_all_wallets(self) -> None:
        """Run one detection pass on each watched wallet (activity-driven)."""
        tasks = [
            self._check_wallet(wallet)
            for wallet in list(self._wallet_states.keys())
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_wallet(self, wallet: str) -> None:
        """Activity-driven detection : emit one signal per new CLOB trade.

        Flow :
          1) GET /activity?user=<wallet>&start=<last_ts>  (type=TRADE)
          2) Si rien : pas d'autre appel → coût idle = 1 HTTP call
          3) Si activité : rafraîchir positions (une seule fois) pour
             calculer le sell_ratio des SELL
          4) Pour chaque activity non-vue, émettre un TradeSignal
        """
        state = self._wallet_states.get(wallet)
        if state is None or not state.initialized:
            return

        activities = await polymarket_client.get_activity_by_address(
            wallet,
            limit=100,
            start=state.last_activity_ts or None,
        )
        if not activities:
            return

        # Tri chronologique ASC (API renvoie typiquement DESC).
        activities = sorted(activities, key=lambda a: a.timestamp)

        # Filtrer les doublons (déjà vus sur un poll précédent) + ignorer les
        # activités <= last_ts (API peut renvoyer == last_ts en bord de
        # fenêtre). Le curseur sera avancé en fin de fonction.
        fresh = [
            a for a in activities
            if a.timestamp >= state.last_activity_ts
            and not state.has_seen(a.tx_hash)
        ]
        if not fresh:
            return

        # Snapshot positions courant (une seule fois ici) pour déduire le
        # sell_ratio des SELL. Pour idle → on ne l'appelle jamais.
        try:
            current_positions = await polymarket_client.get_positions_by_address(
                wallet
            )
            current_map = {p.token_id: p for p in current_positions}
        except Exception as e:
            logger.warning(
                f"[{wallet[:10]}...] positions refresh failed mid-check "
                f"(using stale cache): {e}"
            )
            current_map = dict(state.positions)

        for act in fresh:
            token_id = act.token_id or ""
            side = (act.side or "").upper()
            size = float(act.size or 0)

            if not token_id:
                logger.debug(
                    f"[{wallet[:10]}...] activity without token_id "
                    f"(tx={act.tx_hash[:10]}...) skipped"
                )
                state.mark_seen(act.tx_hash)
                continue

            if size < MIN_SIGNAL_SIZE:
                logger.info(
                    f"[{wallet[:10]}...] ⏭️ activity skipped (size {size:.4f} "
                    f"< {MIN_SIGNAL_SIZE}) {side} on {token_id[:12]}..."
                )
                state.mark_seen(act.tx_hash)
                continue

            market_id = act.market_id
            # market_id absent du payload activity ? retomber sur le cache.
            if not market_id:
                cached = current_map.get(token_id) or state.positions.get(token_id)
                if cached is not None:
                    market_id = cached.market_id

            pos = current_map.get(token_id) or state.positions.get(token_id)
            outcome = act.outcome or (pos.outcome if pos else "")
            title = act.title or (pos.title if pos else "")
            price = float(act.price or 0) or (
                float(pos.current_price) if pos else 0.0
            )
            pnl_pct = float(pos.pnl_pct) if pos else 0.0

            if side == "BUY":
                signal = TradeSignal(
                    master_wallet=wallet,
                    market_id=market_id,
                    token_id=token_id,
                    outcome=outcome,
                    side="BUY",
                    size=size,
                    price=price,
                    master_pnl_pct=pnl_pct,
                    market_question=title,
                )
                logger.info(
                    f"[{wallet[:10]}...] 🆕 activity BUY {size:.2f} sh @ {price:.4f} "
                    f"on {token_id[:12]}... ({title[:40]})"
                )
                await self._emit_signal(signal)

            elif side == "SELL":
                # Si le marché est résolu, c'est un REDEEM onchain, pas un SELL.
                if pos and getattr(pos, "redeemable", False):
                    logger.info(
                        f"[{wallet[:10]}...] activity SELL on {token_id[:12]}... "
                        f"but market RESOLVED — skip (REDEEM, not SELL)"
                    )
                    state.mark_seen(act.tx_hash)
                    continue
                remaining = float(pos.size) if pos else 0.0
                pre_size = remaining + size
                sell_ratio = (size / pre_size) if pre_size > 0 else 1.0
                sell_ratio = max(0.0, min(1.0, sell_ratio))
                signal = TradeSignal(
                    master_wallet=wallet,
                    market_id=market_id,
                    token_id=token_id,
                    outcome=outcome,
                    side="SELL",
                    size=size,
                    price=price,
                    master_pnl_pct=pnl_pct,
                    market_question=title,
                    sell_ratio=sell_ratio,
                )
                logger.info(
                    f"[{wallet[:10]}...] 🔻 activity SELL {size:.2f} sh "
                    f"(~{sell_ratio*100:.0f}% de la position) @ {price:.4f} "
                    f"on {token_id[:12]}..."
                )
                await self._emit_signal(signal)
            else:
                logger.debug(
                    f"[{wallet[:10]}...] activity side unknown ({act.side!r}) — skip"
                )

            state.mark_seen(act.tx_hash)

        # Avance le curseur au timestamp max vu (NB: pas activities[-1] car
        # on a trié, donc c'est bien le plus récent).
        state.last_activity_ts = max(
            state.last_activity_ts, fresh[-1].timestamp
        )
        # Met à jour le cache de positions pour le scoring/consensus.
        state.positions = current_map

    async def _emit_signal(self, signal: TradeSignal) -> None:
        """Emit a trade signal to the copytrade engine."""
        logger.info(
            f"Signal [{signal.master_wallet[:10]}...]: "
            f"{signal.side} {signal.size:.2f} shares "
            f"of {signal.token_id[:12]}... @ {signal.price:.4f}"
        )
        if self._on_signal:
            try:
                await self._on_signal(signal)
            except Exception as e:
                logger.error(f"Signal handler error: {e}")

    @property
    def watched_wallets(self) -> list[str]:
        return list(self._wallet_states.keys())

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def fast_check_all_wallets(self) -> None:
        """Expose a public trigger to forcer un check immédiat.

        Utilisé par le monitor WebSocket (CLOB) pour accélérer la détection
        en complément du polling Gamma.
        """
        if not self._is_running:
            return
        await self._check_all_wallets()
