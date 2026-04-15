# WENBOT FUSION — Polymarket CopyTrading + Strategy Bot

Bot Telegram professionnel pour [Polymarket](https://polymarket.com) qui fusionne deux moteurs complets :

- **Copy Wallet** : copie automatique des trades de wallets Polymarket suivis (multi-masters)
- **Suivi de Strategies** : execution automatique de signaux de strategies via Redis pub/sub

Chaque utilisateur dispose de wallets separes, de parametres individuels et de notifications routees vers des topics Telegram dedies.

---

## Table des matieres

- [Architecture](#architecture)
- [Fonctionnalites](#fonctionnalites)
  - [Copy Wallet](#copy-wallet)
  - [Suivi de Strategies](#suivi-de-strategies)
  - [Smart Analysis V3](#smart-analysis-v3)
  - [Gestion des positions](#gestion-des-positions)
  - [Depot de fonds](#depot-de-fonds)
  - [Dashboard Web](#dashboard-web)
- [Modeles de donnees](#modeles-de-donnees)
- [Services](#services)
- [Systeme de frais](#systeme-de-frais)
- [Systeme de scoring](#systeme-de-scoring)
- [Gestion du risque](#gestion-du-risque)
- [Securite](#securite)
- [Telegram — Commandes et navigation](#telegram--commandes-et-navigation)
- [Infrastructure](#infrastructure)
- [Deploiement VPS](#deploiement-vps)
- [Configuration](#configuration)
- [Stack technique](#stack-technique)

---

## Architecture

```
                     Telegram Users
                          |
                     Telegram Bot
                     (python-telegram-bot 21.x)
                          |
            +-------------+-------------+
            |                           |
       Copy Wallet                Strategy Engine
            |                           |
  MultiMasterMonitor            StrategyListener
  (poll Gamma API)              (Redis pub/sub)
            |                           |
     CopyTradeEngine            StrategyExecutor
            |                           |
       +----+----+                 +----+----+
       |         |                 |         |
   SignalScorer  SmartFilter   GasManager  Resolver
       |         |                 |         |
       +---------+---------+------+---------+
                           |
                    PolymarketClient
                    (CLOB API — ordres)
                           |
                     Polygon Blockchain
                     (USDC, MATIC, CTF)
                           |
                 +----+----+----+
                 |    |         |
              Web3  Fees    Positions
              Client Engine  Manager
                           |
                 PostgreSQL + Redis
```

**3 couches** :
- **Handlers** (`bot/handlers/`) : interface Telegram (commandes, callbacks, menus)
- **Services** (`bot/services/`) : logique metier (execution, monitoring, scoring, fees)
- **Models** (`bot/models/`) : ORM SQLAlchemy async (16 tables)

---

## Fonctionnalites

### Copy Wallet

Le moteur de copy-trading surveille les wallets Polymarket que l'utilisateur choisit de suivre et reproduit automatiquement leurs trades.

**Flux complet** :

1. `MultiMasterMonitor` poll les positions des wallets suivis via l'API Gamma (intervalle configurable, defaut 15s)
2. Detection d'un changement = emission d'un `TradeSignal` (achat ou vente)
3. `CopyTradeEngine` recoit le signal et pour chaque follower du wallet :
   - Valide les filtres (categories, blacklist, expiry max)
   - Score le signal via `SignalScorer` (0-100) — si V3 active
   - Filtre via `SmartFilter` (coin-flip, conviction, trader edge)
   - Verifie les contraintes portfolio via `PortfolioManager`
   - Calcule la taille via `SizingEngine` (4 modes)
   - Calcule et transfere les frais on-chain
   - Execute l'ordre via l'API CLOB de Polymarket
   - Enregistre le trade + frais en base
   - Notifie via `TopicRouter` (topic Telegram ou DM)
   - Enregistre la position ouverte pour le suivi SL/TP

**4 modes de sizing** :

| Mode | Description | Calcul |
|------|-------------|--------|
| `FIXED` | Montant fixe par trade | `fixed_amount` (ex: 5 USDC) |
| `PERCENT` | % du capital alloue | `allocated_capital * percent_per_trade` |
| `PROPORTIONAL` | Proportion du trade master | `master_amount * (my_capital / master_portfolio) * multiplier` |
| `KELLY` | Kelly Criterion simplifie | Utilise le mode PERCENT avec le % configure |

Contraintes appliquees : `min_trade_usdc`, `max_trade_usdc`, balance disponible.

**Paper trading** : Chaque utilisateur peut activer le mode paper (balance virtuelle de 1000 USDC par defaut). Les trades sont simules — memes calculs, memes notifications, mais aucune transaction on-chain.

### Suivi de Strategies

Le moteur de strategies permet de suivre des strategies automatisees qui publient des signaux via Redis.

**Flux complet** :

1. Un pod/container externe publie un signal JSON sur Redis channel `signals:<strategy_id>`
2. `StrategyListener` souscrit a `signals:*` via pub/sub, parse le JSON en `StrategySignalData`
3. `StrategyExecutor` recoit le signal :
   - Recupere les abonnements actifs pour cette strategie
   - Trie par `trade_fee_rate` DESC (priorite aux frais les plus eleves)
   - Pour chaque abonne, sequentiellement (avec delai configurable) :
     - Verifie le quota journalier + pause
     - Verifie le solde USDC du wallet strategie
     - Verifie le gas MATIC via `StrategyGasManager`
     - Calcule et transfere les frais (trade fee)
     - Execute l'ordre via CLOB
     - Enregistre le `Trade` (avec `strategy_id` renseigne)
     - Notifie via topic Telegram dedie
4. `StrategyResolver` poll l'API Gamma toutes les 30s :
   - Detecte les marches resolus
   - Calcule le PnL : WON = `shares * $1 - cost`, LOST = `0 - cost`
   - Met a jour `Trade.result`, `Trade.pnl`, `Trade.resolved_at`
   - Declenche le redeem Polymarket pour les gagnants
   - Recalcule les stats de la strategie (win rate, PnL total)
   - Notifie l'utilisateur

**Format du signal Redis** :

```json
{
  "strategy_id": "strat_v1",
  "action": "BUY",
  "side": "YES",
  "market_slug": "will-btc-hit-100k-2025",
  "token_id": "0x...",
  "max_price": 0.65,
  "shares": 10.0,
  "confidence": 0.85
}
```

**Wallet separe** : Chaque utilisateur a un wallet dedie aux strategies (`strategy_wallet_address`), completement separe du wallet de copy-trading. Les cles privees sont chiffrees independamment.

### Smart Analysis V3

Le systeme d'analyse intelligent ajoute une couche de filtrage et scoring avant chaque copy-trade.

#### Signal Scoring (0-100)

Chaque signal est evalue sur 6 criteres ponderes :

| Critere | Poids | Description | Calcul |
|---------|-------|-------------|--------|
| **Spread** | 15% | Bid-ask du marche | Score inversement proportionnel a l'ecart bid/ask |
| **Liquidite** | 15% | Volume 24h | 0-60 (volume) + 0-40 (spread) = score 0-100 |
| **Conviction** | 20% | Taille du trade master vs son portfolio | `trade_size / portfolio_value * 100` |
| **Forme du trader** | 20% | Win rate rolling 7j du trader | Depuis `TraderStats` (24h, 7d, 30d) |
| **Timing** | 15% | Distance a l'expiry optimale | Sweet spot = 24h-168h avant expiry |
| **Consensus** | 15% | Nb de masters sur le meme marche | Plus de masters = score plus eleve |

Chaque critere produit un score 0-100, pondere et somme. Le signal est copie si `total_score >= min_signal_score` (configurable par utilisateur, defaut 0 = tout passe).

Les poids sont modifiables par l'utilisateur via le menu `/signals`.

#### Smart Filter

Filtrage pattern-based **avant** le scoring :

| Filtre | Description | Seuils |
|--------|-------------|--------|
| **Coin-flip** | Prix entre 0.45-0.55 = marche indecis | Configurable (`skip_coin_flip`) |
| **Conviction** | Trade trop petit vs portfolio du master | `min_conviction_pct` (defaut 1%) |
| **Trader edge** | Win rate du trader sur ce type de marche | `min_trader_winrate_for_type` + `min_trader_trades_for_type` |
| **Price drift** | Le prix a trop bouge depuis le signal | `max_price_drift_pct` |

#### Trader Tracker

Suivi des performances par trader suivi :

- Stats rolling sur 24h, 7d, 30d : win rate, return moyen, PnL, Sharpe ratio
- Detection **hot streak** (bonus de sizing) et **cold streak** (pause auto)
- Performance par type de marche (crypto, politique, sport...) via `TraderMarketHistory`
- Seuils configurables : `cold_trader_threshold`, `hot_streak_boost`

### Gestion des positions

Le `PositionManager` surveille les positions ouvertes toutes les 15 secondes :

| Mecanisme | Description |
|-----------|-------------|
| **Stop-Loss** | Vend si le prix tombe sous `entry_price * (1 - sl_pct)` |
| **Take-Profit** | Vend si le prix depasse `entry_price * (1 + tp_pct)` |
| **Trailing Stop** | SL dynamique qui monte avec le prix (`highest_price * (1 - trailing_pct)`) |
| **Time Exit** | Vend apres N heures (`time_exit_hours`) |
| **Scale Out** | Vend un % de la position au TP, garde le reste |

Chaque exit declenche un ordre SELL reel (ou paper) via le callback `on_position_exit`, puis cree un `Trade` SELL correspondant.

**Controles portfolio** (`PortfolioManager`) :

| Controle | Description |
|----------|-------------|
| `max_positions` | Nombre max de positions ouvertes simultanees |
| `max_category_exposure_pct` | Exposition max a une categorie (ex: 40% crypto) |
| `max_direction_bias_pct` | Biais directionnel max (ex: 70% YES max) |

### Depot de fonds

Le bot guide l'utilisateur pour deposer des USDC sur son wallet Polygon. Deux methodes proposees :

**1. Carte bancaire** (debutants)
- Lien Transak pre-rempli avec le wallet de l'utilisateur
- MoonPay en alternative
- USDC recus en ~5 min, frais 2-4%

**2. Depuis un exchange** (Binance, Coinbase, OKX...)
- Acheter des USDC sur l'exchange
- Retrait vers l'adresse Polygon du wallet bot
- **Important** : reseau Polygon uniquement (pas Ethereum, pas Arbitrum)
- ~2-5 min, frais ~0.1 USDC

Le bot affiche l'adresse du wallet et permet de la copier en un clic. Pour le gas Polygon, l'utilisateur doit aussi envoyer ~0.2 POL/MATIC (quelques centimes suffisent pour des dizaines de trades).

### Dashboard Web

Dashboard FastAPI accessible sur le port 8090 :

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML (Jinja2) |
| `GET /api/dashboard` | Stats globales : trades today/week/total, volume, fees, win rate, followers actifs |
| `GET /api/traders` | Traders suivis avec nb followers, nb trades, volume |
| `GET /api/trades` | Trades recents, filtrables par periode/master/limit |

Lecture seule — aucune action possible depuis le dashboard.

---

## Modeles de donnees

16 tables SQLAlchemy async :

### Tables principales

```
users
  |-- id, uuid, telegram_id, telegram_username, role (ADMIN|FOLLOWER)
  |-- wallet_address, encrypted_private_key              # Copy wallet
  |-- strategy_wallet_address, encrypted_strategy_pk     # Strategy wallet (separe)
  |-- is_active, is_paused, paper_trading, live_mode_confirmed
  |-- daily_limit_usdc, daily_spent_usdc
  |-- paper_balance, paper_initial_balance

user_settings (1:1 avec User)
  |-- Sizing: allocated_capital, sizing_mode, fixed_amount, percent_per_trade, multiplier
  |-- Risk: stop_loss_pct, take_profit_pct, max/min_trade_usdc
  |-- Filtres: followed_wallets (JSON), categories, blacklisted_markets, max_expiry_days
  |-- V3 Smart: signal_scoring_enabled, min_signal_score, scoring_criteria (JSON)
  |-- V3 Positions: trailing_stop_pct, time_exit_hours, scale_out_pct
  |-- V3 Portfolio: max_positions, max_category_exposure_pct, max_direction_bias_pct
  |-- V3 Traders: auto_pause_cold_traders, cold_trader_threshold, hot_streak_boost

trades
  |-- trade_id (UUID), user_id, market_id, market_slug, token_id
  |-- side (BUY|SELL), price, gross/fee/net_amount_usdc, shares
  |-- master_wallet, master_trade_id                      # Copy: qui on a copie
  |-- strategy_id, result (WON|LOST), pnl, resolved_at   # Strategy: resolution
  |-- status (PENDING → FEE_PAID → EXECUTING → FILLED | FAILED)
  |-- is_paper, is_settled, settlement_pnl, market_outcome
```

### Tables strategies

```
strategies
  |-- id (str PK), name, description, version
  |-- status (ACTIVE|PAUSED|TESTING), visibility (PUBLIC|PRIVATE)
  |-- min/max_trade_size, execution_delay_ms
  |-- total_trades, total_pnl, win_rate (recalcules a la resolution)

subscriptions (user_id + strategy_id UNIQUE)
  |-- trade_size (USDC par signal), is_active

strategy_signals (audit trail)
  |-- strategy_id, action, side, market_slug, token_id
  |-- max_price, shares, confidence
  |-- subscribers_count, executed_count, skipped_count, total_volume

strategy_user_settings (1:1 avec User)
  |-- trade_fee_rate (1-20%), max_trades_per_day, trades_today
  |-- MATIC gas anti-exploit: refills_count, total_sent, last_refill_at

daily_performance_fees (user_id + fee_date UNIQUE)
  |-- total_trades, wins, losses, total_pnl
  |-- perf_fee_rate, perf_fee_amount, perf_fee_tx_hash
  |-- status (PENDING|SENT|SKIPPED|FAILED)
```

### Tables analytics

```
market_intel
  |-- market_id, question, category, expiry
  |-- volume_24h, open_interest, spread_avg, price_current
  |-- price_1h_ago, price_6h_ago, price_24h_ago         # Historique snapshot
  |-- momentum_1h (% variation), liquidity_score (0-100)
  |-- is_coin_flip (prix 0.45-0.55)

signal_scores
  |-- signal_hash (unique), master_wallet, market_id, side
  |-- total_score (0-100), components (JSON breakdown), passed (bool)

trader_stats (wallet + period UNIQUE)
  |-- period (24h|7d|30d), win_rate, avg_return_pct, total_pnl
  |-- sharpe_ratio, max_drawdown_pct, current_streak
  |-- is_hot, is_cold, auto_paused

trader_market_history (wallet + market_type UNIQUE)
  |-- trades_count, wins, losses, avg_return_pct

active_positions
  |-- user_id, trade_id, market_id, token_id, outcome
  |-- entry_price, current_price, highest_price, shares
  |-- sl_price, tp_price, trailing_stop_pct
  |-- is_closed, close_reason (sl_hit|tp_hit|trailing_stop|time_exit|manual)

group_config
  |-- group_id, is_forum
  |-- 5 topics copy: signals, traders, portfolio, alerts, admin
  |-- 2 topics strategy: strategies, strategies_perf
```

### Tables support

```
fee_records     — Audit trail des frais (montants, tx_hash, confirmation)
user_wallets    — Multi-wallet par user (chain, address, is_primary, label)
audit_logs      — Logs immutables (action, user, details, timestamp)
```

---

## Services

### Services principaux

| Service | Fichier | Role |
|---------|---------|------|
| `CopyTradeEngine` | `copytrade.py` | Orchestrateur copy-trading : signal -> filtres -> sizing -> fees -> execution |
| `MultiMasterMonitor` | `monitor.py` | Poll les positions des wallets suivis, emet les `TradeSignal` |
| `PolymarketClient` | `polymarket.py` | Wrapper API CLOB + Gamma + Data (ordres, positions, marches) |
| `Web3Client` | `web3_client.py` | Polygon RPC : balances USDC/MATIC, transfers, approvals |
| `TopicRouter` | `topic_router.py` | Route les notifications vers les topics Telegram (7 topics) |

### Services V3 Smart Analysis

| Service | Fichier | Role |
|---------|---------|------|
| `SignalScorer` | `signal_scorer.py` | Score 0-100 sur 6 criteres ponderes |
| `SmartFilter` | `smart_filter.py` | Filtres pattern-based (coin-flip, conviction, edge) |
| `PositionManager` | `position_manager.py` | SL/TP/trailing stop/time exit — poll toutes les 15s |
| `PortfolioManager` | `portfolio_manager.py` | Contraintes portfolio (positions max, exposition) |
| `TraderTracker` | `trader_tracker.py` | Stats rolling par trader (hot/cold detection) |
| `MarketIntelService` | `market_intel.py` | Cache market data + liquidity scoring + momentum |

### Services Strategy Engine

| Service | Fichier | Role |
|---------|---------|------|
| `StrategyListener` | `strategy_listener.py` | Subscribe Redis `signals:*`, dispatch au executor |
| `StrategyExecutor` | `strategy_executor.py` | Execute les signaux pour chaque abonne (fee queue priority) |
| `StrategyResolver` | `strategy_resolver.py` | Poll Gamma pour resolution, calcule PnL, redeem |
| `StrategyGasManager` | `strategy_gas_manager.py` | Refill MATIC avec 5 checks anti-exploit |
| `PerfFeeService` | `perf_fee_service.py` | Collecte journaliere des performance fees (5% PnL positif) |

### Services infrastructure

| Service | Fichier | Role |
|---------|---------|------|
| `RateLimiter` | `rate_limiter.py` | Sliding window Redis (fallback in-memory) |
| `CircuitBreaker` | `circuit_breaker.py` | Arret auto apres N echecs consecutifs |
| `AuditService` | `audit.py` | Logs immutables pour compliance |
| `CryptoService` | `crypto.py` | Chiffrement/dechiffrement AES-256-GCM |
| `OTPService` | `otp.py` | Codes a usage unique pour operations sensibles |

### Jobs planifies (APScheduler)

| Job | Intervalle | Description |
|-----|-----------|-------------|
| `reset_daily_limits` | Cron 00:00 UTC | RAZ des compteurs de depenses journalieres |
| `reset_strategy_daily_counters` | Cron 00:00 UTC | RAZ des compteurs de trades strategies |
| `collect_daily_perf_fees` | Cron 00:01 UTC | Collecte des performance fees (5% du PnL positif) |
| `settle_trades` | 2 min | Resolution des trades copy (paper + live) |
| `cleanup_expired_otps` | 10 min | Nettoyage des OTP expires |
| `health_check` | 5 min | Verification DB + services |
| `refresh_all_trader_stats` | 15 min | Recalcul des stats traders (24h, 7d, 30d) |
| `check_time_exits` | 5 min | Verification des sorties temporelles |
| `daily_portfolio_report` | Cron 08:00 UTC | Rapport portfolio journalier |
| `snapshot_market_prices` | 1h | Snapshot des prix pour le calcul du momentum |
| `sync_ws_subscriptions` | 2 min | Synchronisation des souscriptions WebSocket |

---

## Systeme de frais

### Copy Wallet

- **Frais plateforme** : 1% par trade (configurable via `PLATFORM_FEE_RATE`)
- Calcul : `fee = gross_amount * fee_rate`
- Transfert on-chain : USDC depuis le wallet utilisateur vers `FEES_WALLET`
- Enregistrement : `FeeRecord` avec tx_hash et confirmation

### Strategy Engine

Deux types de frais :

1. **Trade fee** (par trade) :
   - Taux configurable par l'utilisateur (1-20%, defaut 1%)
   - Preleve en USDC avant l'execution du trade
   - Les abonnes avec un fee_rate plus eleve sont executes en priorite (fee queue)

2. **Performance fee** (journaliere) :
   - 5% du PnL positif de la journee (configurable via `STRATEGY_PERF_FEE_RATE`)
   - Collectee a 00:01 UTC via cron job
   - Transferee du wallet strategie vers `FEES_WALLET`
   - Si PnL negatif ou nul : `SKIPPED` (pas de frais)

### MATIC Gas (Strategies)

Refill automatique de MATIC pour payer le gas Polygon, avec **5 protections anti-exploit** :

| Check | Description | Seuil defaut |
|-------|-------------|-------------|
| Lifetime refill cap | Nombre max de refills | 3 |
| Lifetime total cap | Montant max total envoye | 0.3 MATIC |
| Min USDC balance | Refill seulement si le wallet a assez d'USDC | 2 USDC |
| Rate limit | Cooldown entre refills | 24h |
| Projection | Refus si le refill depasserait le cap total | cap - deja_envoye |

---

## Systeme de scoring

### Scoring des signaux (copy-trading)

```
Signal recu du master
        |
        v
  [SmartFilter]  ─── Filtre pattern-based
  |  Coin-flip ? (prix 0.45-0.55)        → SKIP
  |  Conviction trop faible ?              → SKIP
  |  Trader sans edge sur ce marche ?      → SKIP
  |  Price drift trop important ?          → SKIP
  |
  v
  [SignalScorer]  ─── Score 0-100
  |  Spread         (15%) : ecart bid/ask
  |  Liquidite      (15%) : volume 24h + spread
  |  Conviction     (20%) : taille trade / portfolio master
  |  Forme trader   (20%) : win rate 7j du trader
  |  Timing         (15%) : distance a l'expiry optimale
  |  Consensus      (15%) : nb de masters sur le meme marche
  |
  v
  score >= min_signal_score ?
  |     |
  OUI   NON → SKIP
  |
  v
  [PortfolioManager]  ─── Contraintes portfolio
  |  Max positions atteint ?               → SKIP
  |  Exposition categorie trop elevee ?     → SKIP
  |  Biais directionnel trop fort ?         → SKIP
  |
  v
  EXECUTION
```

### Calcul du momentum

- Job planifie toutes les heures : `snapshot_market_prices`
- Ne track que les marches avec des positions ouvertes (copy trades non settles + strategy trades non resolus)
- Snapshot : `price_current` -> `price_1h_ago` (toutes les heures)
- Shift : `price_1h_ago` -> `price_6h_ago` -> `price_24h_ago` (toutes les 6h)
- Calcul : `momentum_1h = (price_current - price_1h_ago) / price_1h_ago * 100`

### Calcul du liquidity score

```
liquidity_score = volume_component (0-60) + spread_component (0-40)

Volume 24h         | Score      Spread %     | Score
>= 500k USDC      | 60         < 1%         | 40
>= 100k            | 50         < 2%         | 30
>= 50k             | 40         < 3%         | 20
>= 10k             | 25         < 5%         | 10
>= 1k              | 10         >= 5%        | 0
< 1k               | 0
```

### Resolution et PnL

**Copy-trading** : `settle_trades()` poll Polymarket toutes les 2 minutes.

**Strategy** : `StrategyResolver` poll l'API Gamma toutes les 30 secondes.

Calcul identique dans les deux cas :

| Resultat | PnL |
|----------|-----|
| **WON** (token_id = winning_token) | `shares * $1.00 - cost` |
| **LOST** (token_id != winning_token) | `0 - cost` (perte totale de la mise) |
| **SELL** (sorti avant resolution) | PnL calcule au moment de la vente |

Detection du gagnant : extraction des `winning_token_ids` depuis la reponse Gamma API (`tokens[].winner == true`), fallback via `clobTokenIds[]` + outcome (YES/NO) pour les marches binaires.

---

## Gestion du risque

### Par trade

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `min_trade_usdc` | Montant minimum par trade | 1 USDC |
| `max_trade_usdc` | Montant maximum par trade | 100 USDC |
| `daily_limit_usdc` | Limite de depenses journaliere | 500 USDC |
| `copy_delay_seconds` | Delai avant copie (eviter front-running) | 0s |
| `manual_confirmation` | Confirmation manuelle au-dessus d'un seuil | false |

### Par position (V3)

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `stop_loss_pct` | % de perte max avant vente auto | 20% |
| `take_profit_pct` | % de gain avant prise de profit | 50% |
| `trailing_stop_pct` | Trailing stop dynamique | 10% |
| `time_exit_hours` | Sortie forcee apres N heures | 72h |
| `scale_out_pct` | % de la position vendu au TP | 50% |

### Par portfolio (V3)

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `max_positions` | Nb max de positions ouvertes | 10 |
| `max_category_exposure_pct` | Exposition max par categorie | 40% |
| `max_direction_bias_pct` | Biais YES/NO max | 70% |

### Circuit Breaker

- **Per-user** : arret apres N echecs consecutifs
- **Global** : arret si pertes depassent un seuil
- Etats : `CLOSED` (normal) -> `OPEN` (arret) -> `HALF_OPEN` (test)
- Cooldown : 1 heure avant re-test

### Rate Limiting

Redis sliding window :

| Scope | Limite | Fenetre |
|-------|--------|---------|
| Commands Telegram | 10 | 60s |
| Trades | 20 | 60s |
| API calls | 100 | 60s |

---

## Securite

| Mesure | Implementation |
|--------|----------------|
| **Cles privees** | Chiffrees AES-256-GCM (sel par utilisateur, cle maitre `ENCRYPTION_KEY`) |
| **Messages sensibles** | Auto-supprimes immediatement sur Telegram |
| **Wallets separes** | Copy wallet et Strategy wallet completement independants |
| **OTP** | Codes a usage unique pour operations sensibles (withdraw, etc.) |
| **Audit logs** | Table immutable `audit_logs` — toute action tracee |
| **Rate limiting** | Redis sliding window, per-user et global |
| **Anti-exploit gas** | 5 checks avant tout refill MATIC |
| **Circuit breaker** | Arret auto en cas d'erreurs repetees |

---

## Telegram — Commandes et navigation

### Hub principal

```
/start  →  Hub d'accueil
           ├── Copy Wallet (gestion copy-trading)
           │     ├── Balance / Positions
           │     ├── Settings (sizing, risk, filtres)
           │     ├── Traders suivis
           │     ├── Signaux & Scoring
           │     ├── Analytics
           │     ├── Deposit / Withdraw / Bridge
           │     └── Pause / Resume
           │
           └── Strategies (suivi de strategies)
                 ├── Liste des strategies
                 ├── Souscrire / Desouscrire
                 ├── Status & PnL
                 ├── Historique trades
                 ├── Settings (fee rate, limites)
                 └── Wallet strategie
```

### Topics Telegram (groupe forum)

Le bot cree automatiquement 7 topics quand il est ajoute comme admin a un groupe forum :

| Topic | Contenu |
|-------|---------|
| Signaux | Notifications de copy-trades executes |
| Traders | Stats et performances des traders suivis |
| Portfolio | Resolutions, PnL, rapport journalier |
| Alertes | Circuit breaker, rate limits, erreurs |
| Admin | Logs admin, health checks |
| Strategies | Signaux de strategies executes |
| Perf Strategies | Resolutions et PnL des strategies |

Mode de notification configurable par utilisateur : `dm` (DM uniquement), `group` (topic uniquement), `both`.

---

## Infrastructure

### Docker Compose

```yaml
services:
  bot:        # Python 3.12 — bot Telegram + dashboard FastAPI
  db:         # PostgreSQL 16 Alpine — donnees persistantes
  redis:      # Redis 7 Alpine — rate limiting + strategy pub/sub
```

- PostgreSQL et Redis ne sont **pas exposes** sur l'hote (securite VPS)
- Dashboard accessible sur le port `8090`
- Volumes persistants : `pgdata`, `redisdata`
- Health checks sur DB et Redis avant demarrage du bot

### Migrations

Les migrations SQL sont executees automatiquement au demarrage (`init_db()` dans `session.py`) :

- `ALTER TABLE` avec SAVEPOINT pour ajouter des colonnes sans casser l'existant
- `CREATE TABLE IF NOT EXISTS` pour les nouvelles tables
- Scripts de reference dans `migrations/`

---

## Deploiement VPS

### Premiere installation

```bash
# 1. Cloner le repo
git clone https://github.com/Torkor29/WENBOT_COPY.git
cd WENBOT_COPY

# 2. Creer et configurer l'environnement
cp .env.example .env
nano .env
# Remplir au minimum : TELEGRAM_TOKEN, ADMIN_CHAT_ID, ENCRYPTION_KEY, POSTGRES_PASSWORD

# 3. Generer la cle de chiffrement
python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Lancer
docker compose up -d --build

# 5. Verifier les logs
docker compose logs -f bot
```

### Mise a jour

```bash
cd WENBOT_COPY
git pull origin v3-smart-analysis
docker compose up -d --build
docker compose logs -f bot
```

### Commandes utiles

```bash
# Voir les logs en temps reel
docker compose logs -f bot

# Redemarrer le bot uniquement
docker compose restart bot

# Acceder a la base PostgreSQL
docker compose exec db psql -U polybot polybot

# Acceder a Redis
docker compose exec redis redis-cli

# Voir les stats des containers
docker compose ps
docker stats

# Backup de la base
docker compose exec db pg_dump -U polybot polybot > backup_$(date +%Y%m%d).sql

# Arreter tout
docker compose down

# Arreter et supprimer les volumes (ATTENTION: perte de donnees)
docker compose down -v
```

---

## Configuration

Toutes les variables sont dans `.env` (voir `.env.example` pour le template complet).

### Variables essentielles

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Token du bot Telegram (@BotFather) |
| `ADMIN_CHAT_ID` | ID Telegram de l'admin |
| `ENCRYPTION_KEY` | Cle AES-256 (64 chars hex) |
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL |
| `DB_URL` | URL de connexion PostgreSQL |
| `REDIS_URL` | URL Redis |
| `FEES_WALLET` | Wallet Polygon pour recevoir les frais |
| `POLYGON_RPC_URL` | RPC Polygon (Alchemy, QuickNode...) |

### Variables optionnelles

| Variable | Defaut | Description |
|----------|--------|-------------|
| `PLATFORM_FEE_RATE` | 0.01 | Frais copy-trade (1%) |
| `MONITOR_POLL_INTERVAL` | 15 | Intervalle de poll (secondes) |
| `STRATEGY_PERF_FEE_RATE` | 0.05 | Performance fee (5%) |
| `STRATEGY_RESOLVER_INTERVAL` | 30 | Poll resolution (secondes) |
| `STRATEGY_MATIC_REFILL_AMOUNT` | 0.1 | Montant refill MATIC |
| `DASHBOARD_ENABLED` | true | Activer le dashboard web |
| `DASHBOARD_PORT` | 8080 | Port interne dashboard |
| `COLLECT_FEES_ONCHAIN` | false | Transferer les frais on-chain |

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| **Langage** | Python 3.12 |
| **Bot Telegram** | python-telegram-bot 21.9 |
| **API Polymarket** | py-clob-client 0.18.0 (CLOB) + Gamma API (positions/marches) |
| **ORM** | SQLAlchemy 2.0 (async) + asyncpg |
| **Base de donnees** | PostgreSQL 16 |
| **Cache / Pub-Sub** | Redis 7 (hiredis) |
| **Blockchain** | Web3.py 7.6 (Polygon) |
| **HTTP** | httpx 0.28 (HTTP/2) |
| **Chiffrement** | cryptography 44.0 (AES-256-GCM) |
| **Scheduler** | APScheduler 3.10 |
| **Web** | FastAPI 0.115 + Uvicorn + Jinja2 |
| **Validation** | Pydantic 2.10 + pydantic-settings |
| **Infra** | Docker + Docker Compose |
| **Tests** | pytest + pytest-asyncio + pytest-cov |

---

## Licence

Projet prive — tous droits reserves.
