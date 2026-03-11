# Guide de lancement du Bot CopyTrading Polymarket

## Qu'est-ce que ce bot ?

Un bot Telegram qui permet à chaque utilisateur de choisir quels traders Polymarket copier automatiquement. Chaque utilisateur gère sa propre liste de traders à suivre, et le bot copie les trades en temps réel sur leur wallet.

---

## Qui configure quoi ?

### VOUS (Admin / Opérateur du bot)

Vous configurez le serveur une seule fois via le fichier `.env`. C'est purement technique — pas de configuration de trading.

| Ce que vous fournissez | Où | Pourquoi |
|------------------------|----|----------|
| Token du bot Telegram | `.env` → `TELEGRAM_TOKEN` | Pour que le bot Telegram fonctionne |
| Votre ID Telegram | `.env` → `ADMIN_CHAT_ID` | Pour accéder au panneau `/admin` |
| Adresse wallet pour les frais | `.env` → `FEES_WALLET` | Wallet où vous recevez le 1% de frais par trade |
| Clé de chiffrement serveur | `.env` → `ENCRYPTION_KEY` | Pour chiffrer les clés privées des utilisateurs en base |
| Intervalle de monitoring | `.env` → `MONITOR_POLL_INTERVAL` | Fréquence de scan des positions (15s par défaut) |
| Paramètres infra | `.env` → `DB_URL`, `REDIS_URL` | Base de données et cache |

**Vous n'avez PAS besoin de :**
- Clé API Polymarket (les positions des traders sont publiques)
- Adresse d'un trader master (chaque utilisateur choisit les siens)

### LES UTILISATEURS (Followers)

Tout se fait via Telegram. Zéro fichier à toucher.

| Ce qu'ils font | Comment | Pourquoi |
|----------------|---------|----------|
| S'inscrire | `/start` sur Telegram | Crée leur compte |
| Fournir leur wallet Polygon | `/start` (étape 1/2) | Pour identifier leur compte Polymarket |
| Fournir leur clé privée | `/start` (étape 2/2) | Pour passer des ordres en leur nom |
| Choisir les traders à copier | `/settings` → "Gérer les traders suivis" | Ajouter/retirer des adresses de traders |
| Configurer le copy-trading | `/settings` | Capital, sizing, stop-loss, etc. |

**Comment ça marche pour les utilisateurs :**
1. Ils s'inscrivent via `/start` (wallet + clé privée)
2. Ils vont dans `/settings` → "Gérer les traders suivis"
3. Ils ajoutent l'adresse Polygon d'un trader Polymarket (0x...)
4. Le bot surveille les positions de ce trader et copie automatiquement
5. Ils peuvent ajouter/retirer des traders à tout moment

**Les utilisateurs n'ont PAS besoin de :**
- Clé API Polymarket (dérivée automatiquement de leur clé privée)
- Accéder au serveur ou à un fichier de configuration

---

## Prérequis (Admin)

| Outil | Version minimale | Obligatoire ? |
|-------|-----------------|---------------|
| Python | 3.12 | Oui (mode local) |
| Docker + Docker Compose | Dernière version stable | Oui (mode Docker) |
| Un bot Telegram | Créé via [@BotFather](https://t.me/BotFather) | Oui |

---

## Etape 1 — Configurer le fichier .env (Admin uniquement)

1. Copier le fichier d'exemple :

```powershell
copy .env.example .env
```

2. Remplir les variables :

### Bloc Telegram

| Variable | Comment l'obtenir |
|----------|-------------------|
| `TELEGRAM_TOKEN` | Créer un bot via [@BotFather](https://t.me/BotFather) sur Telegram |
| `ADMIN_CHAT_ID` | Envoyer un message à [@userinfobot](https://t.me/userinfobot) |

### Bloc Frais

| Variable | Description |
|----------|-------------|
| `FEES_WALLET` | Votre adresse Polygon (0x...) pour recevoir les frais (1%) |
| `PLATFORM_FEE_RATE` | `0.01` = 1% par défaut |

### Bloc Chiffrement

| Variable | Comment l'obtenir |
|----------|-------------------|
| `ENCRYPTION_KEY` | Générer avec la commande ci-dessous |

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

**Ne perdez pas cette clé** — sans elle, les clés privées stockées deviennent indéchiffrables.

### Bloc Monitoring

| Variable | Description |
|----------|-------------|
| `MONITOR_POLL_INTERVAL` | Fréquence de scan en secondes (défaut : 15) |

### Bloc Infrastructure

| Variable | Valeur recommandée |
|----------|--------------------|
| `DB_URL` | `postgresql+asyncpg://polybot:polybot_dev@db:5432/polybot` (Docker) ou `sqlite+aiosqlite:///./polybot.db` (local) |
| `REDIS_URL` | `redis://redis:6379` (Docker) — optionnel en local |

### Bloc Bridge (optionnel)

| Variable | Description |
|----------|-------------|
| `LIFI_API_KEY` | Clé API Li.Fi pour le bridge SOL → USDC |
| `ACROSS_API_URL` | URL API Across (défaut : `https://across.to/api`) |
| `BRIDGE_SLIPPAGE` | Slippage toléré (défaut : `0.005` = 0.5%) |

---

## Etape 2 — Lancer le bot (Admin uniquement)

### Option A : avec Docker (recommandé)

```powershell
docker-compose up --build
```

En arrière-plan :

```powershell
docker-compose up --build -d
```

Voir les logs :

```powershell
docker-compose logs -f bot
```

Arrêter :

```powershell
docker-compose down
```

### Option B : en local (développement)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ajuster `.env` pour le mode local :

```
DB_URL=sqlite+aiosqlite:///./polybot.db
```

Lancer :

```powershell
python -m bot.main
```

---

## Etape 3 — Vérifier que tout fonctionne (Admin)

1. Ouvrir Telegram et chercher votre bot par son nom
2. Envoyer `/start` — le bot affiche le message de bienvenue
3. S'inscrire pour tester le flux d'onboarding
4. Aller dans `/settings` → "Gérer les traders suivis" → ajouter une adresse de test

---

## Parcours utilisateur complet

### Inscription (via `/start`)

1. L'utilisateur envoie `/start` au bot
2. Il clique "Commencer l'inscription"
3. Il choisit :
   - **Créer un wallet Polygon** (recommandé pour débuter), ou
   - **J'ai déjà un wallet** (il fournit alors son adresse 0x… et sa clé privée, qui est chiffrée immédiatement)
4. Le compte est créé en mode Paper Trading

### Choisir les traders à copier (via `/settings`)

1. L'utilisateur envoie `/settings`
2. Il clique "Gérer les traders suivis"
3. Il clique "Ajouter un trader" et envoie l'adresse Polygon du trader
4. Le bot commence à surveiller ce trader et copie ses positions
5. Il peut ajouter autant de traders qu'il veut, ou en retirer

### Commandes disponibles

| Commande | Description |
|----------|-------------|
| `/start` | Inscription / voir son profil |
| `/settings` | Gérer traders suivis + paramètres de copie |
| `/balance` | Voir le solde du wallet |
| `/deposit` | Voir comment déposer des USDC (carte, exchange, bridge) |
| `/pause` | Mettre la copie en pause |
| `/resume` | Reprendre la copie |
| `/bridge` | Pont SOL → USDC sur Polygon |
| `/admin` | Administration (admin uniquement) |

---

## Lancer les tests

```powershell
python -m pytest tests/ -v
```

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `ModuleNotFoundError` | Vérifier que le venv est activé + `pip install -r requirements.txt` |
| `TELEGRAM_TOKEN manquant` | Vérifier le fichier `.env` |
| Erreur de connexion DB | Docker : `docker-compose up db`. Local : utiliser SQLite |
| Le bot ne copie pas | L'utilisateur a-t-il ajouté un trader via `/settings` ? Est-il en Paper Trading ? |
| Aucun trader surveillé | Vérifier les logs — le monitor affiche le nombre de wallets surveillés |

---

## Architecture

```
bot/
├── main.py              → Point d'entrée
├── config.py            → Configuration (lit .env)
├── handlers/
│   ├── start.py         → Inscription (/start)
│   ├── settings.py      → Paramètres + gestion traders suivis
│   ├── balance.py       → Soldes (/balance)
│   ├── controls.py      → Pause/resume
│   ├── admin.py         → Administration
│   └── bridge.py        → Bridge SOL→USDC
├── services/
│   ├── polymarket.py    → API Polymarket (positions publiques + ordres)
│   ├── monitor.py       → MultiMasterMonitor (surveille tous les wallets suivis)
│   ├── copytrade.py     → Moteur de copie (filtre par wallet suivi)
│   ├── crypto.py        → Chiffrement AES-256-GCM
│   └── ...
├── models/
│   ├── user.py          → Utilisateurs
│   ├── settings.py      → Paramètres (dont followed_wallets)
│   ├── trade.py         → Historique des trades (dont master_wallet)
│   └── ...
└── db/
    └── session.py       → Session base de données
```

---

## Résumé express

```powershell
# 1. Configurer (admin — une seule fois)
copy .env.example .env
# Remplir : TELEGRAM_TOKEN, ADMIN_CHAT_ID, FEES_WALLET, ENCRYPTION_KEY

# 2. Lancer
docker-compose up --build

# 3. Les utilisateurs s'inscrivent via /start
#    Puis choisissent qui copier via /settings → "Gérer les traders suivis"
```
