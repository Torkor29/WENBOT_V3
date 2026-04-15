## Instructions diverses

### 1. Gérer le fichier `.env` sur le serveur

Emplacement supposé du projet : `/opt/wenpolymarket`

- **Afficher le `.env` :**

```bash
cd /opt/wenpolymarket
cat .env
```

- **Éditer le `.env` :**

```bash
cd /opt/wenpolymarket
nano .env
```

Dans `nano` :

- `Ctrl+O` puis `Enter` pour sauvegarder.
- `Ctrl+X` pour quitter.

Variables importantes à vérifier / renseigner :

- `TELEGRAM_TOKEN`
- `ADMIN_CHAT_ID`
- `ENCRYPTION_KEY`
- `POLYGON_RPC_URL`
- `DB_URL`
- `REDIS_URL`
- `WELCOME_BANNER_URL` (optionnel – URL de la bannière /start)

---

### 2. Mettre à jour le serveur après un `git push`

Chaque fois que tu as poussé du code sur GitHub (`main`) :

```bash
cd /opt/wenpolymarket

# Récupérer la dernière version du code
git pull origin main

# Rebuild + relancer les conteneurs en arrière-plan
docker compose up --build -d

# (Optionnel) Vérifier que tout tourne
docker compose ps
docker logs -f polybot   # Ctrl+C pour quitter les logs
```

Pour l’instant, le déploiement est manuel (simple et sûr). Plus tard, on pourra automatiser (GitHub Actions + SSH) si besoin.

---

### 3. Héberger l’image de bannière (`WELCOME_BANNER_URL`)

Objectif : afficher une bannière (logo) dans le message `/start` des nouveaux utilisateurs.

1. **Ajouter l’image dans le repo (en local) :**

```bash
cd /chemin/vers/WENPOLYMARKET
mkdir -p branding
cp /chemin/vers/ton-image.png branding/wenpolymarket-banner.png

git add branding/wenpolymarket-banner.png
git commit -m "Ajoute bannière WenPolymarket"
git push origin main
```

2. **Récupérer l’URL “raw” sur GitHub :**

- Aller sur GitHub → repo `WENPOLYMARKET` → dossier `branding` → `wenpolymarket-banner.png`.
- Cliquer sur **Raw**.
- Copier l’URL complète, de type :

```text
https://raw.githubusercontent.com/Torkor29/WENPOLYMARKET/main/branding/wenpolymarket-banner.png
```

3. **Configurer la variable d’environnement sur le serveur :**

```bash
cd /opt/wenpolymarket
nano .env
```

Ajouter / modifier :

```env
WELCOME_BANNER_URL=https://raw.githubusercontent.com/Torkor29/WENPOLYMARKET/main/branding/wenpolymarket-banner.png
```

Sauvegarder (`Ctrl+O`, `Enter`, `Ctrl+X`), puis relancer le bot :

```bash
docker compose up --build -d
```

À partir de là, le message d’accueil `/start` utilisera cette image comme bannière.




Pour voir les logs du VPS :

```bash
cd /opt/wenpolymarket
docker compose ps
docker logs -n 80 polybot
```

---

### 4. Template `.env` complet pour le VPS (tout pour faire tourner le bot)

Copie ce bloc dans ton `.env` sur le VPS, puis remplace les valeurs entre `<>`.

**Obligatoire** : Telegram, `ENCRYPTION_KEY`, `DB_URL`, `REDIS_URL`, `POLYGON_RPC_URL` (Alchemy).  
**WebSocket CLOB** : aucune clé à mettre, le bot utilise l’URL publique Polymarket.

| Variable | Obligatoire | À quoi ça sert |
|----------|-------------|----------------|
| `TELEGRAM_TOKEN` | Oui | Token du bot (BotFather) |
| `ADMIN_CHAT_ID` | Oui | Ton ID Telegram (admin) |
| `ENCRYPTION_KEY` | Oui | Clé pour chiffrer les clés privées (génère une longue chaîne aléatoire) |
| `DB_URL` | Oui | Connexion Postgres (Docker) |
| `REDIS_URL` | Oui | Connexion Redis (Docker) |
| `POLYGON_RPC_URL` | Oui | RPC Polygon (Alchemy, etc.) — solde, exécution des trades |
| `FEES_WALLET` | Non | Adresse qui reçoit les frais (vide = pas de frais) |
| `WELCOME_BANNER_URL` | Non | URL de l’image bannière /start |

```env
# --- Telegram (obligatoire) ---
TELEGRAM_TOKEN=<ton_token_botfather>
ADMIN_CHAT_ID=<ton_telegram_user_id>

# --- Chiffrement des wallets (obligatoire) ---
ENCRYPTION_KEY=<une_cle_longue_aleatoire_32_caracteres_min>

# --- Base de données + Redis (obligatoire, ne pas modifier si Docker standard) ---
DB_URL=postgresql+asyncpg://polybot:polybot_dev@db:5432/polybot
REDIS_URL=redis://redis:6379

# --- Polygon / Web3 — Alchemy (obligatoire pour trades + soldes) ---
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/<TA_CLE_ALCHEMY>

# --- Polling + WebSocket (optionnel) ---
# Le WebSocket CLOB n'a pas besoin de clé. Intervalle de secours en secondes.
MONITOR_POLL_INTERVAL=15

# --- Frais (optionnel) ---
FEES_WALLET=
PLATFORM_FEE_RATE=0.01

# --- Exécution (optionnel) ---
MAX_CONCURRENT_TRADES=20
COLLECT_FEES_ONCHAIN=false

# --- Bridge / Transak (optionnel) ---
LIFI_API_KEY=
ACROSS_API_URL=https://across.to/api
BRIDGE_SLIPPAGE=0.005
TRANSAK_API_KEY=

# --- Bannière /start (optionnel) ---
WELCOME_BANNER_URL=
```