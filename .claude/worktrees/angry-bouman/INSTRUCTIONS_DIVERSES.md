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
cd /opt/wenpolymarket
docker compose ps
docker logs -n 80 polybot