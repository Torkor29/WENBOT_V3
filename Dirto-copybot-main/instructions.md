# CLAUDE CODE — WenBot Copytrading Platform

## Instructions

Lis ce fichier en entier avant de commencer. C'est la spec complète d'une plateforme de copytrading Polymarket. Tu dois construire le projet from scratch en suivant l'ordre de la section "Comment procéder" à la fin.

---

## 1. Vision produit

Plateforme de copytrading Polymarket via bot Telegram. Les utilisateurs s'abonnent à des stratégies de trading automatisées. Chaque stratégie tourne dans un container Docker isolé dans Kubernetes. L'utilisateur dépose des USDC.e sur un wallet Polygon créé automatiquement, choisit ses stratégies, et le bot trade pour lui.

**Modèle de fees :**
- Trade fee : variable, minimum 1%, PAS DE MAXIMUM. Choisi par le user. Définit la priorité d'exécution (10% passe avant 3% qui passe avant 1%).
- Performance fee : fixe 5% du PnL net positif quotidien, prélevé à minuit UTC. Même taux pour tout le monde.

**Target :** 6-7 users, 1-3 stratégies, VPS 2 vCPU / 4GB RAM (Espagne ou Irlande Dublin).
**Plateforme :** Polymarket uniquement (marchés crypto 5m/15m pour commencer, extensible).

---

## 2. Stack technique

- **Interface user** : Bot Telegram (aiogram v3 — async natif, meilleur que python-telegram-bot pour ce use case)
- **Backend** : FastAPI (Python 3.11+) — API interne entre composants
- **Base de données** : Supabase (PostgreSQL)
- **Message bus** : Redis (pub/sub pour les signaux + state pour les snapshots)
- **Orchestration** : Kubernetes (K3s — léger, adapté à un VPS)
- **Blockchain** : Polygon — USDC.e (bridged USDC, contract 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174), py_clob_client pour Polymarket CLOB, web3.py pour les transactions USDC.e et MATIC
- **Secret management** : Kubernetes Secrets pour la master key AES-256-GCM
- **CI/CD** : GitHub Actions → Docker Hub → kubectl apply (Phase 2)

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Kubernetes cluster (K3s)                                    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Telegram Bot  │  │  Execution   │  │   Redis      │       │
│  │ (aiogram v3)  │  │   Engine     │  │  (pub/sub)   │       │
│  │               │  │              │  │              │       │
│  │ /start        │  │ Fee queue    │  │ signals:*    │       │
│  │ /subscribe    │  │ Trade exec   │  │ state:*      │       │
│  │ /status       │  │ Resolution   │  │              │       │
│  │ /withdraw     │  │ Perf fee cron│  │              │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │               │
│         │     Supabase    │                  │               │
│         └────────┬────────┘                  │               │
│                  │                           │               │
│  ┌──────────────┐│  ┌──────────────┐         │               │
│  │ Strategy A   ││  │ Strategy B   │─────────┘               │
│  │ (public)     ││  │ (private)    │ Publie signaux          │
│  │ Docker       ││  │ Docker       │ dans Redis              │
│  └──────────────┘│  └──────────────┘                         │
│                  │                                            │
│         ┌────────┴────────┐                                  │
│         │   Supabase DB   │                                  │
│         │ users, trades,  │                                  │
│         │ strategies,     │                                  │
│         │ subscriptions   │                                  │
│         └─────────────────┘                                  │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ Polymarket CLOB  │
              │ (Polygon/USDC.e) │
              └──────────────────┘
```

**Principe de sécurité fondamental :** les strategy pods ne touchent JAMAIS aux wallets. Ils publient des signaux dans Redis, l'execution engine exécute. Même si un strategy pod est compromis, il ne peut pas voler les fonds.

---

## 4. Structure du repo

```
wenbot-copytrade/
├── README.md
├── SPEC.md                          ← ce fichier
├── docker-compose.yml               ← dev local (sans K8s)
├── docker-compose.override.yml      ← overrides dev
├── requirements.txt                 ← deps communes
│
├── bot/                             ← Telegram bot
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                      ← entry point aiogram
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py                 ← /start → onboarding + wallet creation
│   │   ├── deposit.py               ← /deposit → affiche adresse
│   │   ├── balance.py               ← /balance → solde USDC.e + MATIC
│   │   ├── strategies.py            ← /strategies → liste strats publiques
│   │   ├── subscribe.py             ← /subscribe → choix strat + trade size + fee rate
│   │   ├── unsubscribe.py           ← /unsubscribe
│   │   ├── status.py                ← /status → PnL jour/semaine/mois
│   │   ├── history.py               ← /history → derniers 20 trades
│   │   ├── withdraw.py              ← /withdraw → envoie USDC.e vers adresse externe
│   │   ├── settings.py              ← /settings → trade size, fee rate, pause
│   │   └── export_key.py            ← /export_key → clé privée, auto-delete 30s
│   └── utils/
│       ├── __init__.py
│       └── notifications.py         ← envoie des messages aux users (trade placed, win/loss, daily recap)
│
├── engine/                          ← Execution engine
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                      ← entry point
│   ├── executor.py                  ← signal → fee tx → trade FAK → log
│   ├── resolver.py                  ← poll Gamma API → determine winner → update PnL → notify
│   ├── fee_queue.py                 ← trie users par trade_fee_rate DESC, delay entre chaque
│   ├── perf_fee_cron.py             ← cron minuit UTC → calcule PnL net → prélève 5%
│   └── gas_manager.py               ← MATIC refill logic + anti-exploit checks
│
├── wallet/                          ← Wallet manager (librairie partagée)
│   ├── __init__.py
│   ├── create.py                    ← génère EOA wallet Polygon (eth_account)
│   ├── encrypt.py                   ← AES-256-GCM encrypt/decrypt clé privée
│   ├── signer.py                    ← signe ordres Polymarket (py_clob_client) + tx USDC.e (web3.py)
│   └── balance.py                   ← check solde USDC.e + MATIC via RPC
│
├── shared/                          ← Code partagé
│   ├── __init__.py
│   ├── config.py                    ← env vars, constantes
│   ├── supabase_client.py           ← singleton Supabase
│   ├── redis_client.py              ← singleton Redis
│   └── models.py                    ← dataclasses User, Trade, Strategy, Subscription, Signal
│
├── strategies/                      ← Dossier pour les strategy pods
│   ├── example_strategy/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                  ← entry point — analyse marché, publie signal dans Redis
│   │   └── README.md
│   └── README.md                    ← Doc pour créer une nouvelle stratégie
│
├── k8s/                             ← Manifests Kubernetes
│   ├── namespace.yaml
│   ├── redis.yaml                   ← StatefulSet Redis
│   ├── telegram-bot.yaml            ← Deployment bot
│   ├── execution-engine.yaml        ← Deployment engine
│   ├── strategy-template.yaml       ← Template pour deployer une strat
│   ├── network-policy-strategy.yaml ← Isolation des strategy pods
│   └── secrets.yaml.example         ← Template pour les secrets (jamais committé)
│
├── migrations/                      ← SQL Supabase
│   └── 001_initial_schema.sql
│
├── scripts/
│   ├── deploy_strategy.sh           ← Script pour deployer une nouvelle strat
│   └── setup_k3s.sh                 ← Setup K3s sur VPS
│
└── tests/
    ├── test_wallet.py
    ├── test_executor.py
    ├── test_fee_queue.py
    ├── test_gas_manager.py
    └── test_perf_fee.py
```

---

## 5. Schema base de données (Supabase)

Crée le fichier `migrations/001_initial_schema.sql` avec :

```sql
-- Users
CREATE TABLE users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    telegram_id BIGINT UNIQUE NOT NULL,
    telegram_username TEXT,
    wallet_address TEXT NOT NULL,
    encrypted_private_key TEXT NOT NULL,
    trade_fee_rate FLOAT DEFAULT 0.01 CHECK (trade_fee_rate >= 0.01),
    is_active BOOLEAN DEFAULT true,
    max_trade_size FLOAT DEFAULT 4.0,
    max_trades_per_day INTEGER DEFAULT 50,
    is_paused BOOLEAN DEFAULT false,
    matic_refills_count INTEGER DEFAULT 0,
    matic_total_sent FLOAT DEFAULT 0,
    last_matic_refill_at TIMESTAMPTZ,
    trades_today INTEGER DEFAULT 0,
    trades_today_reset_at DATE DEFAULT CURRENT_DATE
);

-- Strategies
CREATE TABLE strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    docker_image TEXT NOT NULL,
    version TEXT DEFAULT '1.0.0',
    status TEXT DEFAULT 'testing' CHECK (status IN ('active', 'paused', 'testing')),
    visibility TEXT DEFAULT 'private' CHECK (visibility IN ('public', 'private')),
    markets JSONB DEFAULT '[]'::jsonb,
    min_trade_size FLOAT DEFAULT 2.0,
    max_trade_size FLOAT DEFAULT 10.0,
    execution_delay_ms INTEGER DEFAULT 100,
    track_record_since TIMESTAMPTZ,
    total_trades INTEGER DEFAULT 0,
    total_pnl FLOAT DEFAULT 0,
    win_rate FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Subscriptions (user × strategy)
CREATE TABLE subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    strategy_id TEXT REFERENCES strategies(id) ON DELETE CASCADE,
    trade_size FLOAT NOT NULL CHECK (trade_size >= 1.0),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, strategy_id)
);

-- Trades
CREATE TABLE trades (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    user_id UUID REFERENCES users(id),
    strategy_id TEXT REFERENCES strategies(id),
    market_slug TEXT NOT NULL,
    token_id TEXT,
    direction TEXT,
    side TEXT CHECK (side IN ('YES', 'NO')),
    entry_price FLOAT,
    amount_usdc FLOAT,
    trade_fee_rate FLOAT,
    trade_fee_amount FLOAT,
    trade_fee_tx_hash TEXT,
    order_tx_hash TEXT,
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PLACED', 'FILLED', 'FAILED', 'SKIPPED')),
    result TEXT CHECK (result IN ('WON', 'LOST', NULL)),
    pnl FLOAT,
    execution_priority INTEGER,
    execution_delay_ms INTEGER,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_trades_user ON trades(user_id);
CREATE INDEX idx_trades_strategy ON trades(strategy_id);
CREATE INDEX idx_trades_created ON trades(created_at);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_market ON trades(market_slug);

-- Daily performance fees
CREATE TABLE daily_performance_fees (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    user_id UUID REFERENCES users(id),
    date DATE NOT NULL,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    total_pnl FLOAT,
    perf_fee_rate FLOAT DEFAULT 0.05,
    perf_fee_amount FLOAT,
    perf_fee_tx_hash TEXT,
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SENT', 'SKIPPED', 'FAILED')),
    UNIQUE(user_id, date)
);

-- Strategy signals (audit trail)
CREATE TABLE strategy_signals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    strategy_id TEXT REFERENCES strategies(id),
    action TEXT NOT NULL,
    side TEXT,
    market_slug TEXT NOT NULL,
    token_id TEXT,
    max_price FLOAT,
    confidence FLOAT,
    subscribers_count INTEGER DEFAULT 0,
    executed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    total_volume FLOAT DEFAULT 0
);

CREATE INDEX idx_signals_strategy ON strategy_signals(strategy_id);
CREATE INDEX idx_signals_created ON strategy_signals(created_at);

-- Admin alerts log
CREATE TABLE admin_alerts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    alert_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    user_id UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}'::jsonb,
    acknowledged BOOLEAN DEFAULT false
);
```

---

## 6. Composants détaillés

### 6.1 Wallet manager (`wallet/`)

```python
# wallet/create.py
# Utilise eth_account pour générer un wallet EOA Polygon
# from eth_account import Account
# account = Account.create()
# Retourne: wallet_address, private_key (en clair, à chiffrer immédiatement)

# wallet/encrypt.py
# AES-256-GCM avec la master key depuis os.environ["ENCRYPTION_MASTER_KEY"]
# encrypt(private_key: str) → encrypted_blob: str (base64)
# decrypt(encrypted_blob: str) → private_key: str
# La master key est un hex string de 64 chars (32 bytes)
# Utilise cryptography.fernet ou mieux: cryptography.hazmat.primitives.ciphers.aead.AESGCM

# wallet/signer.py
# Deux fonctions de signing :
# 1. sign_polymarket_order(private_key, order_args) → signed order via py_clob_client
#    - Crée un ClobClient temporaire avec la clé
#    - client = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=private_key, signature_type=0)
#    - client.set_api_creds(client.create_or_derive_api_creds())
#    - signed = client.create_order(order_args)
#    - resp = client.post_order(signed, OrderType.FAK)
#
# 2. send_usdc_transfer(private_key, to_address, amount_usdc) → tx_hash
#    - Utilise web3.py pour envoyer un ERC-20 transfer USDC.e sur Polygon
#    - USDC.e contract: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
#    - Attention: USDC.e a 6 décimales, pas 18
#    - amount_wei = int(amount_usdc * 1_000_000)
#
# 3. send_matic_transfer(private_key, to_address, amount_matic) → tx_hash
#    - Transfert natif MATIC (POL) pour le gas

# wallet/balance.py
# get_usdc_balance(wallet_address) → float (en USDC.e)
# get_matic_balance(wallet_address) → float (en MATIC)
# Utilise web3.py avec un RPC Polygon public ou Alchemy
```

### 6.2 Execution engine (`engine/`)

```python
# engine/fee_queue.py
# La priority queue qui trie les users par trade_fee_rate DESC
#
# async def execute_for_subscribers(signal: Signal, subscribers: list[Subscription]):
#     # Trie par fee DESC
#     sorted_subs = sorted(subscribers, key=lambda s: s.user.trade_fee_rate, reverse=True)
#     
#     for priority, sub in enumerate(sorted_subs):
#         user = sub.user
#         strategy = signal.strategy
#         
#         # 1. Check USDC.e balance
#         balance = await get_usdc_balance(user.wallet_address)
#         if balance < sub.trade_size:
#             await notify_user(user, "Solde insuffisant")
#             continue
#         
#         # 2. Check MATIC + refill si nécessaire
#         await check_and_refill_matic(user)
#         
#         # 3. Check daily trade limit
#         if user.trades_today >= user.max_trades_per_day:
#             continue
#         
#         # 4. Calculate trade fee
#         fee_amount = sub.trade_size * user.trade_fee_rate
#         trade_amount = sub.trade_size - fee_amount
#         
#         # 5. Enforce minimum fee rate
#         if user.trade_fee_rate < 0.01:
#             user.trade_fee_rate = 0.01  # safety net
#         
#         # 6. Send fee tx
#         fee_tx = await send_usdc_transfer(user.pk, WENBOT_FEE_WALLET, fee_amount)
#         
#         # 7. Place order on Polymarket
#         order_result = await place_fak_order(user.pk, signal, trade_amount)
#         
#         # 8. Log trade
#         await insert_trade(user, signal, fee_tx, order_result, priority)
#         
#         # 9. Notify
#         await notify_trade_placed(user, signal, trade_amount, entry_price)
#         
#         # 10. Delay before next user
#         await asyncio.sleep(strategy.execution_delay_ms / 1000)

# engine/gas_manager.py
# PROTECTIONS ANTI-EXPLOIT (TOUTES OBLIGATOIRES) :
#
# async def check_and_refill_matic(user: User):
#     matic_balance = await get_matic_balance(user.wallet_address)
#     if matic_balance >= 0.01:
#         return  # Pas besoin de refill
#     
#     # CHECK 1: Cap lifetime
#     if user.matic_refills_count >= 3 or user.matic_total_sent >= 0.3:
#         await alert_admin("MATIC cap reached", user)
#         return
#     
#     # CHECK 2: USDC.e minimum
#     usdc_balance = await get_usdc_balance(user.wallet_address)
#     if usdc_balance < 2.0:
#         return  # Pas de refill sans USDC.e
#     
#     # CHECK 3: Rate limit 1x/24h
#     if user.last_matic_refill_at and (now() - user.last_matic_refill_at).total_seconds() < 86400:
#         return
#     
#     # CHECK 4: Vérifier que le MATIC précédent a été consommé en gas
#     # (pas transféré vers une autre adresse)
#     if not await verify_matic_consumed_as_gas(user.wallet_address):
#         await flag_user(user, "MATIC drain suspect")
#         await alert_admin("Suspect MATIC drain", user)
#         return
#     
#     # OK, refill
#     tx = await send_matic_transfer(WENBOT_PK, user.wallet_address, 0.1)
#     user.matic_refills_count += 1
#     user.matic_total_sent += 0.1
#     user.last_matic_refill_at = now()
#     await update_user(user)

# engine/perf_fee_cron.py
# Tourne comme un asyncio task dans le même process que l'execution engine
# Se déclenche à minuit UTC
#
# async def daily_perf_fee_job():
#     while True:
#         await sleep_until_midnight_utc()
#         
#         yesterday = date.today() - timedelta(days=1)
#         users = await get_active_users()
#         
#         for user in users:
#             trades = await get_resolved_trades(user.id, yesterday)
#             if not trades:
#                 continue
#             
#             total_pnl = sum(t.pnl for t in trades)
#             
#             if total_pnl <= 0:
#                 await insert_perf_fee(user, yesterday, total_pnl, 0, "SKIPPED")
#                 continue
#             
#             perf_fee = total_pnl * 0.05
#             
#             # Check balance
#             balance = await get_usdc_balance(user.wallet_address)
#             if balance < perf_fee:
#                 perf_fee = balance  # Take what's available
#             
#             if perf_fee < 0.01:  # Don't bother with dust
#                 await insert_perf_fee(user, yesterday, total_pnl, 0, "SKIPPED")
#                 continue
#             
#             tx = await send_usdc_transfer(user.pk, WENBOT_FEE_WALLET, perf_fee)
#             await insert_perf_fee(user, yesterday, total_pnl, perf_fee, "SENT", tx)
#             
#             # Notify user
#             wins = sum(1 for t in trades if t.result == 'WON')
#             await notify_daily_recap(user, len(trades), wins, total_pnl, perf_fee)
```

### 6.3 Bot Telegram (`bot/`)

```python
# bot/handlers/start.py
# /start flow:
# 1. Check si user existe déjà (telegram_id)
# 2. Si non: créer wallet EOA → chiffrer clé → insert user dans Supabase
# 3. Message de bienvenue avec l'adresse du wallet pour déposer
# 4. Inline keyboard avec les actions principales

# bot/handlers/subscribe.py
# /subscribe flow:
# 1. Liste les stratégies publiques actives (status='active', visibility='public')
# 2. User choisit une stratégie (inline keyboard)
# 3. User choisit trade_size (inline keyboard: 2$, 4$, 6$, custom)
# 4. User choisit trade_fee_rate (inline keyboard: 1%, 2%, 3%, 5%, custom)
#    → Message: "Plus le fee est élevé, plus vos trades sont prioritaires"
# 5. Confirmation → insert subscription dans Supabase
# 6. Message: "Abonné à {strategy_name}! Vos trades seront exécutés automatiquement."

# bot/handlers/status.py
# /status flow:
# 1. Query trades du user (aujourd'hui, cette semaine, ce mois)
# 2. Calcule PnL par période
# 3. Affiche:
#    - Solde USDC.e actuel
#    - PnL aujourd'hui / semaine / mois
#    - Stratégies actives
#    - Trades aujourd'hui: X wins / Y losses
#    - Fee rate actuel + position dans la queue

# bot/handlers/withdraw.py
# /withdraw flow:
# 1. Demande l'adresse de destination (Polygon)
# 2. Demande le montant (ou "max")
# 3. Validation de l'adresse (checksum ETH)
# 4. Confirmation avec recap
# 5. Envoie tx USDC.e
# 6. Message avec le tx hash

# bot/handlers/export_key.py
# /export_key flow:
# 1. Warning message: "Votre clé privée va être affichée. Ce message s'auto-supprimera dans 30s."
# 2. Confirmation requise
# 3. Déchiffre la clé
# 4. Envoie la clé dans un message
# 5. asyncio.sleep(30) → delete le message
# 6. Rate limit: 1x par 24h (check last_export_at)
```

### 6.4 Strategy pod interface (`strategies/`)

```python
# strategies/example_strategy/main.py
# Template minimal pour une stratégie
#
# Une stratégie DOIT :
# 1. Se connecter à Redis
# 2. Analyser le marché (à sa façon)
# 3. Quand elle décide de trader, publier un signal :
#
# signal = {
#     "strategy_id": "strat_example_v1",
#     "action": "BUY",
#     "side": "YES",                           # ou "NO"
#     "market_slug": "btc-updown-5m-1774013700",
#     "token_id": "24309598195452...",
#     "max_price": 0.65,                       # prix max acceptable
#     "confidence": 0.82,                       # optionnel
#     "timestamp": time.time()
# }
# await redis.publish(f"signals:{strategy_id}", json.dumps(signal))
#
# Une stratégie ne doit JAMAIS :
# - Accéder aux wallets des users
# - Placer des ordres directement sur Polymarket
# - Accéder aux secrets Kubernetes
# - Communiquer avec d'autres pods que Redis

# strategies/README.md
# Documentation pour les développeurs de stratégies :
# - Comment créer une nouvelle stratégie
# - Format du signal Redis
# - Comment tester en local
# - Comment déployer via CI/CD
```

---

## 7. Kubernetes manifests (`k8s/`)

### Redis
```yaml
# k8s/redis.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: wenbot-prod
spec:
  serviceName: redis
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: wenbot-prod
spec:
  selector:
    app: redis
  ports:
    - port: 6379
```

### Network Policy (CRITIQUE)
```yaml
# k8s/network-policy-strategy.yaml
# Empêche les strategy pods d'accéder aux secrets et aux autres pods
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: strategy-isolation
  namespace: wenbot-prod
spec:
  podSelector:
    matchLabels:
      role: strategy
  policyTypes:
    - Egress
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - port: 6379
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443
        - port: 80
```

---

## 8. Docker Compose (dev local)

Pour le développement, tout tourne en local sans K8s :

```yaml
# docker-compose.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  telegram-bot:
    build: ./bot
    env_file: .env
    depends_on:
      - redis
    volumes:
      - ./shared:/app/shared
      - ./wallet:/app/wallet

  execution-engine:
    build: ./engine
    env_file: .env
    depends_on:
      - redis
    volumes:
      - ./shared:/app/shared
      - ./wallet:/app/wallet

  # Stratégie exemple (optionnel pour dev)
  strategy-example:
    build: ./strategies/example_strategy
    env_file: .env
    depends_on:
      - redis
    volumes:
      - ./shared:/app/shared
```

---

## 9. Variables d'environnement (`.env.example`)

```bash
# Telegram
TELEGRAM_TOKEN=your_telegram_bot_token

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...

# Redis
REDIS_URL=redis://localhost:6379

# Blockchain
POLYGON_RPC_URL=https://polygon-rpc.com
ALCHEMY_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/your_key
USDC_CONTRACT=0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174

# WenBot wallet (receives fees)
WENBOT_FEE_WALLET=0x...your_fee_wallet_address
WENBOT_PRIVATE_KEY=0x...your_fee_wallet_pk

# Encryption
ENCRYPTION_MASTER_KEY=64_hex_chars_here

# Polymarket
POLYMARKET_CLOB_HOST=https://clob.polymarket.com
POLYMARKET_CHAIN_ID=137
```

---

## 10. Sécurité — règles obligatoires

1. **ENCRYPTION_MASTER_KEY** n'est JAMAIS dans le code, JAMAIS dans Supabase, JAMAIS dans les env vars des strategy pods. Uniquement dans K8s Secrets (ou .env pour le dev local).

2. **Les strategy pods** n'ont accès qu'à Redis et à Internet (Binance WS, Polymarket API). PAS à l'execution engine, PAS aux K8s Secrets, PAS à Supabase directement (en prod, ils passent par Redis → execution engine).

3. **Trade fee minimum** : enforce `trade_fee_rate >= 0.01` à CHAQUE trade dans l'execution engine, pas seulement à l'inscription.

4. **MATIC anti-exploit** : TOUTES les 5 vérifications DOIVENT être implémentées (cap lifetime, condition USDC, rate limit, vérification consommation, monitoring). Voir section 6.2.

5. **/export_key** : message auto-delete après 30s, rate limit 1x/24h, log dans admin_alerts.

6. **Aucun log** ne doit contenir une clé privée, ni en clair ni chiffrée.

---

## 11. Comment procéder (ORDRE OBLIGATOIRE)

### Étape 1 : Setup du repo
- Crée la structure de dossiers complète
- Crée `requirements.txt` pour chaque composant
- Crée `.env.example`
- Crée `.gitignore` (exclure .env, __pycache__, *.pyc, .venv, k8s/secrets.yaml)
- Crée un README.md basique

### Étape 2 : Shared + Wallet
- `shared/config.py`, `shared/models.py`, `shared/supabase_client.py`, `shared/redis_client.py`
- `wallet/create.py`, `wallet/encrypt.py`, `wallet/signer.py`, `wallet/balance.py`
- Tests : `tests/test_wallet.py`

### Étape 3 : Migration SQL
- `migrations/001_initial_schema.sql` (copier depuis cette spec)

### Étape 4 : Execution engine
- `engine/main.py` — entry point avec Redis subscriber + perf fee cron
- `engine/fee_queue.py` — priority queue + execution séquentielle
- `engine/executor.py` — fee tx + trade FAK
- `engine/resolver.py` — poll Gamma API + PnL update
- `engine/gas_manager.py` — MATIC refill + anti-exploit
- `engine/perf_fee_cron.py` — job minuit UTC
- Tests : `tests/test_executor.py`, `tests/test_fee_queue.py`, `tests/test_gas_manager.py`, `tests/test_perf_fee.py`

### Étape 5 : Bot Telegram
- `bot/main.py` — setup aiogram, register handlers
- Tous les handlers dans `bot/handlers/`
- `bot/utils/notifications.py`

### Étape 6 : Strategy example
- `strategies/example_strategy/main.py` — bot minimal qui publie un signal toutes les 5 minutes
- `strategies/README.md` — doc pour créer une strat

### Étape 7 : Docker
- Dockerfiles pour bot, engine, example_strategy
- `docker-compose.yml` pour dev local

### Étape 8 : Kubernetes
- Tous les manifests dans `k8s/`
- Network policies
- `scripts/setup_k3s.sh`
- `scripts/deploy_strategy.sh`

### Étape 9 : Tests end-to-end
- Tester le flow complet en local : strategy publie signal → engine reçoit → fee tx (mock) → trade (mock) → resolution → PnL → notification
- Tester le perf fee cron
- Tester l'anti-exploit MATIC

**Commence par l'étape 1. Montre-moi le résultat et demande confirmation avant de passer à l'étape suivante.**
