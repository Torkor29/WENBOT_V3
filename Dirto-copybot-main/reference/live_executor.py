#!/usr/bin/env python3
"""
Live Executor — Passe les vrais ordres sur Polymarket CLOB.

Utilisé par le resolution_collector pour exécuter les trades en live.
Sépare la logique d'exécution (ordres réels) de la logique de décision (portfolio_manager).

Usage:
    executor = LiveExecutor()  # charge .env, init client
    order = executor.buy(token_id, amount_usdc=4.0)  # achète
    order = executor.sell(token_id, shares=8.0)       # vend (couverture)
"""
import os, sys, time, json

# Add py_clob_client from the other venv if not available
_clob_path = '/home/lab/Polymarket-End-Of-Window-MultiSignal/venv/lib/python3.12/site-packages'
if os.path.isdir(_clob_path) and _clob_path not in sys.path:
    sys.path.insert(0, _clob_path)

# Load .env
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.isfile(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v

TRADES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades_live.jsonl')
DRY_RUN = os.environ.get('LIVE_DRY_RUN', 'false').lower() == 'true'
LIVE_INVEST = float(os.environ.get('LIVE_INVEST', '4.0'))
LIVE_MIN_BALANCE = float(os.environ.get('LIVE_MIN_BALANCE', '0'))


class LiveExecutor:
    def __init__(self):
        self.client = None
        self.enabled = False
        self.live_stopped = False  # True if balance dropped below minimum
        self.estimated_balance = None  # Track balance estimate
        self._init_client()

    def _init_client(self):
        pk = os.environ.get('POLYMARKET_PK')
        funder = os.environ.get('POLYMARKET_FUNDER')
        sig_type = int(os.environ.get('POLYMARKET_SIGNATURE_TYPE', '2'))

        if not pk:
            print("  [EXECUTOR] POLYMARKET_PK not set — live trading disabled", flush=True)
            return

        try:
            from py_clob_client.client import ClobClient
            self.client = ClobClient(
                host='https://clob.polymarket.com',
                chain_id=137,
                key=pk,
                signature_type=sig_type,
                funder=funder if funder else None,
            )
            creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(creds)
            self.enabled = True
            print(f"  [EXECUTOR] CLOB client ready (sig_type={sig_type}, funder={funder[:10]}...)" if funder else
                  f"  [EXECUTOR] CLOB client ready (sig_type={sig_type})", flush=True)
        except Exception as e:
            print(f"  [EXECUTOR] Init failed: {e}", flush=True)
            self.enabled = False

    def buy(self, token_id, amount_usdc=4.0, min_price=0.0, max_price=1.0):
        """Place a BUY market order. Returns order result or None.
        min_price/max_price: refuse if best_ask is outside this range."""
        if not self.enabled:
            return None
        if self.live_stopped:
            print(f"  [EXECUTOR] LIVE STOPPED (balance < {LIVE_MIN_BALANCE}$)", flush=True)
            return None
        if DRY_RUN:
            print(f"  [EXECUTOR] DRY BUY {amount_usdc}$ token={token_id[:20]}...", flush=True)
            return {'dry_run': True, 'side': 'BUY', 'amount': amount_usdc}

        # Use LIVE_INVEST instead of portfolio's INVEST
        amount_usdc = LIVE_INVEST

        # Check balance before trading
        if LIVE_MIN_BALANCE > 0:
            bal = self.get_balance()
            if bal is not None:
                self.estimated_balance = bal
                if bal < LIVE_MIN_BALANCE:
                    self.live_stopped = True
                    print(f"  [EXECUTOR] BALANCE {bal:.2f}$ < {LIVE_MIN_BALANCE}$ — LIVE STOPPED", flush=True)
                    return None

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType, OrderArgs
            from py_clob_client.order_builder.constants import BUY

            # Get current best ask to set a price with margin
            best_ask = None
            try:
                book = self.client.get_order_book(token_id)
                asks = book.asks if hasattr(book, 'asks') else []
                if asks:
                    best_ask = min(float(a.price) for a in asks)
            except Exception:
                pass

            # Pre-approve conditional token for future SELL (coverage)
            try:
                from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
                self.client.update_balance_allowance(
                    BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
                )
            except Exception:
                pass

            # Guard: refuser si best_ask hors range de la stratégie
            if best_ask is not None and (best_ask < min_price or best_ask > max_price):
                print(f"  [EXECUTOR] BUY REJECTED: best_ask={best_ask:.4f} hors range [{min_price:.2f}-{max_price:.2f}]", flush=True)
                self._log_trade('BUY', token_id, amount_usdc, 0, 0, False, '',
                               {'status': 'REJECTED', 'reason': f'best_ask={best_ask} hors range'})
                return {'success': False, 'status': 'REJECTED', 'orderID': '', 'takingAmount': '0', 'makingAmount': '0'}

            # BUY: FOK puis fallback FAK
            buy_price = min(best_ask + 0.05, 0.95) if best_ask and best_ask > 0.01 else 0.95
            print(f"  [EXECUTOR] BUY {amount_usdc}$ | best_ask={best_ask} | price={buy_price:.2f} | token={token_id[:20]}...", flush=True)

            result = None
            buy_status = 'FAILED'
            total_shares = 0.0
            total_cost = 0.0
            all_order_ids = []

            for attempt, order_type in [(1, OrderType.FOK), (2, OrderType.FAK)]:
                try:
                    order = MarketOrderArgs(
                        token_id=token_id,
                        amount=amount_usdc - total_cost,  # restant à acheter
                        side='BUY',
                        price=buy_price,
                    )
                    signed = self.client.create_market_order(order)
                    result = self.client.post_order(signed, order_type)

                    if result.get('success', False):
                        filled_shares = float(result.get('takingAmount', '0'))
                        filled_cost = float(result.get('makingAmount', '0'))
                        total_shares += filled_shares
                        total_cost += filled_cost
                        all_order_ids.append(result.get('orderID', ''))

                        # FULL = cost réel >= 99% du montant demandé (tolérance arrondi USDC 6 decimals)
                        if total_cost >= amount_usdc * 0.99:
                            buy_status = 'FULL_SUCCESS'
                        else:
                            buy_status = 'PARTIAL_SUCCESS'

                        type_name = 'FOK' if attempt == 1 else 'FAK'
                        print(f"  [EXECUTOR] BUY {type_name} OK: {filled_shares:.4f}sh for {filled_cost:.2f}$ | total={total_shares:.4f}sh", flush=True)
                        break
                    else:
                        err = str(result.get('errorMsg', result))
                        if attempt == 1:
                            # FOK failed → toujours tenter FAK, quelle que soit l'erreur
                            print(f"  [EXECUTOR] BUY FOK failed: {err[:80]}, trying FAK...", flush=True)
                            continue
                        else:
                            print(f"  [EXECUTOR] BUY FAK failed: {err[:80]}", flush=True)
                            break

                except Exception as e:
                    if attempt == 1:
                        print(f"  [EXECUTOR] BUY FOK error: {e}, trying FAK...", flush=True)
                        continue
                    else:
                        print(f"  [EXECUTOR] BUY FAK error: {e}", flush=True)
                        break

            # Log et résultat
            order_id = ','.join(all_order_ids) if all_order_ids else ''
            self._log_trade('BUY', token_id, amount_usdc, total_shares, total_cost,
                           buy_status != 'FAILED', order_id,
                           {'status': buy_status, 'shares': total_shares, 'cost': total_cost})

            if buy_status == 'FAILED':
                print(f"  [EXECUTOR] BUY FAILED: 0 shares", flush=True)
            elif buy_status == 'PARTIAL_SUCCESS':
                print(f"  [EXECUTOR] BUY PARTIAL: {total_shares:.4f}sh for {total_cost:.2f}$ (requested {amount_usdc}$)", flush=True)

            return {
                'success': buy_status == 'FULL_SUCCESS',
                'partial': buy_status == 'PARTIAL_SUCCESS',
                'status': buy_status,
                'orderID': order_id,
                'takingAmount': str(total_shares),
                'makingAmount': str(total_cost),
            }

        except Exception as e:
            print(f"  [EXECUTOR] BUY ERROR: {e}", flush=True)
            self._log_trade('BUY', token_id, amount_usdc, 0, 0, False, '', {'error': str(e)})
            return None

    def sell(self, token_id, shares):
        """Place a SELL market order (for coverage/take-profit). Returns order result or None."""
        if not self.enabled:
            return None
        if shares <= 0:
            return None
        if DRY_RUN:
            print(f"  [EXECUTOR] DRY SELL {shares:.2f} shares token={token_id[:20]}...", flush=True)
            return {'dry_run': True, 'side': 'SELL', 'shares': shares}

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType, OrderArgs
            from py_clob_client.order_builder.constants import SELL as SELL_SIDE

            # Get best bid to set sell price with margin
            # Approve conditional token before selling
            try:
                from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
                self.client.update_balance_allowance(
                    BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
                )
            except Exception:
                pass

            best_bid = None
            try:
                book = self.client.get_order_book(token_id)
                bids = book.bids if hasattr(book, 'bids') else []
                if bids:
                    best_bid = max(float(b.price) for b in bids)
            except Exception:
                pass

            # SELL: state-based — vérifier balance réel, retry, partial sell
            result = None
            success = False
            sell_status = 'FAILED'
            max_attempts = 12  # 12 x 5s = 60s max
            remaining = shares
            total_received = 0.0
            all_order_ids = []

            for attempt in range(max_attempts):
                if remaining < 0.001:
                    break  # tout vendu
                try:
                    # 1. Vérifier le balance réel
                    available = self.get_share_balance(token_id)

                    if available is None:
                        print(f"  [EXECUTOR] SELL {attempt+1}/{max_attempts}: balance=UNKNOWN (API error), retry in 5s...", flush=True)
                        time.sleep(5)
                        continue

                    if available <= 0:
                        print(f"  [EXECUTOR] SELL {attempt+1}/{max_attempts}: balance=0 (not settled yet), retry in 5s...", flush=True)
                        time.sleep(5)
                        continue

                    # 2. Déterminer le montant à vendre
                    sell_amount = min(remaining, available)
                    is_partial = sell_amount < remaining - 0.001
                    sell_type = 'PARTIAL' if is_partial else 'FULL'
                    print(f"  [EXECUTOR] SELL {attempt+1}/{max_attempts}: requested={remaining:.4f} available={available:.4f} selling={sell_amount:.4f} ({sell_type})", flush=True)

                    # 3. Approve + refresh price
                    try:
                        self.client.update_balance_allowance(
                            BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
                        )
                    except Exception:
                        pass

                    try:
                        book = self.client.get_order_book(token_id)
                        bids = book.bids if hasattr(book, 'bids') else []
                        if bids:
                            best_bid = max(float(b.price) for b in bids)
                    except Exception:
                        pass
                    sell_price = max(best_bid - 0.05, 0.01) if best_bid and best_bid > 0.01 else 0.01

                    # 4. FOK first attempt, FAK after
                    order_type = OrderType.FOK if attempt == 0 else OrderType.FAK
                    order = MarketOrderArgs(
                        token_id=token_id,
                        amount=sell_amount,
                        side='SELL',
                        price=sell_price,
                    )
                    signed = self.client.create_market_order(order)
                    result = self.client.post_order(signed, order_type)

                    if result.get('success', False):
                        filled = float(result.get('takingAmount', sell_amount))
                        received = float(result.get('makingAmount', '0'))
                        total_received += received
                        remaining -= filled
                        all_order_ids.append(result.get('orderID', ''))
                        print(f"  [EXECUTOR] SELL {sell_type} OK: sold {filled:.4f}sh, received {received:.2f}$, remaining={remaining:.4f}", flush=True)
                        if remaining < 0.001:
                            success = True
                            break
                        # Partial: continue loop to sell the rest
                        continue
                    else:
                        err = str(result.get('errorMsg', result))
                        # Erreurs fatales : pas la peine de retenter
                        fatal_errors = ['does not exist', 'not found', 'resolved', 'closed', 'expired']
                        if any(fe in err.lower() for fe in fatal_errors):
                            print(f"  [EXECUTOR] SELL ABORTED_FATAL: {err[:80]}", flush=True)
                            sell_status = 'ABORTED_FATAL'
                            break
                        print(f"  [EXECUTOR] SELL {attempt+1}/{max_attempts} failed: {err[:60]}, retry in 5s...", flush=True)
                        time.sleep(5)

                except Exception as e:
                    err_str = str(e)
                    fatal_errors = ['does not exist', 'not found', 'resolved', 'closed', 'expired']
                    if any(fe in err_str.lower() for fe in fatal_errors):
                        print(f"  [EXECUTOR] SELL ABORTED_FATAL: {err_str[:80]}", flush=True)
                        sell_status = 'ABORTED_FATAL'
                        break
                    print(f"  [EXECUTOR] SELL {attempt+1}/{max_attempts} error: {e}, retry in 5s...", flush=True)
                    time.sleep(5)

            # Bilan final — 3 états distincts
            if result is None:
                result = {}
            order_id = ','.join(all_order_ids) if all_order_ids else ''
            usdc_received = str(total_received)

            if sell_status == 'ABORTED_FATAL':
                sell_status = 'ABORTED_FATAL'
                success = False
                print(f"  [EXECUTOR] SELL ABORTED_FATAL: marché fermé/résolu, {remaining:.4f}sh non vendables", flush=True)
            elif remaining < 0.001:
                sell_status = 'FULL_SUCCESS'
                success = True
                print(f"  [EXECUTOR] SELL FULL_SUCCESS: {shares:.4f}sh → {total_received:.2f}$", flush=True)
            elif total_received > 0:
                sell_status = 'PARTIAL_SUCCESS'
                success = False
                print(f"  [EXECUTOR] SELL PARTIAL_SUCCESS: sold {shares-remaining:.4f}/{shares:.4f}sh → {total_received:.2f}$, REMAINING={remaining:.4f}sh unsold", flush=True)
            else:
                sell_status = 'FAILED'
                success = False
                print(f"  [EXECUTOR] SELL FAILED: 0/{shares:.4f}sh sold after {max_attempts} attempts", flush=True)

            # Log avec status explicite
            self._log_trade('SELL', token_id, 0, shares, total_received, success, order_id,
                           {'status': sell_status, 'sold': shares - remaining, 'remaining': remaining,
                            'received': total_received, 'attempts': attempt + 1})

            result_out = {
                'success': sell_status == 'FULL_SUCCESS',
                'partial': sell_status == 'PARTIAL_SUCCESS',
                'status': sell_status,
                'orderID': order_id,
                'makingAmount': str(total_received),
                'sold': shares - remaining,
                'remaining': remaining,
            }
            return result_out

        except Exception as e:
            print(f"  [EXECUTOR] SELL ERROR: {e}", flush=True)
            self._log_trade('SELL', token_id, 0, shares, 0, False, '', {'error': str(e)})
            return None

    def get_balance(self):
        """Get USDC balance. Returns float or None."""
        if not self.enabled:
            return None
        try:
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            bal = self.client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            return float(bal.get('balance', 0)) if isinstance(bal, dict) else None
        except Exception as e:
            print(f"  [EXECUTOR] Balance check error: {e}", flush=True)
            return None

    def get_share_balance(self, token_id):
        """Get share balance for a specific token. Returns float in real units or None."""
        if not self.enabled:
            return None
        try:
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            bal = self.client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL, token_id=token_id)
            )
            raw = float(bal.get('balance', 0)) if isinstance(bal, dict) else None
            if raw is None:
                return None
            # Balance retourné en base units (6 décimales), convertir en shares réelles
            return raw / 1e6
        except Exception as e:
            return None

    def redeem_all(self):
        """Redeem all resolved winning positions. Returns list of results or None."""
        if not self.enabled:
            return None

        # Check for dedicated Builder API creds (required by Polymarket relayer)
        builder_key = os.environ.get('BUILDER_API_KEY', '')
        builder_secret = os.environ.get('BUILDER_API_SECRET', '')
        builder_passphrase = os.environ.get('BUILDER_API_PASSPHRASE', '')

        if not (builder_key and builder_secret and builder_passphrase):
            print("  [REDEEM] Skipped: missing BUILDER_API_KEY/SECRET/PASSPHRASE in .env", flush=True)
            return None

        try:
            import sys
            sys.path.insert(0, '/tmp/poly_web3_pkg')
            from py_builder_relayer_client.client import RelayClient
            from py_builder_signing_sdk.config import BuilderConfig
            from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
            from poly_web3 import PolyWeb3Service

            pk = os.environ.get('POLYMARKET_PK')
            print(f"  [REDEEM] Using Builder creds: key={builder_key[:8]}...", flush=True)
            builder_creds = BuilderApiKeyCreds(
                key=builder_key, secret=builder_secret, passphrase=builder_passphrase
            )
            builder_cfg = BuilderConfig(local_builder_creds=builder_creds)
            relay_client = RelayClient(
                relayer_url='https://relayer-v2.polymarket.com/',
                chain_id=137,
                private_key=pk,
                builder_config=builder_cfg,
            )
            rpc = os.environ.get('ALCHEMY_RPC_URL', 'https://polygon-rpc.com')
            service = PolyWeb3Service(
                clob_client=self.client,
                relayer_client=relay_client,
                rpc_url=rpc,
            )
            results = service.redeem_all(batch_size=10)
            if results:
                print(f"  [EXECUTOR] REDEEM OK: {len(results)} positions redeemed", flush=True)
                self._log_trade('REDEEM', '', 0, 0, 0, True, '', {'redeemed': len(results)})
            return results
        except Exception as e:
            print(f"  [EXECUTOR] REDEEM ERROR: {e}", flush=True)
            return None

    def _log_trade(self, side, token_id, amount_usdc, shares, cost_or_received, success, order_id, raw_result):
        """Append trade to JSONL log file."""
        try:
            entry = {
                'ts': time.time(),
                'side': side,
                'token_id': token_id[:30],
                'amount_usdc': amount_usdc,
                'shares': shares,
                'cost_or_received': cost_or_received,
                'success': success,
                'order_id': order_id,
                'raw': str(raw_result)[:200],
            }
            with open(TRADES_LOG, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass
