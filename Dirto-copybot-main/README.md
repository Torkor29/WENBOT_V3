# Dirto Copybot

Plateforme de **copy-trading automatisée** sur [Polymarket](https://polymarket.com) via un bot Telegram. Les utilisateurs s'abonnent à des stratégies, et chaque signal généré par une stratégie est automatiquement exécuté sur le portefeuille de chaque abonné.

---

## Table des matières

- [Architecture](#architecture)
- [Stack technique](#stack-technique)
- [Structure du projet](#structure-du-projet)
- [Flux de fonctionnement](#flux-de-fonctionnement)
  - [Signal → Exécution](#signal--exécution)
  - [BUY Flow](#buy-flow)
  - [SELL Flow](#sell-flow)
  - [Résolution & Redeem](#resolution--redeem)
  - [Frais](#frais)
- [Bot Telegram](#bot-telegram)
- [Base de données](#base-de-donnees)
- [Wallet & Sécurité](#wallet--securite)
- [Infrastructure & Déploiement](#infrastructure--deploiement)
  - [K3s (Kubernetes)](#k3s-kubernetes)
  - [Portainer](#portainer)
  - [WireGuard](#wireguard)
- [Configuration](#configuration)
- [Installation locale](#installation-locale)
- [Déploiement production](#deploiement-production)
- [Commandes Make](#commandes-make)
- [Tests](#tests)
- [Créer une stratégie](#creer-une-strategie)

---

## Architecture

```
┌──────────────┐     Redis PubSub      ┌──────────────────┐
│   Strategy   │ ────signals:*────────> │  Execution       │
│   Pods       │                        │  Engine          │
└──────────────┘                        │                  │
                                        │  ┌─fee_queue     │
                                        │  ┌─executor      │
┌──────────────┐                        │  ┌─resolver      │
│  Telegram    │                        │  └─perf_fee_cron │
│  Bot         │                        └──────┬───────────┘
│  (aiogram)   │                               │
└──────┬───────┘                               │
       │                                       │
       │         ┌─────────────┐               │
       └────────>│  Supabase   │<──────────────┘
                 │  (Postgres) │
                 └─────────────┘
                        │
                 ┌──────┴──────┐
                 │  Polygon    │
                 │  Blockchain │
                 │  (CLOB API) │
                 └─────────────┘
```

### Composants principaux

| Composant | Rôle |
|-----------|------|
| **Telegram Bot** | Interface utilisateur : inscription, dépôt, retrait, abonnements, statut, historique, paramètres |
| **Execution Engine** | Écoute Redis, orchestre l'exécution des trades pour chaque abonné |
| **Strategy Pods** | Conteneurs indépendants qui analysent les marchés et publient des signaux sur Redis |
| **Supabase** | Base de données PostgreSQL : utilisateurs, stratégies, abonnements, trades, frais |
| **Redis** | Bus de messages entre stratégies et engine (pub/sub `signals:*`) |
| **Polygon (CLOB)** | Polymarket CLOB API pour les ordres + blockchain Polygon pour les transferts USDC.e |

---

## Stack technique

- **Python 3.11+**
- **aiogram v3** — Framework Telegram bot (async, FSM, inline keyboards)
- **py_clob_client** — SDK officiel Polymarket CLOB
- **web3.py** — Interactions blockchain (transferts ERC-20, MATIC)
- **Supabase** — PostgreSQL managé (BaaS)
- **Redis 7** — Pub/sub pour les signaux de stratégies
- **K3s** — Kubernetes léger (single-node)
- **Docker** — Conteneurisation de tous les services
- **Portainer CE** — UI web pour gérer les deployments Kubernetes
- **WireGuard** — VPN pour accès sécurisé à Portainer
- **Traefik** — Ingress controller (Kubernetes)
- **cryptography** — AES-256-GCM pour le chiffrement des clés privées

---

## Structure du projet

```
copytrade/
├── bot/                          # Telegram bot
│   ├── handlers/                 # Commandes et callbacks
│   │   ├── start.py              # /start + menu principal (8 boutons)
│   │   ├── balance.py            # Solde USDC.e + MATIC
│   │   ├── deposit.py            # Adresse de dépôt
│   │   ├── withdraw.py           # Retrait USDC.e (FSM multi-étapes)
│   │   ├── strategies.py         # Liste des stratégies publiques
│   │   ├── subscribe.py          # Abonnement à une stratégie (FSM)
│   │   ├── unsubscribe.py        # Désabonnement
│   │   ├── status.py             # Statut du compte + PnL
│   │   ├── history.py            # Historique des 20 derniers trades
│   │   ├── settings.py           # Paramètres (taille, frais, pause)
│   │   └── export_key.py         # Export clé privée (auto-delete 30s)
│   ├── utils/
│   │   └── notifications.py      # Notifications push
│   ├── main.py                   # Entry point bot
│   ├── Dockerfile
│   └── requirements.txt
│
├── engine/                       # Moteur d'exécution
│   ├── main.py                   # Entry point (Redis listener + background tasks)
│   ├── executor.py               # Orchestration BUY/SELL par utilisateur
│   ├── fee_queue.py              # File de priorité (fee_rate DESC)
│   ├── resolver.py               # Résolution des marchés (Gamma API)
│   ├── gas_manager.py            # Refill MATIC automatique (5 checks anti-exploit)
│   ├── perf_fee_cron.py          # Collecte des frais de performance (midnight UTC)
│   ├── Dockerfile
│   └── requirements.txt
│
├── wallet/                       # Gestion des wallets
│   ├── create.py                 # Génération de wallets EOA (eth_account)
│   ├── encrypt.py                # Chiffrement AES-256-GCM des clés privées
│   ├── balance.py                # Queries USDC.e et MATIC (web3.py)
│   └── signer.py                 # Trading Polymarket CLOB + transferts web3
│
├── shared/                       # Modules partagés
│   ├── config.py                 # Variables d'environnement centralisées
│   ├── models.py                 # Dataclasses (User, Strategy, Trade, Signal...)
│   ├── redis_client.py           # Client Redis async singleton
│   └── supabase_client.py        # Client Supabase singleton
│
├── strategies/                   # Stratégies de trading
│   └── example_strategy/         # Stratégie d'exemple
│       ├── main.py               # Publie des signaux fictifs toutes les 5min
│       ├── Dockerfile
│       └── requirements.txt
│
├── scripts/
│   ├── setup_infra.sh            # Setup complet : WireGuard, K3s, Docker, deploy
│   ├── setup_k3s.sh              # Installation K3s standalone
│   ├── deploy_strategy.sh        # Deploy une stratégie sur K3s
│   └── test_strategy.py          # Simulateur de signaux (strat_test_v1)
│
├── k8s/                          # Manifestes Kubernetes
│   ├── namespace.yaml            # Namespace wenbot-prod
│   ├── redis.yaml                # Redis StatefulSet + Service + NodePort
│   ├── execution-engine.yaml     # Deployment engine
│   ├── telegram-bot.yaml         # Deployment bot
│   ├── portainer.yaml            # Portainer CE (deploy + ingress)
│   ├── traefik-config.yaml       # HelmChartConfig (WireGuard-only binding)
│   ├── network-policy-strategy.yaml
│   ├── strategy-template.yaml    # Template pour stratégies
│   └── secrets.yaml.example      # Exemple de secrets
│
├── migrations/                   # Migrations SQL standalone
│   ├── 001_initial_schema.sql
│   └── 002_test_strategy.sql
│
├── supabase/                     # Migrations Supabase CLI
│   └── migrations/
│       ├── 001_initial_schema.sql
│       └── 20260328134138_test_strategy.sql
│
├── tests/                        # Tests unitaires (pytest)
│   ├── test_executor.py
│   ├── test_fee_queue.py
│   ├── test_gas_manager.py
│   ├── test_perf_fee.py
│   └── test_wallet.py
│
├── reference/
│   └── live_executor.py          # Code de référence original (LiveExecutor)
│
├── .env.example                  # Template des variables d'environnement
├── docker-compose.yml            # Dev local
├── Makefile                      # Commandes rapides
└── conftest.py                   # Fixtures pytest
```

---

## Flux de fonctionnement

### Signal → Exécution

```
Strategy Pod                Engine                              Polygon
    │                          │                                   │
    │── publish signal ──────> │                                   │
    │   (Redis signals:*)      │── parse signal                    │
    │                          │── log to strategy_signals table   │
    │                          │── fetch active subscribers        │
    │                          │── sort by fee_rate DESC           │
    │                          │                                   │
    │                          │── for each subscriber:            │
    │                          │   ├─ check daily limit            │
    │                          │   ├─ check USDC balance (BUY)     │
    │                          │   ├─ check/refill MATIC gas       │
    │                          │   ├─ decrypt private key          │
    │                          │   ├─ send fee (BUY only)  ──────> │
    │                          │   ├─ place order (CLOB) ────────> │
    │                          │   └─ insert trade record          │
```

### BUY Flow

1. **Decrypt** la clé privée de l'utilisateur (AES-256-GCM)
2. **Calculer le frais** : `fee = trade_size * trade_fee_rate`
3. **Envoyer le frais** en USDC.e vers `WENBOT_FEE_WALLET` (transfert ERC-20 via web3.py)
4. **Créer un ClobClient éphémère** (signature_type=0, EOA, dérive API creds)
5. **Récupérer le best_ask** depuis l'orderbook CLOB
6. **Guardrail** : refuser si `best_ask > max_price`
7. **Pré-approuver** le conditional token
8. **Calculer buy_price** : `min(best_ask + 0.05, 0.95)`
9. **Passer l'ordre FOK** (Fill or Kill) → si échec → **fallback FAK** (Fill and Kill)
10. **Enregistrer** le trade dans Supabase (shares, cost, entry_price, status)

### SELL Flow

1. **Decrypt** la clé privée
2. **Pas de frais** (déjà pris au BUY)
3. **Créer un ClobClient éphémère**
4. **Boucle de retry** (max 12 tentatives, 5s entre chaque) :
   - Vérifier le solde réel de shares
   - Attendre si les shares ne sont pas encore settled
   - Récupérer le best_bid
   - `sell_price = max(best_bid - 0.05, 0.01)`
   - FOK au 1er essai → FAK ensuite
   - Détection des erreurs fatales (marché fermé/résolu) → abort
5. **Enregistrer** le trade (sold, remaining, received)

### Résolution & Redeem

Le **resolver** tourne en boucle (toutes les 30s) :

1. Récupère les trades non résolus (`PLACED` / `FILLED`, `resolved_at IS NULL`)
2. Groupe par `market_slug`
3. Interroge la **Gamma API** (`gamma-api.polymarket.com/markets?slug=...`)
4. Si le marché est résolu :
   - Détermine WON/LOST en comparant `side` avec `outcome`
   - Calcule le PnL :
     - **BUY WON** : `(shares * 1.0) - cost`
     - **BUY LOST** : `0 - cost`
     - **SELL** : `received` (USDC recu)
   - Met à jour le trade + les stats de la stratégie
5. **Redeem** automatique pour les trades gagnants via Builder API + RelayClient

### Frais

| Type | Taux | Quand |
|------|------|-------|
| **Trade Fee** | 1-20% (configurable par user) | À chaque BUY (avant l'ordre) |
| **Performance Fee** | 5% du PnL positif | Quotidien à minuit UTC |

- Le trade fee sert aussi de **mécanisme de priorité** : plus le taux est élevé, plus l'exécution est rapide (tri `fee_rate DESC`)
- Le performance fee n'est collecté que si le PnL journalier est **positif** et le montant est >= $0.01
- Si le solde est insuffisant pour le perf fee, il est ajusté au solde disponible

---

## Bot Telegram

Interface entièrement basée sur des **boutons inline** (pas de commandes slash visibles).

### Menu principal (8 boutons)

| Bouton | Action |
|--------|--------|
| Balance | Affiche USDC.e + MATIC + adresse wallet |
| Deposit | Affiche l'adresse de dépôt (Polygon USDC.e) |
| Strategies | Liste les stratégies publiques actives |
| Status | PnL jour/semaine/mois, trades du jour, strategies actives |
| History | 20 derniers trades avec PnL |
| Withdraw | Retrait USDC.e (FSM : adresse → montant → confirmation) |
| Settings | Trade size, fee rate, max trades/day, pause/resume |
| Export Key | Export clé privée (auto-delete après 30s, rate limit 24h) |

### Navigation

- Chaque écran a un bouton **"Back to menu"** pour revenir au menu principal
- Le flow d'abonnement est un **FSM multi-étapes** : choix stratégie → taille → fee rate → confirmation
- Le retrait est également un **FSM** : adresse destination → montant → confirmation → exécution

---

## Base de données

### Schéma (Supabase / PostgreSQL)

```
users
├── id (UUID, PK)
├── telegram_id (BIGINT, UNIQUE)
├── telegram_username
├── wallet_address
├── encrypted_private_key
├── trade_fee_rate (FLOAT, default 0.01, min 0.01)
├── is_active, is_paused
├── max_trade_size (default 4.0)
├── max_trades_per_day (default 50)
├── matic_refills_count, matic_total_sent, last_matic_refill_at
└── trades_today, trades_today_reset_at

strategies
├── id (TEXT, PK)
├── name, description
├── docker_image, version
├── status (active | paused | testing)
├── visibility (public | private)
├── markets (JSONB)
├── min_trade_size, max_trade_size
├── execution_delay_ms
├── total_trades, total_pnl, win_rate
└── track_record_since

subscriptions
├── id (UUID, PK)
├── user_id → users(id)
├── strategy_id → strategies(id)
├── trade_size (min 1.0)
├── is_active
└── UNIQUE(user_id, strategy_id)

trades
├── id (UUID, PK)
├── user_id → users(id)
├── strategy_id → strategies(id)
├── market_slug, token_id
├── direction (BUY | SELL)
├── side (YES | NO)
├── entry_price, amount_usdc, shares, received
├── trade_fee_rate, trade_fee_amount, trade_fee_tx_hash
├── order_tx_hash
├── status (PENDING | PLACED | FILLED | FAILED | SKIPPED)
├── result (WON | LOST)
├── pnl
├── execution_priority, execution_delay_ms
└── resolved_at

daily_performance_fees
├── id (UUID, PK)
├── user_id → users(id)
├── date (UNIQUE per user)
├── total_trades, wins, losses, total_pnl
├── perf_fee_rate, perf_fee_amount, perf_fee_tx_hash
└── status (PENDING | SENT | SKIPPED | FAILED)

strategy_signals
├── id (UUID, PK)
├── strategy_id → strategies(id)
├── action, side, market_slug, token_id
├── max_price, confidence, signal_timestamp
└── subscribers_count, executed_count, skipped_count, total_volume

admin_alerts
├── id (UUID, PK)
├── alert_type, severity (info | warning | critical)
├── message
├── user_id → users(id)
├── metadata (JSONB)
└── acknowledged
```

---

## Wallet & Sécurité

### Génération de wallet

Chaque utilisateur reçoit un wallet EOA généré via `eth_account.Account.create()`. La clé privée est immédiatement chiffrée et stockée dans Supabase.

### Chiffrement AES-256-GCM

- Clé de chiffrement : `ENCRYPTION_MASTER_KEY` (32 bytes / 64 hex chars)
- Algorithme : AES-256-GCM avec nonce aléatoire de 12 bytes
- Format stocké : `base64(nonce || ciphertext)`
- La clé privée n'est décryptée qu'au moment de l'exécution d'un trade, et nettoyée de la mémoire immédiatement après

### MATIC Gas Manager

Le système refill automatiquement le MATIC (gas Polygon) des utilisateurs avec **5 protections anti-exploit** :

1. **Lifetime cap** : maximum `MATIC_MAX_REFILLS` refills par utilisateur (default: 3)
2. **Total cap** : maximum `MATIC_MAX_TOTAL` MATIC envoye au total (default: 0.3)
3. **Solde USDC minimum** : le refill n'est fait que si l'utilisateur a >= `MIN_USDC_FOR_MATIC_REFILL` (default: $2)
4. **Rate limit** : 1 refill par 24h (`MATIC_REFILL_COOLDOWN_SECONDS`)
5. **Projection cap** : vérifie que le refill ne dépasse pas le total lifetime

Chaque anomalie génère une **admin alert** dans la table `admin_alerts`.

### Export de clé privée

- Affiche la clé dans un **spoiler Telegram** (`<tg-spoiler>`)
- Le message s'**auto-delete** après 30 secondes
- **Rate limit** : 1 export par 24h (via `admin_alerts` table)
- Un enregistrement d'audit est créé à chaque export

---

## Infrastructure & Déploiement

### K3s (Kubernetes)

Le déploiement production utilise **K3s** (Kubernetes léger, single-node) avec Docker comme runtime de conteneurs.

```
K3s Cluster (single-node)
├── Namespace: wenbot-prod
│   ├── Redis (StatefulSet + PVC + NodePort 30379)
│   ├── Execution Engine (Deployment, 1 replica)
│   ├── Telegram Bot (Deployment, 1 replica)
│   └── Strategy Pods (Deployment par stratégie)
├── Namespace: portainer
│   └── Portainer CE (Deployment + PVC + Ingress)
└── Traefik (Ingress Controller, bind WireGuard IP)
```

### Portainer

UI web pour gérer les deployments Kubernetes, accessible sur `portainer.vqnirr.me` via WireGuard uniquement.

### WireGuard

Le VPS rejoint un réseau WireGuard existant en tant que peer. Traefik est bind sur l'IP WireGuard (`10.1.0.9`), ce qui rend Portainer inaccessible depuis l'internet public.

**iptables** bloque les ports 80/443 sur l'interface publique :
```
iptables -I INPUT -i <public_iface> -p tcp --dport 80 -j DROP
iptables -I INPUT -i <public_iface> -p tcp --dport 443 -j DROP
```

---

## Configuration

Copier `.env.example` vers `.env` et remplir toutes les valeurs :

```bash
cp .env.example .env
```

### Variables requises

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Token du bot Telegram (via @BotFather) |
| `SUPABASE_URL` | URL du projet Supabase |
| `SUPABASE_KEY` | Clé d'API Supabase (anon ou service_role) |
| `REDIS_URL` | URL Redis (default: `redis://localhost:6379`) |
| `POLYGON_RPC_URL` | RPC Polygon (default: `https://polygon-rpc.com`) |
| `ALCHEMY_RPC_URL` | RPC Alchemy (pour les opérations qui nécessitent plus de fiabilité) |
| `WENBOT_FEE_WALLET` | Adresse du wallet qui reçoit les frais |
| `WENBOT_PRIVATE_KEY` | Clé privée du wallet opérationnel (pour les refills MATIC) |
| `ENCRYPTION_MASTER_KEY` | Clé AES-256 en hex (64 caractères) |

### Variables optionnelles

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYMARKET_CLOB_HOST` | `https://clob.polymarket.com` | Host CLOB API |
| `POLYMARKET_CHAIN_ID` | `137` | Chain ID Polygon |
| `BUILDER_API_KEY` | — | Clé API Builder (pour redeem) |
| `BUILDER_API_SECRET` | — | Secret API Builder |
| `BUILDER_API_PASSPHRASE` | — | Passphrase API Builder |

### Générer une clé de chiffrement

```bash
python3 -c "import os; print(os.urandom(32).hex())"
```

---

## Installation locale

### Prérequis

- Python 3.11+
- Redis (ou Docker)
- Compte Supabase avec le schéma déployé

### Setup

```bash
# 1. Cloner le repo
git clone https://github.com/Vqnirr/Dirto-copybot.git
cd Dirto-copybot

# 2. Installer les dépendances
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configurer l'environnement
cp .env.example .env
# Éditer .env avec vos valeurs

# 4. Lancer Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 5. Déployer le schéma de base de données
(via Supabase CLI ou manuellement avec les fichiers dans migrations/)

# 6. Lancer le bot
python3 -m bot.main

# 7. Lancer le moteur d'exécution (dans un autre terminal)
python3 -m engine.main
```

### Avec Docker Compose

```bash
# Tout lancer d'un coup (dev)
docker compose up --build
```

---

## Déploiement production

### Setup complet automatisé

```bash
sudo bash scripts/setup_infra.sh
```

Ce script fait tout :
1. Vérifie que WireGuard est actif
2. Ajoute les règles iptables (bloque 80/443 sur l'interface publique)
3. Installe K3s avec Docker comme runtime
4. Configure Traefik pour écouter uniquement sur l'IP WireGuard
5. Build les images Docker (engine, bot, strategy)
6. Crée le namespace, les secrets depuis `.env`, et déploie tous les services
7. Déploie Portainer avec ingress HTTPS

### Déploiement individuel

```bash
# Rebuild + deploy engine
make deploy-engine

# Rebuild + deploy bot
make deploy-bot

# Deploy Redis
make deploy-redis

# Tout déployer
make deploy
```

---

## Commandes Make

```bash
make build            # Build toutes les images Docker
make build-engine     # Build l'image engine
make build-bot        # Build l'image bot
make build-strategy   # Build l'image strategy test

make deploy           # Deploy Redis + Engine + Bot
make deploy-engine    # Build + Deploy engine
make deploy-bot       # Build + Deploy bot

make status           # Afficher l'état des pods (wenbot-prod + portainer)
make pods             # Liste les pods wenbot-prod

make logs-engine      # Suivre les logs de l'engine
make logs-bot         # Suivre les logs du bot
make logs-redis       # Suivre les logs Redis

make restart-engine   # Restart l'engine
make restart-bot      # Restart le bot
make restart-all      # Restart engine + bot

make test-strategy    # Lancer le simulateur de signaux
make test             # Lancer les tests unitaires
make setup            # Setup infrastructure complet (root)
```

---

## Tests

```bash
# Lancer tous les tests
python3 -m pytest tests/ -v

# Ou via Make
make test
```

### Couverture des tests

| Fichier | Ce qui est testé |
|---------|-----------------|
| `test_executor.py` | BUY success, BUY fee failure, SELL sans frais, `send_trade_fee`, `_insert_trade` |
| `test_fee_queue.py` | `execute_for_subscribers`, tri par priorité, limites journalières, skip si solde insuffisant |
| `test_gas_manager.py` | Refill MATIC, 5 checks anti-exploit, rate limiting |
| `test_perf_fee.py` | Collecte des performance fees, PnL positif/négatif, ajustement au solde |
| `test_wallet.py` | Création wallet, chiffrement/déchiffrement, queries balance |

---

## Créer une stratégie

Une stratégie est un conteneur Docker qui publie des signaux sur Redis.

### Format du signal

```json
{
    "strategy_id": "my_strategy_v1",
    "action": "BUY",
    "side": "YES",
    "market_slug": "btc-updown-5m-1711612800",
    "token_id": "0x1234...abcd",
    "max_price": 0.75,
    "shares": 0.0,
    "confidence": 0.85,
    "timestamp": 1711612345.678
}
```

| Champ | Type | Description |
|-------|------|-------------|
| `strategy_id` | string | ID unique de la stratégie (doit exister dans la table `strategies`) |
| `action` | string | `"BUY"` ou `"SELL"` |
| `side` | string | `"YES"` ou `"NO"` |
| `market_slug` | string | Slug du marché Polymarket |
| `token_id` | string | ID du token conditionnel Polymarket |
| `max_price` | float | Prix maximum acceptable (BUY only, guardrail) |
| `shares` | float | Nombre de shares à vendre (SELL only, 0 pour BUY) |
| `confidence` | float | Score de confiance (0-1, informatif) |
| `timestamp` | float | Unix timestamp du signal |

### Canal Redis

Publier sur `signals:<strategy_id>` :

```python
import redis
import json

r = redis.from_url("redis://localhost:6379")
r.publish("signals:my_strategy_v1", json.dumps(signal))
```

### Enregistrer la stratégie

Insérer dans la table `strategies` :

```sql
INSERT INTO strategies (id, name, description, docker_image, status, visibility)
VALUES (
    'my_strategy_v1',
    'Ma Strategie',
    'Description de la stratégie',
    'wenbot/my-strategy:latest',
    'active',
    'public'
);
```

### Déployer sur K3s

```bash
bash scripts/deploy_strategy.sh my_strategy_v1 wenbot/my-strategy:latest
```

### Exemple complet

Voir `strategies/example_strategy/main.py` pour une implémentation de référence.

---

## Licence

Projet privé.
