# WENBOT FUSION — Polymarket CopyTrading + Strategy Bot

Bot Telegram professionnel pour [Polymarket](https://polymarket.com) qui fusionne deux moteurs complets :

- **Copy Wallet** : copie automatique des trades de wallets Polymarket suivis (multi-masters)
- **Suivi de Strategies** : execution automatique de signaux de strategies via Redis pub/sub

Chaque utilisateur dispose de wallets separes, de parametres individuels, de notifications routees vers des topics Telegram dedies, et d'une **Mini App Telegram complete** servie via FastAPI.

---

## Table des matieres

- [Architecture](#architecture)
- [Mini App Telegram (interface principale)](#mini-app-telegram-interface-principale)
- [Fonctionnalites](#fonctionnalites)
  - [Copy Wallet](#copy-wallet)
  - [Découvrir des traders (Polymarket leaderboard)](#decouvrir-des-traders-polymarket-leaderboard)
  - [Suivi de Strategies](#suivi-de-strategies)
  - [Smart Analysis V3](#smart-analysis-v3)
  - [Gestion des positions (live)](#gestion-des-positions-live)
  - [Reclamation des gains (Redeem)](#reclamation-des-gains-redeem)
  - [Notifications](#notifications)
  - [Rapports & exports](#rapports--exports)
  - [Depot de fonds](#depot-de-fonds)
- [API Endpoints (Mini App)](#api-endpoints-mini-app)
- [Garanties techniques du copytrading](#garanties-techniques-du-copytrading)
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
- [Limitations connues](#limitations-connues)

---

## Architecture

```
                     Telegram Users
                          |
                +---------+---------+
                |                   |
          Telegram Bot         Mini App
        (python-telegram-bot)  (FastAPI + SPA)
                |                   |
                +---------+---------+
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
                    (CLOB API + Gamma + data-api)
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

**4 couches** :
- **Mini App** (`bot/web/static/`, `bot/web/miniapp.py`) : SPA vanilla JS + endpoints FastAPI
- **Handlers Telegram** (`bot/handlers/`) : commandes natives, callbacks, menus inline
- **Services** (`bot/services/`) : logique metier (execution, monitoring, scoring, fees)
- **Models** (`bot/models/`) : ORM SQLAlchemy async (16 tables)

---

## Mini App Telegram (interface principale)

Une **Mini App Telegram** complete est l'interface principale du bot. Elle est servie par FastAPI a `/miniapp/static/miniapp.html` et utilise une SPA vanilla JS sans framework (zero build, deployment instant via volume Docker).

### Authentification

Authentification via Telegram WebApp `initData` :
- Le frontend envoie `Authorization: tma <initData>` sur chaque appel API
- Le backend valide via HMAC-SHA256 avec le bot token (`bot/web/auth.py`)
- Pour les liens externes (export HTML), un fallback `?auth=<initData>` query param est accepte

### Architecture front

- **5 onglets** : Accueil · Wallet · Copy · Stratégies · Notifs
- **Bouton ⚙️ engrenage** dans le header → page Plus (Réglages, Rapports, Notifications TG, etc.)
- **Telegram BackButton natif** auto-géré sur chaque sous-écran
- **Telegram MainButton** pour les actions principales (Importer, Suivre, Envoyer)
- **HapticFeedback** sur clics et toasts
- **Cache busting** via query string (`?v=YYYYMMDDx`) pour forcer le reload sur deploy

### Onglets

#### 🏠 Accueil

- Mode banner (Paper / Live) en haut de page
- Hero PnL total + badge état (Actif / Pause / Arrêté)
- Card balance avec **2 cellules** : Paper (fictif) et Live (on-chain) cote a cote
- Quick actions 2x2 : Traders, Découvrir, Positions, Stratégies
- Stats 7 derniers jours
- Activité récente (5 derniers événements)
- Bouton "Mettre en pause" inline si bot actif

#### 💰 Wallet (sub-nav : Copy / Stratégie)

Pour chaque wallet :
- Cellules duales Paper + Live avec indicateur du mode actif
- Adresse Polygon copiable
- 4 actions : Déposer (instructions) / Retirer (formulaire+confirmation+tx hash) / Exporter PK (double-confirm) / Supprimer
- Section **"💰 Réclamer mes gains"** : positions résolues gagnantes avec bouton vers Polymarket
- Wallet stratégie completement séparé (clé chiffrée distincte)

#### 👥 Copy (sub-nav : Traders / 🔍 Découvrir / Positions / Historique)

- **Traders** : liste des wallets suivis avec stats (trades, volume, PnL) + bouton "+ Ajouter"
- **🔍 Découvrir** : top traders Polymarket via leaderboard API (24h / 7j / 30j / All-time) avec médailles top-3
- **Positions** : auto-refresh 15s, hero PnL non-réalisé, current price live, indicateur 🟢 si tracked
- **Historique** : 50 derniers trades avec PnL settled si dispo
- **Fiche trader** (clic sur un item) : stats détaillées + **section "📊 Marchés actifs sur Polymarket"** avec bouton "🚫 Bloquer / ✓ Débloquer" par marché + section "🏷 Catégories exclues" + derniers trades copiés

#### 🎯 Stratégies (sub-nav : Disponibles / Mes abos / Historique)

- **Disponibles** : cards stratégies publiques avec PnL/win rate/trades + tap pour souscrire
- **Mes abos** : abonnements actifs avec trade_size + bouton modifier/désinscrire
- **Historique** : trades de stratégies avec result WON/LOST + PnL
- Bottom sheet modale pour souscription (slider trade_size avec bornes min/max de la strategy)
- Banner d'alerte si wallet stratégie non configuré

#### 🔔 Notifs (feed temps réel)

- Sub-nav : Tout / Trades / Sorties
- Timeline chronologique :
  - 🟢 Trades BUY copiés
  - 🔴 Trades SELL copiés
  - 🛑 Stop Loss déclenchés
  - 🎯 Take Profit atteints
  - 📉 Trailing stop sortis
  - ⏱ Time exits
  - ✂️ Scale out (TP partiels)
  - 📊 Trades de stratégies
- **Badge rouge** sur l'icône avec compteur unread (jusqu'a 99+)
- Auto-marqué lu dès ouverture de l'onglet
- Polling toutes les 20s en tâche de fond
- Items avec barre latérale colorée par sévérité (vert/rouge/orange/bleu)

### Plus (header ⚙️)

Accessible via le bouton engrenage en haut a droite :
- ⚙️ Réglages (toutes les configurations)
- 🔔 Notifications Telegram (config canal TG)
- 📊 Rapports (Mes trades / Mes traders / Export)
- 🚫 Marchés bloqués (gestion blacklist global)

### Réglages — 10 cards thématiques

Chaque champ a une **description claire avec exemple chiffré** :

1. 🔌 **Mode trading** — Toggle Paper/Live avec double confirmation pour Live
2. 💰 **Capital & sizing** — capital alloué, mode (FIXED/PERCENT/PROPORTIONAL/KELLY), montant fixe, %, multiplicateur, min/max, daily limit
3. 🧠 **Smart Analysis V3** — scoring on/off, score min, smart filter, skip coin-flip, conviction min, drift max, win rate trader min + 3 **Profils rapides** (Prudent/Équilibré/Agressif)
4. 🛡 **Stop Loss & Take Profit** — SL/TP avec %, trailing stop dynamique
5. ⏱ **Sorties avancées** — time exit (heures), scale out (% au TP1)
6. 📊 **Risque portefeuille** — max positions, max % par catégorie, max biais YES/NO
7. 🔥 **Suivi performance traders** — auto-pause cold traders, seuil cold WR, hot streak boost (multiplicateur)
8. ⛽ **Gas & Timing** — gas mode (Normal/Fast/Ultra/Instant), délai avant copie, confirmation manuelle
9. 🔔 **Notifications** — destination DM/Group/Both
10. 🎯 **Stratégies** — fee rate (priorité dans la file d'exécution), max trades/jour, pause

### Rapports

3 sub-tabs avec **bouton "Générer" explicite** (plus de génération auto au moindre clic) :

- **📊 Mes trades** : sélecteur période → génère hero PnL + activité par jour + répartition + PnL par marché
- **👥 Mes traders** : cases à cocher par trader (Tout/Aucun) + sélecteur période → liste détaillée avec catégories fortes/faibles, streaks, badges HOT/COLD
- **📄 Export** : sélecteur période + bouton "Générer & ouvrir le rapport HTML" → ouvre une page imprimable (Ctrl+P pour PDF)

### Notifications Telegram (page dédiée)

Configuration claire :
- 📍 **Destination** : DM / Groupe / Both
- 🎚 **Toggles fins par événement** :
  - 🟢 Notify trades BUY exécutés
  - 🔴 Notify trades SELL exécutés
  - 🛑🎯 Notify sorties auto (SL/TP/Trailing/Time/Scale)
- 💡 Note : la Mini App garde TOUT l'historique dans l'onglet 🔔 même si on coupe TG

---

## Fonctionnalites

### Copy Wallet

Le moteur de copy-trading surveille les wallets Polymarket que l'utilisateur choisit de suivre et reproduit automatiquement leurs trades.

**Flux complet** :

1. `MultiMasterMonitor` poll les positions des wallets suivis via l'API Gamma (intervalle configurable, defaut 15s)
2. **Snapshot baseline** au moment d'ajouter un trader : ses positions actuelles ne sont PAS copiées (uniquement les nouveaux trades a venir)
3. Detection d'un changement = emission d'un `TradeSignal` (achat ou vente proportionnelle)
4. `CopyTradeEngine` recoit le signal et pour chaque follower du wallet :
   - **Idempotency check** : skip si même (user, market, token, side) déjà exécuté dans les 5 dernières min (anti-replay)
   - Valide les filtres (categories, blacklist marchés, expiry max, trader_filters par-trader)
   - **Auto-pause** si trader cold (option utilisateur)
   - **Hot streak boost** appliqué au sizing si trader en série de wins
   - Score le signal via `SignalScorer` (0-100) — si V3 active
   - Filtre via `SmartFilter` (coin-flip, conviction, trader edge, drift)
   - Verifie les contraintes portfolio via `PortfolioManager`
   - Calcule la taille via `SizingEngine` (4 modes)
   - Applique le hot_streak_boost
   - Calcule et transfere les frais on-chain
   - Execute l'ordre via l'API CLOB de Polymarket (live) ou simule (paper)
   - Enregistre le trade + frais en base
   - Notifie via `TopicRouter` (topic Telegram + Mini App feed) selon les flags `notify_on_buy/sell`
   - Enregistre la position ouverte pour le suivi SL/TP

**4 modes de sizing** :

| Mode | Description | Calcul |
|------|-------------|--------|
| `FIXED` | Montant fixe par trade | `fixed_amount` (ex: 5 USDC) |
| `PERCENT` | % du capital alloue | `allocated_capital * percent_per_trade` |
| `PROPORTIONAL` | Proportion du trade master | `master_amount * (my_capital / master_portfolio) * multiplier` |
| `KELLY` | Kelly Criterion simplifie | Utilise le mode PERCENT avec le % configure |

Contraintes appliquees : `min_trade_usdc`, `max_trade_usdc`, balance disponible.

**Paper trading** : Chaque utilisateur peut activer le mode paper (balance virtuelle de 1000 USDC par defaut). Les trades sont simules — memes calculs, memes notifications, mais aucune transaction on-chain. Le `paper_balance` est débité/crédité automatiquement par le bot. Le passage Paper → Live exige une **double confirmation explicite** (security gate `live_mode_confirmed`).

### Decouvrir des traders (Polymarket leaderboard)

Onglet **🔍 Découvrir** sous Copy. Permet de trouver les meilleurs traders Polymarket sans connaître leur adresse :

- Endpoint backend `/discover/top-traders?period=day|week|month|all`
- Appelle `https://lb-api.polymarket.com/profit` avec parsing robuste (fallback sur plusieurs structures de réponse)
- Affichage rankée avec médailles top-3 (gradient or)
- Bouton "+ Suivre" inline (1 clic ajoute à `followed_wallets`)
- Tap sur un item → fiche détaillée avec **positions actives sur Polymarket** (via `data-api.polymarket.com/positions`)
- Lien direct vers le profil Polymarket natif

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
     - Notifie via topic Telegram dedie + Mini App feed
4. `StrategyResolver` poll l'API Gamma toutes les 30s :
   - Detecte les marches resolus
   - Calcule le PnL : WON = `shares * $1 - cost`, LOST = `0 - cost`
   - Met a jour `Trade.result`, `Trade.pnl`, `Trade.resolved_at`
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

Chaque critere produit un score 0-100, pondere et somme. Le signal est copie si `total_score >= min_signal_score` (configurable par utilisateur, defaut 40).

Les poids sont modifiables par l'utilisateur via la Mini App ou le menu `/signals` Telegram.

#### Profils rapides

3 presets accessibles dans Réglages → Smart Analysis :

| Profil | min_score | Stratégie |
|--------|-----------|-----------|
| 🛡 **Prudent** | 65 | Pondération équilibrée 6 critères, conviction min 5%, drift max 3% |
| ⚖️ **Équilibré** | 40 | Trader_form + conviction prioritaires, défaut sain |
| ⚡ **Agressif** | 20 | Désactive spread+timing, mise sur conviction+forme du trader, accepte coin-flip |

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
- Détection **hot streak** (bonus de sizing via `hot_streak_boost`) et **cold streak** (`auto_pause_cold_traders`)
- Performance par type de marche (crypto, politique, sport...) via `TraderMarketHistory`
- Catégories fortes (≥60% WR sur ≥3 trades) et faibles (≤40% WR) affichées dans Analytics

#### Filtres par-trader

Possibilité de definir des **catégories exclues spécifiques par trader** via `UserSettings.trader_filters` :
- Format : `{"0xwallet": {"excluded_categories": ["Sports", "NBA"]}}`
- Exposé via la fiche trader dans la Mini App
- Câblé dans `copytrade.py:_passes_filters()`

### Gestion des positions (live)

Le `PositionManager` surveille les positions ouvertes toutes les 15 secondes :

| Mecanisme | Description |
|-----------|-------------|
| **Stop-Loss** | Vend si le prix tombe sous `entry_price * (1 - sl_pct)` |
| **Take-Profit** | Vend si le prix depasse `entry_price * (1 + tp_pct)` |
| **Trailing Stop** | SL dynamique qui monte avec le prix (`highest_price * (1 - trailing_pct)`) |
| **Time Exit** | Vend apres N heures (`time_exit_hours`) — câblé dans `_check_loop` |
| **Scale Out** | Au TP : vend `scale_out_pct` % au lieu de 100%, garde le reste avec SL=entrée (lock-in profit) |

Chaque exit déclenche un ordre SELL réel (ou paper) via le callback `on_position_exit`, puis crée un `Trade` SELL correspondant. Les notifications respectent le flag `notify_on_sl_tp`.

**Vue live dans la Mini App** : l'écran Positions auto-refresh toutes les 15s avec :
- PnL non-réalisé (mark-to-market) calculé sur `current_price` depuis `ActivePosition`
- Hero PnL total non-réalisé + investissement total + valeur actuelle
- Indicateur 🟢 par position si tracked par le `position_manager`
- Stop auto du polling quand on quitte la page (économie batterie)

**Controles portfolio** (`PortfolioManager`) :

| Controle | Description |
|----------|-------------|
| `max_positions` | Nombre max de positions ouvertes simultanees |
| `max_category_exposure_pct` | Exposition max a une categorie (ex: 40% crypto) |
| `max_direction_bias_pct` | Biais directionnel max (ex: 70% YES max) |

### Reclamation des gains (Redeem)

Sur Polymarket, quand un marché se résout :
- Le bot calcule automatiquement `settlement_pnl` (scheduler `settle_trades` /2min)
- Pour les **paper trades** : `paper_balance` est crédité automatiquement
- Pour les **live trades** : `is_settled=True` est marqué, mais l'USDC reste verrouillé dans le contrat Conditional Tokens jusqu'a un appel `redeemPositions()` sur la blockchain

**État actuel** : le redeem on-chain n'est PAS automatisé. La Mini App expose une section **"💰 Réclamer mes gains"** sur l'écran Wallet/Copy :
- Endpoint `GET /positions/redeemable` liste les trades is_settled + winners + live
- Affiche : marché, shares, gain estimé, total
- Bouton **"🌐 Réclamer sur Polymarket ↗"** ouvre `https://polymarket.com/profile/{wallet}` où l'utilisateur clique "Redeem" en 2 clics

Auto-redeem on-chain prévu en évolution future (nécessite ABI Conditional Tokens + calcul indexSets + signature TX web3.py).

### Notifications

**Deux canaux complémentaires** :

#### 1. Telegram (DM + topics groupe)

- Configurable via la Mini App (Plus → Notifications Telegram) :
  - **Destination** : `dm` / `group` / `both`
  - **Filtres événements** : `notify_on_buy`, `notify_on_sell`, `notify_on_sl_tp`
- Routes via `TopicRouter` (7 topics dans un groupe forum)
- Format enrichi : score, badges, breakdown PnL, durée

#### 2. Mini App feed (onglet 🔔 Notifs)

- Timeline temps réel **dérivée** des `trades` + `active_positions` closed (pas de table dédiée)
- Sub-nav : Tout / Trades / Sorties
- Tracking unread via `users.last_notif_seen_at`
- Badge rouge sur l'icône avec compteur (jusqu'à 99+)
- Auto-mark-read au visit
- Polling toutes les 20s en background (pause si tab pas visible)

Le feed Mini App est **toujours complet** même si l'utilisateur a coupé certaines notifs Telegram.

### Rapports & exports

3 sub-tabs avec **génération à la demande** (sélecteurs + bouton "Générer") :

#### 📊 Mes trades

- Sélecteur de période (Aujourd'hui / 7j / 30j)
- Hero PnL période + stats (Trades / Win rate / Best)
- Activité par jour (graphe barres)
- Répartition par source (positions ouvertes)
- PnL par marché (top 15)
- Bouton inline "📄 Exporter HTML/PDF"

#### 👥 Mes traders

- **Cases à cocher par trader** (par défaut tous cochés)
- Boutons "Tout cocher" / "Tout décocher"
- Sélecteur de période (7j / 30j)
- Affichage filtré : catégories fortes/faibles, streaks, badges HOT/COLD
- Lien vers la fiche complète

#### 📄 Export HTML / PDF

- Sélecteur de période + bouton "Générer & ouvrir le rapport"
- Génère un rapport HTML standalone via `/reports/export.html`
- Ouvert via `tg.openLink()` avec `?auth=` query param (URL self-contained)
- Imprimable en PDF natif (Ctrl+P)
- Inclus : hero PnL, breakdown copy/strategy, win rate, best/worst, table par trader (top 20), table par marché (top 20), détail des 100 derniers trades

### Depot de fonds

Le bot guide l'utilisateur pour deposer des USDC sur son wallet Polygon depuis un exchange (Binance, Coinbase, OKX, Bybit...).

**Etapes affichees a l'utilisateur :**

1. Ouvrir son exchange
2. Acheter des USDC (carte, virement...)
3. Retrait → USDC → reseau **Polygon** (pas Ethereum, pas Arbitrum)
4. Coller l'adresse du wallet bot comme destination
5. Confirmer — recu en ~2-5 min, frais ~0.1 USDC

Le bot affiche l'adresse du wallet et permet de la copier en un clic. L'utilisateur doit aussi envoyer ~0.2 POL/MATIC pour le gas (quelques centimes suffisent pour des dizaines de trades).

Aucune integration de paiement tiers (pas de Transak, MoonPay, etc.) — l'utilisateur gere ses fonds depuis son propre exchange.

---

## API Endpoints (Mini App)

Tous les endpoints sont sous `/miniapp/api`. Auth requise via `Authorization: tma <initData>`.

### User & Auth
| Endpoint | Description |
|----------|-------------|
| `GET /me` | Profil + état wallets + counts |
| `POST /user/mode` | Switch paper/live (avec `confirm_live` requis pour Live) |
| `GET /controls/status` | Etat copytrading (running/paused/stopped) |
| `POST /controls/pause` | Mettre en pause |
| `POST /controls/resume` | Reprendre |

### Wallet copy
| Endpoint | Description |
|----------|-------------|
| `POST /wallet/create` | Génère un nouveau wallet Polygon (PK affichée 1x) |
| `POST /wallet/import` | Importe une clé privée existante |
| `GET /wallet/balance` | USDC + MATIC + erreurs RPC explicites |
| `POST /wallet/withdraw` | Transfer USDC vers une adresse externe |
| `POST /wallet/export-pk` | Récupère la clé privée déchiffrée (avec `confirm`) |
| `DELETE /wallet` | Efface le wallet de la base |

### Wallet stratégie
Mêmes routes sous `/strategy-wallet/*` (créé/import/balance/withdraw/export-pk/delete).

### Copy trading
| Endpoint | Description |
|----------|-------------|
| `GET /copy/stats` | Stats globales (trades, today, volume, PnL, open) |
| `GET /copy/positions` | Positions ouvertes avec PnL non-réalisé live |
| `GET /copy/trades` | Historique trades (limit + offset) |
| `GET /copy/traders` | Liste traders suivis avec stats |
| `POST /copy/traders/add` | Suivre un trader (par adresse) |
| `DELETE /copy/traders/{wallet}` | Arrêter de suivre |
| `GET /copy/traders/{wallet}/stats` | Stats détaillées d'un trader |
| `GET /copy/blacklist` | Liste des marchés bloqués |
| `POST /copy/blacklist/add` | Bloquer un marché |
| `DELETE /copy/blacklist/{market_id}` | Débloquer |

### Discover
| Endpoint | Description |
|----------|-------------|
| `GET /discover/top-traders?period=day\|week\|month\|all` | Leaderboard Polymarket |
| `GET /discover/trader/{wallet}/markets` | Positions ouvertes d'un trader sur Polymarket |

### Strategies
| Endpoint | Description |
|----------|-------------|
| `GET /strategies` | Liste des strategies disponibles |
| `GET /strategies/subscriptions` | Mes abonnements |
| `POST /strategies/{id}/subscribe` | Souscrire (avec `trade_size`) |
| `POST /strategies/{id}/unsubscribe` | Désinscrire |
| `PATCH /strategies/{id}/subscription` | Modifier (trade_size / is_active) |
| `GET /strategies/trades` | Historique trades stratégies |
| `GET /strategies/stats` | Stats agrégées stratégies |

### Settings
| Endpoint | Description |
|----------|-------------|
| `GET /settings` | Tous les réglages utilisateur |
| `POST /settings` | Update partiel (Pydantic exclude_none) |
| `POST /settings/scoring-profile` | Applique un preset (prudent/balanced/aggressive) |
| `GET /settings/trader-filters` | Filtres par-trader actuels |
| `POST /settings/trader-filter` | Set exclusions catégories pour un trader |

### Analytics
| Endpoint | Description |
|----------|-------------|
| `GET /analytics/traders` | Stats par trader (catégories fortes/faibles, streaks) |
| `GET /analytics/portfolio` | Répartition positions par source |
| `GET /analytics/signals` | Activité par jour (7j) |
| `GET /analytics/filters` | Config scoring + criteria weights |

### Reports
| Endpoint | Description |
|----------|-------------|
| `GET /reports/pnl?period=day\|week\|month` | Stats PnL période |
| `GET /reports/by-trader` | PnL agrégé par trader |
| `GET /reports/by-market` | PnL agrégé par marché |
| `GET /reports/export.html?period=...&auth=...` | Page HTML standalone imprimable |

### Notifications
| Endpoint | Description |
|----------|-------------|
| `GET /notifications?limit=N&kind=all\|trades\|exits` | Feed unifié dérivé |
| `GET /notifications/unread-count` | Compteur d'événements après last_notif_seen_at |
| `POST /notifications/mark-read` | Update last_notif_seen_at = now() |

### Positions
| Endpoint | Description |
|----------|-------------|
| `GET /positions/redeemable` | Positions gagnantes live à réclamer sur Polymarket |

---

## Garanties techniques du copytrading

### Pas de copie des positions pré-existantes

`bot/services/monitor.py:182-187` :
```python
if initial or not state.initialized:
    state.positions = {p.token_id: p for p in positions}  # snapshot baseline
```

Quand un trader est ajouté, ses positions actuelles deviennent le baseline. Aucun signal n'est émis pour ces positions. Seuls les **changements futurs** (nouvelles positions, top-ups, decreases, fermetures) déclenchent une copie.

### Idempotency anti-doublon

`bot/services/copytrade.py` (nouveau bloc inseré avant calculate_trade_size) :
- Avant chaque exécution, check si même `(user_id, market_id, token_id, side)` déjà processé dans les 5 dernières minutes
- Si oui → skip
- Évite les double-copies en cas de restart Docker, replay du monitor, ou bug réseau

### Settlement automatique

Scheduler `settle_trades` toutes les 2 minutes (`bot/main.py:151`) :
- Trouve trades `is_settled=False, FILLED, BUY`
- Check résolution Polymarket (`check_market_resolution`)
- Calcule `pnl = (shares × $1) - invested` si gagné, sinon `-invested`
- Marque `is_settled=True`, `settlement_pnl`, `market_outcome`
- Pour paper : crédite `paper_balance` automatiquement
- Notifie via Telegram + Mini App feed

### Multi-tenant safety

- Chaque trade a un `user_id` unique (FK vers User)
- `daily_spent_usdc`, `paper_balance`, `daily_limit_usdc` per-user
- Settings isolés via `UserSettings.user_id` (1:1)
- `get_followers_of_wallet(master_wallet)` retourne uniquement les users qui suivent **ce** master
- Notifications routées via `telegram_id` unique

### Live mode safety gate

Triple-check avant tout trade live (`copytrade.py:163-180`) :
1. `user.paper_trading == False`
2. `user.live_mode_confirmed == True` (set seulement si l'utilisateur confirme explicitement via la Mini App)
3. `user.encrypted_private_key` non null

Sinon → fallback paper avec log warning.

### Position price refresh

`PositionManager._check_loop` toutes les 15s :
- Update `current_price`, `highest_price` sur toutes les ActivePosition
- Check SL / TP / trailing / time_exit
- Trigger `_execute_exit` si condition remplie

### Cold trader auto-pause + Hot streak boost

Câblé dans `copytrade.py` (nouveau bloc avant `calculate_trade_size`) :
- `auto_pause_cold_traders` : appelle `trader_tracker.check_auto_pause(wallet)` → skip si trader cold + notif explicative
- `hot_streak_boost` : appelle `trader_tracker.get_hot_multiplier(wallet)` → multiplie `gross_amount` si hot streak

---

## Modeles de donnees

16 tables SQLAlchemy async. Migrations auto via `init_db()` au démarrage (`ALTER TABLE` avec SAVEPOINT pour ajouter des colonnes sans casser l'existant).

### Tables principales

```
users
  |-- id, uuid, telegram_id, telegram_username, role (ADMIN|FOLLOWER)
  |-- wallet_address, encrypted_private_key              # Copy wallet
  |-- strategy_wallet_address, encrypted_strategy_pk     # Strategy wallet (separe)
  |-- is_active, is_paused, paper_trading, live_mode_confirmed
  |-- daily_limit_usdc, daily_spent_usdc
  |-- paper_balance, paper_initial_balance
  |-- last_notif_seen_at                                 # Mini App unread tracking

user_settings (1:1 avec User)
  |-- Sizing: allocated_capital, sizing_mode, fixed_amount, percent_per_trade, multiplier
  |-- Risk: stop_loss_pct, take_profit_pct, max/min_trade_usdc
  |-- Filtres: followed_wallets (JSON), categories, blacklisted_markets, trader_filters (JSON)
  |-- Filtres: max_expiry_days
  |-- V3 Smart: signal_scoring_enabled, min_signal_score, scoring_criteria (JSON)
  |-- V3 Positions: trailing_stop_pct, time_exit_hours, scale_out_pct
  |-- V3 Portfolio: max_positions, max_category_exposure_pct, max_direction_bias_pct
  |-- V3 Traders: auto_pause_cold_traders, cold_trader_threshold, hot_streak_boost
  |-- V3 Smart filter: skip_coin_flip, min_conviction_pct, max_price_drift_pct
  |-- V3 Smart filter: min_trader_winrate_for_type, min_trader_trades_for_type
  |-- Copy: copy_delay_seconds, manual_confirmation, confirmation_threshold_usdc
  |-- Notifications: notification_mode (dm/group/both)
  |-- Notifications: notify_on_buy, notify_on_sell, notify_on_sl_tp
  |-- Gas: gas_mode (normal/fast/ultra/instant)

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
  |-- trade_fee_rate (1-20%), max_trades_per_day, trades_today, is_paused
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
  |-- is_closed, close_reason (sl_hit|tp_hit|trailing_stop|time_exit|scale_out|manual)
  |-- opened_at, closed_at

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
| `PositionManager` | `position_manager.py` | SL/TP/trailing/time exit/scale out — poll toutes les 15s |
| `PortfolioManager` | `portfolio_manager.py` | Contraintes portfolio (positions max, exposition) |
| `TraderTracker` | `trader_tracker.py` | Stats rolling par trader (hot/cold detection) + multipliers |
| `MarketIntelService` | `market_intel.py` | Cache market data + liquidity scoring + momentum |

### Services Strategy Engine

| Service | Fichier | Role |
|---------|---------|------|
| `StrategyListener` | `strategy_listener.py` | Subscribe Redis `signals:*`, dispatch au executor |
| `StrategyExecutor` | `strategy_executor.py` | Execute les signaux pour chaque abonne (fee queue priority) |
| `StrategyResolver` | `strategy_resolver.py` | Poll Gamma pour resolution, calcule PnL |
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

### Web (FastAPI)

| Module | Fichier | Role |
|--------|---------|------|
| `app.py` | `bot/web/app.py` | Application FastAPI principale |
| `miniapp.py` | `bot/web/miniapp.py` | Router `/miniapp/api/*` (40+ endpoints) |
| `auth.py` | `bot/web/auth.py` | Validation HMAC-SHA256 du Telegram initData |
| `static/miniapp.html` | | Shell HTML minimal |
| `static/miniapp.js` | | SPA vanilla JS (5 onglets, routing hash) |
| `static/miniapp.css` | | Design system (dark + light, theme Telegram) |
| `templates/dashboard.html` | | Dashboard web admin (Jinja2, lecture seule) |

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
- Le `gas_mode` utilisateur (normal/fast/ultra/instant) determine le `priority_fee_gwei` du transfert

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

### Pipeline complet

```
Signal recu du master
        |
        v
  [Idempotency check] ─── skip si déjà processé en 5 min
        |
        v
  [SmartFilter]  ─── Filtre pattern-based
  |  Coin-flip ? (prix 0.45-0.55)        → SKIP
  |  Conviction trop faible ?              → SKIP
  |  Trader sans edge sur ce marche ?      → SKIP
  |  Price drift trop important ?          → SKIP
  |
  v
  [Auto-pause cold traders]  ─── skip si trader cold (option)
        |
        v
  [Hot streak boost]  ─── multiplie sizing si trader hot
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
  EXECUTION (live ou paper)
  |
  v
  Notif (selon notify_on_buy/sell + notification_mode)
  |
  v
  Mini App feed update + badge unread
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
| `daily_limit_usdc` | Limite de depenses journaliere | 1000 USDC |
| `copy_delay_seconds` | Delai avant copie (eviter front-running) | 0s |
| `manual_confirmation` | Confirmation manuelle au-dessus d'un seuil | false |
| `confirmation_threshold_usdc` | Seuil pour confirmation | 50 |

### Par position (V3)

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `stop_loss_pct` | % de perte max avant vente auto | 20% |
| `take_profit_pct` | % de gain avant prise de profit | 50% |
| `trailing_stop_pct` | Trailing stop dynamique | 10% |
| `time_exit_hours` | Sortie forcee apres N heures | 24h |
| `scale_out_pct` | % de la position vendu au TP | 50% |

### Par portfolio (V3)

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `max_positions` | Nb max de positions ouvertes | 15 |
| `max_category_exposure_pct` | Exposition max par categorie | 30% |
| `max_direction_bias_pct` | Biais YES/NO max | 70% |

### Trader tracking (V3)

| Parametre | Description | Defaut |
|-----------|-------------|--------|
| `auto_pause_cold_traders` | Skip si trader cold | true |
| `cold_trader_threshold` | Seuil win rate cold | 40% |
| `hot_streak_boost` | Multiplicateur sizing si hot streak | 1.5x |

### Filtrage de marches

| Mecanisme | Granularite | Effet |
|-----------|-------------|-------|
| `categories` (whitelist) | Large | Si défini, autorise SEULEMENT ces catégories |
| `blacklisted_markets` | Précis (1 marché) | Skip ce marché précis pour TOUS les traders |
| `trader_filters` | Par-trader | Exclusions de catégories spécifiques par trader |
| `max_expiry_days` | Global | Skip marchés trop éloignés dans le temps |

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
| **Auth Mini App** | HMAC-SHA256 sur Telegram initData (validation backend a chaque requete) |
| **Mode Live safety gate** | Triple check : paper_trading=False + live_mode_confirmed=True + wallet présent |
| **Idempotency** | Anti-doublon 5 min sur (user, market, token, side) |
| **Messages sensibles** | Auto-supprimes immediatement sur Telegram |
| **Wallets separes** | Copy wallet et Strategy wallet completement independants |
| **OTP** | Codes a usage unique pour operations sensibles (withdraw, etc.) |
| **Audit logs** | Table immutable `audit_logs` — toute action tracee |
| **Rate limiting** | Redis sliding window, per-user et global |
| **Anti-exploit gas** | 5 checks avant tout refill MATIC |
| **Circuit breaker** | Arret auto en cas d'erreurs repetees |
| **Export PK** | Double-confirm via 2 toggles + log warning admin |

---

## Telegram — Commandes et navigation

L'interface principale est la **Mini App**. Les commandes Telegram natives restent un fallback :

### Hub principal

```
/start  →  Hub d'accueil
           └── Bouton "📱 Ouvrir l'App" (Mini App)
```

Si l'utilisateur préfère l'interface native :

```
/menu   →  Menu inline (fallback)
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

Mode de notification configurable par utilisateur via la Mini App : `dm` (DM uniquement), `group` (topic uniquement), `both`.

Filtres événements granulaires : `notify_on_buy`, `notify_on_sell`, `notify_on_sl_tp`.

---

## Infrastructure

### Docker Compose

```yaml
services:
  bot:        # Python 3.12 — bot Telegram + Mini App + dashboard FastAPI
  db:         # PostgreSQL 16 Alpine — donnees persistantes
  redis:      # Redis 7 Alpine — rate limiting + strategy pub/sub
```

- PostgreSQL et Redis ne sont **pas exposes** sur l'hote (securite VPS)
- Mini App + Dashboard accessibles sur le port `8080`
- Volumes persistants : `pgdata`, `redisdata`
- Health checks sur DB et Redis avant demarrage du bot

### HTTPS pour la Mini App

Telegram exige HTTPS pour servir une Mini App. Plusieurs options :

1. **Cloudflare Tunnel** (gratuit, recommandé) :
   ```bash
   cloudflared tunnel --url http://localhost:8080
   ```
   Donne une URL `https://xxx.trycloudflare.com` à coller dans `MINIAPP_URL`.

2. **Reverse proxy + Let's Encrypt** (Caddy/Traefik/Nginx + certbot) avec un domaine.

3. **ngrok** pour développement local.

### Migrations

Les migrations SQL sont executees automatiquement au demarrage (`init_db()` dans `session.py`) :

- `ALTER TABLE` avec SAVEPOINT pour ajouter des colonnes sans casser l'existant
- `CREATE TABLE IF NOT EXISTS` pour les nouvelles tables
- Scripts de reference dans `migrations/`

Migrations récentes ajoutées :
- `users.last_notif_seen_at TIMESTAMP` (Mini App unread tracking)
- `user_settings.notify_on_buy/sell/sl_tp BOOLEAN DEFAULT true`

### Cache busting Mini App

Le HTML `miniapp.html` injecte `?v=YYYYMMDDx` sur les liens CSS/JS pour forcer Telegram a re-télécharger les assets après deploy. Bump le suffixe à chaque release UI.

---

## Deploiement VPS

### Premiere installation

```bash
# 1. Cloner le repo
git clone https://github.com/Torkor29/WENBOT_V3.git
cd WENBOT_V3

# 2. Creer et configurer l'environnement
cp .env.example .env
nano .env
# Remplir au minimum : TELEGRAM_TOKEN, ADMIN_CHAT_ID, ENCRYPTION_KEY,
#                       POSTGRES_PASSWORD, MINIAPP_URL, FEES_WALLET, POLYGON_RPC_URL

# 3. Generer la cle de chiffrement
python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Lancer
docker compose up -d --build

# 5. Verifier les logs
docker compose logs -f bot

# 6. Setup HTTPS via Cloudflare Tunnel (si pas déjà fait)
nohup cloudflared tunnel --url http://localhost:8080 > /tmp/cloudflared.log 2>&1 &
# Récupérer l'URL trycloudflare et la coller dans MINIAPP_URL du .env
```

### Configurer la Mini App dans BotFather

```
/setdomain  ← envoyer au bot @BotFather, choisir votre bot, coller l'URL HTTPS
/setmenubutton  ← optionnel : bouton menu permanent qui ouvre la Mini App
```

### Mise a jour

```bash
cd ~/WENBOT_V3
git pull origin v3-smart-analysis
docker compose up -d --build
docker compose logs -f bot
```

Pour un simple restart sans rebuild :
```bash
docker compose restart bot
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

# Voir les jobs scheduler
docker compose logs bot | grep -i "settle\|scheduled\|job"

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
| `MINIAPP_URL` | URL HTTPS publique de la Mini App (Cloudflare/ngrok/domain) |

### Variables optionnelles

| Variable | Defaut | Description |
|----------|--------|-------------|
| `PLATFORM_FEE_RATE` | 0.01 | Frais copy-trade (1%) |
| `MONITOR_POLL_INTERVAL` | 15 | Intervalle de poll (secondes) |
| `STRATEGY_PERF_FEE_RATE` | 0.05 | Performance fee (5%) |
| `STRATEGY_RESOLVER_INTERVAL` | 30 | Poll resolution (secondes) |
| `STRATEGY_MATIC_REFILL_AMOUNT` | 0.1 | Montant refill MATIC |
| `DASHBOARD_ENABLED` | true | Activer le dashboard web |
| `DASHBOARD_PORT` | 8080 | Port interne dashboard + Mini App |
| `COLLECT_FEES_ONCHAIN` | false | Transferer les frais on-chain |

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| **Langage** | Python 3.12 |
| **Bot Telegram** | python-telegram-bot 21.9 |
| **API Polymarket** | py-clob-client 0.18.0 (CLOB) + Gamma API + data-api + lb-api (leaderboard) |
| **ORM** | SQLAlchemy 2.0 (async) + asyncpg |
| **Base de donnees** | PostgreSQL 16 |
| **Cache / Pub-Sub** | Redis 7 (hiredis) |
| **Blockchain** | Web3.py 7.6 (Polygon) |
| **HTTP** | httpx 0.28 (HTTP/2) |
| **Chiffrement** | cryptography 44.0 (AES-256-GCM) |
| **Scheduler** | APScheduler 3.10 |
| **Web** | FastAPI 0.115 + Uvicorn + Jinja2 |
| **Mini App** | Vanilla JS SPA (zéro framework, zéro build) + Telegram WebApp SDK |
| **Validation** | Pydantic 2.10 + pydantic-settings |
| **Infra** | Docker + Docker Compose |
| **HTTPS** | Cloudflare Tunnel (recommandé) |
| **Tests** | pytest + pytest-asyncio + pytest-cov |

---

## Limitations connues

### 1. Redeem on-chain non automatisé

Quand un marché Polymarket se résout :
- Le bot calcule `settlement_pnl` correctement (scheduler /2min)
- Mais le contrat `ConditionalTokens` (`0x4D97DCd97eB9859e87e8a49B26f7BF28d03De805` sur Polygon) requiert un appel `redeemPositions()` pour libérer les USDC gagnants
- Cet appel n'est pas automatisé actuellement

**Workaround** : la Mini App expose une section "💰 Réclamer mes gains" sur l'écran Wallet qui liste les positions à réclamer + bouton vers `https://polymarket.com/profile/{wallet}` où l'utilisateur clique "Redeem" en 2 clics (~10 sec).

**Solution propre** (TODO) : implémenter `redeem_positions()` dans `polymarket.py` avec ABI Conditional Tokens + indexSets calculés depuis conditionId + signature TX web3.py + scheduler dédié + bouton "Redeem auto" dans la Mini App.

### 2. Replay theoriquement possible sur restart Docker

Si le bot crash entre `Trade` créé en DB (`status=PENDING`) et `executed_at` set (`status=FILLED`), un signal pourrait être rejoué au restart.

**Mitigation actuelle** : check idempotency 5 min sur `(user_id, market_id, token_id, side)` avant chaque exécution. Évite les doubles exécutions dans cette fenêtre.

### 3. Polymarket Leaderboard API peut changer

L'endpoint `https://lb-api.polymarket.com/profit` n'est pas documenté officiellement. Le parsing backend est tolérant (essaie plusieurs structures de réponse) mais peut casser silencieusement si l'API change. La Mini App affiche alors un message d'erreur clair plutôt que crash.

### 4. Pas de support Solana actuellement

Le code prévoit `solana_wallet_address` et `auto_bridge_sol` mais pas câblé. Polymarket reste exclusivement sur Polygon dans cette version.

---

## Licence

Projet prive — tous droits reserves.
