CLAUDE CODE — Refactor signer.py et executor.py avec le code Polymarket prouvé
Contexte
Le fichier reference/live_executor_original.py (ci-joint) est le code qui tourne en production sur notre bot Polymarket actuel. Il fonctionne. Il faut l'utiliser comme base pour réécrire wallet/signer.py et engine/executor.py du projet copytrade, en le rendant clean, async, et multi-wallet.
Ne réinvente PAS la communication avec Polymarket. Utilise exactement les mêmes patterns que le LiveExecutor original (init ClobClient, create_or_derive_api_creds, MarketOrderArgs, FOK→FAK fallback, etc.). Le code original MARCHE, il faut juste le restructurer.

Fichier de référence à copier dans le repo
Copie le contenu du fichier reference/live_executor_original.py tel quel. C'est la source de vérité pour tout ce qui touche à py_clob_client.

Ce qui doit changer par rapport à l'original
1. Multi-wallet au lieu de single wallet
L'original charge UNE clé privée depuis os.environ['POLYMARKET_PK'] au démarrage.
Le copytrade doit créer un ClobClient par wallet, à la volée, au moment du trade. Chaque user a sa propre clé privée (déchiffrée depuis Supabase). Le client est créé, utilisé, puis détruit (pas de cache de clients avec des clés en mémoire).
python# PATTERN À SUIVRE dans wallet/signer.py :
async def create_clob_client(private_key: str) -> ClobClient:
    """Crée un ClobClient éphémère pour un wallet donné."""
    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=private_key,
        signature_type=0,  # EOA wallet (pas proxy/funder)
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client
IMPORTANT : signature_type=0 pour les wallets EOA créés par notre système (pas de funder/proxy). L'original utilise signature_type=2 parce que c'est un wallet Polymarket avec proxy. Nos wallets sont des EOA purs.
2. Async au lieu de sync
L'original est synchrone (time.sleep, pas d'await). Le copytrade est full async (aiogram, asyncio).
Wrappe les appels bloquants py_clob_client dans asyncio.to_thread() :
python# py_clob_client est sync, on le wrappe :
book = await asyncio.to_thread(client.get_order_book, token_id)
signed = await asyncio.to_thread(client.create_market_order, order)
result = await asyncio.to_thread(client.post_order, signed, OrderType.FAK)
3. BUY + SELL + REDEEM — tout garder
La stratégie peut envoyer des signaux BUY et SELL. Le signal Redis contient "action": "BUY" ou "action": "SELL". L'execution engine doit gérer les deux.
BUY : exactement comme l'original (FOK→FAK fallback, best_ask + 0.05 margin, pre-approve conditional token).
SELL : exactement comme l'original (vérif share balance, retry loop avec backoff 5s, FOK→FAK, détection erreurs fatales market closed/resolved). Adapter pour multi-wallet (get_share_balance par wallet).
REDEEM : garder la logique redeem_all de l'original. Le cron de résolution peut appeler redeem après avoir détecté que des marchés sont clos. Nécessite les Builder API creds (BUILDER_API_KEY, BUILDER_API_SECRET, BUILDER_API_PASSPHRASE).
Le signal Redis étendu :
json{
    "strategy_id": "strat_alpha_v1",
    "action": "BUY",          // ou "SELL"
    "side": "YES",
    "market_slug": "btc-updown-5m-1774013700",
    "token_id": "24309598195452...",
    "max_price": 0.65,         // pour BUY: prix max acceptable
    "shares": 8.0,             // pour SELL: nombre de shares à vendre (optionnel pour BUY)
    "confidence": 0.82,
    "timestamp": 1774013670.123
}
4. Logging propre avec le module logging Python
Remplace tous les print(f"  [EXECUTOR] ...") par du logging.getLogger(__name__). Plus de flush=True partout.

Structure finale attendue
wallet/signer.py — Communication Polymarket
python"""
Polymarket CLOB signer — crée des ordres signés pour n'importe quel wallet.

Basé sur le LiveExecutor prouvé en production.
Adapté pour multi-wallet (1 ClobClient éphémère par trade).

Endpoints utilisés :
  - https://clob.polymarket.com/book  → orderbook (best ask)
  - https://clob.polymarket.com       → post order (FAK)
  - Gamma API pour la résolution (dans resolver.py, pas ici)
"""

# À implémenter :

async def create_clob_client(private_key: str) -> ClobClient:
    """Crée un ClobClient éphémère pour un wallet.
    signature_type=0 (EOA), chain_id=137 (Polygon).
    Dérive les API creds automatiquement."""

async def get_best_ask(client: ClobClient, token_id: str) -> float | None:
    """Récupère le meilleur ask depuis l'orderbook CLOB.
    Exactement comme l'original : client.get_order_book(token_id) → min(asks)."""

async def approve_conditional_token(client: ClobClient, token_id: str):
    """Pre-approve le token conditionnel.
    Exactement comme l'original : client.update_balance_allowance(CONDITIONAL)."""

async def place_buy_order(
    private_key: str,
    token_id: str,
    amount_usdc: float,
    max_price: float = 0.95,
) -> dict:
    """Place un ordre BUY sur Polymarket CLOB.
    
    Flow (EXACTEMENT comme l'original) :
    1. Crée ClobClient éphémère
    2. Get best_ask depuis orderbook
    3. Guard: refuse si best_ask > max_price
    4. Pre-approve conditional token
    5. Calcule buy_price = min(best_ask + 0.05, 0.95)
    6. Tente FOK d'abord
    7. Si FOK échoue → fallback FAK
    8. Retourne {success, status, order_id, shares, cost, entry_price}
    
    Retourne :
    {
        "success": bool,
        "partial": bool,
        "status": str,             # FULL_SUCCESS | PARTIAL_SUCCESS | FAILED | REJECTED
        "order_id": str,
        "shares": float,           # takingAmount
        "cost": float,             # makingAmount (USDC réellement dépensé)
        "entry_price": float,      # cost / shares
    }
    """

async def place_sell_order(
    private_key: str,
    token_id: str,
    shares: float,
) -> dict:
    """Place un ordre SELL sur Polymarket CLOB.
    
    Flow (EXACTEMENT comme l'original sell()) :
    1. Crée ClobClient éphémère
    2. Approve conditional token
    3. Get share balance réel pour ce wallet
    4. Boucle retry (max 12 attempts, 5s entre chaque) :
       a. Vérif share balance disponible
       b. Get best_bid depuis orderbook
       c. Calcule sell_price = max(best_bid - 0.05, 0.01)
       d. FOK au premier essai, FAK ensuite
       e. Si partial → continue la boucle avec le restant
       f. Si erreur fatale (market closed/resolved) → abort
    5. Retourne {success, status, order_id, sold, remaining, received}
    
    Retourne :
    {
        "success": bool,
        "partial": bool,
        "status": str,             # FULL_SUCCESS | PARTIAL_SUCCESS | FAILED | ABORTED_FATAL
        "order_id": str,
        "sold": float,
        "remaining": float,
        "received": float,         # USDC reçus
    }
    """

async def get_share_balance(private_key: str, token_id: str) -> float | None:
    """Récupère le nombre de shares d'un token pour un wallet.
    Comme l'original : client.get_balance_allowance(CONDITIONAL, token_id).
    Attention : le balance est en base units (6 décimales), diviser par 1e6."""

async def redeem_positions(private_key: str) -> list | None:
    """Redeem toutes les positions résolues gagnantes d'un wallet.
    
    Comme l'original redeem_all() :
    - Nécessite Builder API creds (BUILDER_API_KEY, BUILDER_API_SECRET, BUILDER_API_PASSPHRASE)
    - Utilise RelayClient + PolyWeb3Service
    - Retourne la liste des positions redeemed ou None
    
    Les Builder API creds sont dans les env vars, communes à tous les wallets.
    Le private_key est celui du wallet user (pour signer la tx redeem).
    """

async def get_clob_balance(private_key: str) -> float | None:
    """Récupère le solde USDC via le CLOB API (collateral balance).
    Comme l'original : client.get_balance_allowance(COLLATERAL)."""
engine/executor.py — Exécution de trade pour un user
python"""
Trade executor — exécute un trade pour un user donné.

Orchestre : déchiffrement wallet → fee tx → ordre Polymarket → log Supabase.
Utilise wallet/signer.py pour la communication Polymarket.
Utilise wallet/encrypt.py pour le déchiffrement.
Utilise web3.py pour les transferts USDC.e (fee).
"""

# À implémenter :

async def execute_trade_for_user(
    user: User,
    signal: Signal,
    subscription: Subscription,
    priority: int,
) -> Trade | None:
    """Exécute un trade complet pour un user.
    
    Si signal.action == "BUY" :
    1. Déchiffre la clé privée
    2. Calcule fee = trade_size * trade_fee_rate
    3. Envoie fee USDC.e → WENBOT_FEE_WALLET (web3.py)
    4. Place l'ordre BUY sur Polymarket (signer.place_buy_order)
    5. Insère le trade dans Supabase
    
    Si signal.action == "SELL" :
    1. Déchiffre la clé privée
    2. PAS DE FEE sur les SELL (la fee a déjà été prise au BUY)
    3. Place l'ordre SELL sur Polymarket (signer.place_sell_order)
    4. Insère le trade dans Supabase avec les USDC reçus
    
    Retourne l'objet Trade ou None si échec.
    """

async def send_trade_fee(private_key: str, fee_amount: float) -> str | None:
    """Envoie la trade fee en USDC.e vers WENBOT_FEE_WALLET.
    Utilise web3.py (PAS py_clob_client — c'est un ERC-20 transfer, pas un ordre CLOB).
    
    USDC.e contract : 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
    Décimales : 6 (amount_wei = int(amount * 1_000_000))
    
    Retourne le tx hash ou None si échec."""

async def try_redeem_for_user(user: User):
    """Tente de redeem les positions résolues d'un user.
    Appelé par le resolver après avoir détecté des marchés clos.
    Utilise signer.redeem_positions(private_key)."""
engine/resolver.py — Résolution des marchés
python"""
Market resolver — poll Gamma API pour déterminer le résultat des marchés.

Endpoint : https://gamma-api.polymarket.com/events/slug/{slug}
"""

# À implémenter :

async def poll_and_resolve():
    """Tourne en boucle, poll toutes les 30s les trades PENDING/PLACED.
    
    Pour chaque trade non résolu :
    1. Fetch https://gamma-api.polymarket.com/events/slug/{market_slug}
    2. Check si le marché est résolu (closed=True, resolved=True)
    3. Détermine le winner (le token avec price=1.0 ou le dernier outcome)
    4. Calcule PnL = (shares * win_price) - cost  (win_price = 1.0 si gagné, 0.0 si perdu)
    5. Update le trade dans Supabase (result=WON/LOST, pnl=X)
    6. Update les stats de la stratégie
    7. Notifie le user via Telegram
    8. Tente redeem_positions() pour les users avec des trades résolus gagnants
    """

Règles obligatoires

Ne change PAS les patterns py_clob_client qui marchent dans l'original. ClobClient init, create_or_derive_api_creds, MarketOrderArgs, FOK→FAK — tout ça reste identique.
signature_type=0 pour nos wallets EOA (pas 2 comme dans l'original).
Pas de funder — nos wallets n'ont pas de proxy Polymarket.
asyncio.to_thread() pour wrapper tous les appels sync py_clob_client.
Jamais de clé privée dans les logs. Utilise private_key[:10]+"..." si tu dois loguer pour debug.
Le ClobClient est éphémère — créé pour un trade, détruit après. Pas de pool de clients avec des clés en mémoire.
La fee USDC.e passe par web3.py (ERC-20 transfer), pas par py_clob_client. Ce sont deux choses différentes : web3 = blockchain transaction, py_clob_client = CLOB API order.
Fees uniquement sur les BUY, pas sur les SELL. La fee a été prélevée à l'achat.
Builder API creds (pour redeem) dans les env vars : BUILDER_API_KEY, BUILDER_API_SECRET, BUILDER_API_PASSPHRASE. Ce sont des creds globales, pas par wallet.


Comment procéder

Copie reference/live_executor_original.py dans le repo (comme référence, pas exécuté)
Réécris wallet/signer.py en extrayant la logique Polymarket de l'original
Réécris engine/executor.py en utilisant signer.py + web3 pour les fees
Réécris engine/resolver.py avec le poll Gamma API
Mets à jour les tests pour couvrir le nouveau code
Vérifie que les imports py_clob_client sont corrects (pas de hack sys.path)
