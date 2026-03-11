## Polymarket CopyTrading Bot — WENPOLYMARKET

Bot Telegram de copy-trading pour Polymarket, orienté wallets (multi-masters) et rapidité d'exécution.

### Fonctionnalités principales

- Chaque utilisateur :
  - Crée ou importe un **wallet Polygon dédié** au copy-trading (aucune clé privée de son wallet principal n'est requise s’il choisit l’option “Créer un wallet”).
  - Choisit quels **traders Polymarket** suivre (par adresse 0x).
  - Configure ses paramètres de risque : capital alloué, sizing (fixe / pourcentage / proportionnel), stop-loss global, limites par trade, délai de copie, confirmation manuelle, etc.
- Le bot :
  - Surveille en continu les **positions des wallets suivis** sur Polymarket.
  - Copie automatiquement **achats ET ventes** vers les followers éligibles.
  - Gère le **paper trading** et le **trading réel**.
  - Supporte un bridge **SOL → USDC sur Polygon** (flux Li.Fi / Across, exécution à parfaire).

L’architecture est pensée pour faire évoluer le projet vers du **sniping / arbitrage** (suivi temps réel des wallets et exécution rapide).

---

### Stack technique

- **Langage** : Python 3.11+
- **Bot Telegram** : `python-telegram-bot` 21.x
- **API Polymarket** :
  - CLOB client (`py-clob-client`) pour passer les ordres
  - Gamma API pour les positions/markets (monitoring)
- **Base de données** : PostgreSQL (prod via Docker), SQLite (tests)
- **ORM** : SQLAlchemy (async) + Pydantic
- **Cache / rate limiting** : Redis
- **Blockchain** :
  - Web3.py pour Polygon (USDC, MATIC, transferts, soldes)
  - Gestion de clés privées chiffrées (AES-256-GCM)
- **Infra** : Docker + docker-compose

---

### Lancement rapide (Docker recommandé)

1. **Cloner le repo**

```bash
git clone https://github.com/Torkor29/WENPOLYMARKET.git
cd WENPOLYMARKET
```

2. **Copier et remplir `.env`**

```bash
copy .env.example .env
```

Dans `.env`, au minimum :

- `TELEGRAM_TOKEN` : token de ton bot (@BotFather)
- `ADMIN_CHAT_ID` : ton ID Telegram (via @userinfobot)
- `FEES_WALLET` : ton wallet Polygon pour recevoir les éventuels frais (peut rester placeholder si non utilisé au début)
- `ENCRYPTION_KEY` : générer avec :

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

3. **Lancer avec Docker**

```bash
docker-compose up --build
```

Le bot sera alors en train de :
- initialiser la base,
- se connecter à Redis,
- démarrer le bot Telegram,
- démarrer le monitor multi-wallets.

---

### Flux utilisateur

1. **Inscription**

- L’utilisateur envoie `/start` au bot.
- Il choisit :
  - **Créer un wallet Polygon** : le bot génère une adresse 0x… dédiée au copy-trading, chiffrée et stockée.
  - **J’ai déjà un wallet** : mode avancé où il fournit son adresse + clé privée (chiffrée côté serveur).

2. **Dépôt de fonds**

- Commande `/deposit` ou via `/balance` :
  - **💳 Acheter USDC** via Transak (lien pré-rempli, USDC sur Polygon, wallet de l’utilisateur).
  - **Depuis un exchange** : retrait USDC réseau Polygon vers son adresse.
  - **🌉 Bridge SOL → USDC** via `/bridge`.

3. **Choix des traders à copier**

- Commande `/settings` → bouton **“Gérer les traders suivis”**.
- L’utilisateur ajoute les **adresses Polygon** des comptes Polymarket à suivre.
- Le monitor surveille ensuite les positions de ces wallets et émet des signaux d’achat/vente vers le moteur de copie.

4. **Suivi et contrôle**

- `/balance` : vue synthétique des soldes, positions, frais.
- `/positions` : dernières positions copiées.
- `/history` : historique des trades et frais.
- `/pause` / `/resume` : mettre le copy-trading en pause / reprise.

---

### Points clés sécurité

- **Clés privées chiffrées** en AES-256-GCM, avec une clé maître `ENCRYPTION_KEY` + un sel par utilisateur.
- Les messages Telegram contenant des clés privées sont **supprimés immédiatement**.
- Possibilité pour l’utilisateur de **ne jamais partager sa clé privée principale** en choisissant la création d’un wallet dédié au copy-trading, et en y déposant simplement des USDC par transaction on-chain.

---

### Roadmap “sniping / arbitrage”

Cette version met en place :

- le modèle de données (trades, wallets suivis, moteur de copie),
- le monitor multi-wallets basé sur les positions Polymarket,
- les hooks nécessaires dans le moteur de copie pour gérer des signaux externes.

Prochaine étape naturelle : ajouter un **indexer on-chain** (service séparé) connecté à un **RPC WebSocket Polygon**, pour :

- écouter en temps réel les transactions des wallets master vers le contrat CLOB de Polymarket,
- décoder les ordres (token, side, prix, taille),
- pousser ces signaux au bot via Redis ou HTTP interne,
- réduire drastiquement la latence de détection pour du sniping / arbitrage.

