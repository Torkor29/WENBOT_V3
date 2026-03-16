"""Smart market categorization for Polymarket markets.

Analyzes market titles/slugs to classify them into categories and sub-categories.
Used for per-trader filtering (e.g., follow a trader for BTC but not XRP).
"""

import re
from dataclasses import dataclass
from typing import Optional

# ── Category definitions ──────────────────────────────────────────────
# Each top-level category has sub-categories with keyword lists.
# Keywords are matched case-insensitively against market title + slug.

CATEGORY_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "Crypto": {
        "BTC": ["bitcoin", "btc", "₿"],
        "ETH": ["ethereum", " eth ", "ether"],
        "SOL": ["solana", " sol "],
        "XRP": ["xrp", "ripple"],
        "DOGE": ["doge", "dogecoin"],
        "ADA": ["cardano", " ada "],
        "AVAX": ["avalanche", "avax"],
        "MATIC": ["polygon", "matic", " pol "],
        "DOT": ["polkadot", " dot "],
        "LINK": ["chainlink", "link"],
        "BNB": [" bnb ", "binance coin"],
        "LTC": ["litecoin", " ltc "],
        "NEAR": [" near "],
        "APT": ["aptos", " apt "],
        "ARB": ["arbitrum", " arb "],
        "OP": ["optimism", " op "],
        "SUI": [" sui "],
        "PEPE": [" pepe "],
        "SHIB": ["shiba", " shib "],
        "WIF": [" wif "],
        "TRUMP": ["trump coin", "trump token", "$trump", "official trump"],
        "MEME": ["memecoin", "meme coin"],
        "_general": [
            "crypto", "token", "defi", "nft", "blockchain",
            "halving", "staking", "airdrop",
        ],
    },
    "Politics": {
        "US": [
            "trump", "biden", "harris", "desantis", "congress",
            "senate", "democrat", "republican", "white house",
            "presidential", "gop",
        ],
        "Elections": ["election", "vote", "ballot", "primary", "caucus", "midterm"],
        "World": [
            "macron", "putin", "zelensky", "xi jinping",
            "nato", "eu ", "european union", "united nations", "un ",
            "brexit",
        ],
        "_general": [
            "politic", "government", "president", "minister",
            "legislation", "bill ", "executive order",
        ],
    },
    "Sports": {
        "NFL": ["nfl", "super bowl", "touchdown", "quarterback"],
        "NBA": ["nba", "basketball", "lakers", "celtics"],
        "MLB": ["mlb", "baseball", "world series"],
        "Soccer": [
            "soccer", "premier league", "champions league",
            "la liga", "bundesliga", "serie a", "mls",
            "fifa", "world cup",
        ],
        "UFC/MMA": ["ufc", "mma", "fight night", "bellator"],
        "F1": ["formula 1", " f1 ", "grand prix"],
        "Tennis": ["tennis", "wimbledon", "us open", "roland garros"],
        "Golf": ["golf", "pga", "masters tournament"],
        "NHL": ["nhl", "hockey", "stanley cup"],
        "_general": [
            "sport", "game score", "championship", "tournament",
            "playoff", "finals",
        ],
    },
    "Economy": {
        "Fed": [
            "federal reserve", "fed ", "interest rate", "fomc",
            "powell", "rate cut", "rate hike",
        ],
        "Markets": [
            "s&p", "nasdaq", "dow jones", " spy ", "stock market",
            "wall street", "nyse",
        ],
        "Inflation": ["inflation", "cpi", "ppi", "consumer price"],
        "GDP": ["gdp", "recession", "economic growth"],
        "Jobs": ["jobs report", "unemployment", "nonfarm", "payroll"],
        "_general": [
            "economy", "economic", "fiscal", "monetary",
            "treasury", "bond", "yield",
        ],
    },
    "Entertainment": {
        "Awards": ["oscar", "grammy", "emmy", "golden globe", "academy award"],
        "Music": ["album", "billboard", "spotify", "concert", "tour"],
        "Movies/TV": ["box office", "netflix", "disney", "movie", "series"],
        "Celebrity": ["celebrity", "kardashian", "swift", "beyonce"],
        "_general": ["entertainment", "pop culture", "viral"],
    },
    "Tech": {
        "AI": [
            "artificial intelligence", " ai ", "openai", "chatgpt",
            "claude", "gemini", "llm", "machine learning",
        ],
        "Companies": [
            "apple", "google", "microsoft", "meta", "amazon",
            "tesla", "nvidia", "spacex",
        ],
        "_general": ["tech", "technology", "software", "hardware", "startup"],
    },
    "Weather": {
        "_general": [
            "weather", "temperature", "rain", "snow", "hurricane",
            "tornado", "heat wave", "cold wave", "forecast",
        ],
    },
    "Science": {
        "_general": [
            "science", "space", "nasa", "mars", "moon",
            "vaccine", "pandemic", "virus", "study",
        ],
    },
}

# Crypto price pattern: "BTC above $85,000" or "Bitcoin above $X at Y PM"
CRYPTO_PRICE_PATTERN = re.compile(
    r"(btc|bitcoin|eth|ethereum|sol|solana|xrp|doge|ada|bnb|ltc|avax|dot|link|"
    r"near|apt|arb|shib|pepe|sui|wif|matic|pol)\b.*"
    r"(above|below|over|under|reach|hit|price|at \$)",
    re.IGNORECASE,
)

# Ticker-like patterns at start of title: "BTC above $X"
TICKER_PATTERN = re.compile(
    r"^(BTC|ETH|SOL|XRP|DOGE|ADA|AVAX|MATIC|DOT|LINK|BNB|LTC|NEAR|APT|ARB|OP|SUI|PEPE|SHIB|WIF|POL)\b",
    re.IGNORECASE,
)


@dataclass
class MarketCategory:
    """Categorization result for a market."""
    category: str          # Top-level: "Crypto", "Politics", "Sports", etc.
    subcategory: str       # Sub-level: "BTC", "NFL", "US", etc.
    tag: str               # Display tag: "Crypto/BTC", "Sports/NFL"
    confidence: float      # 0.0 to 1.0

    def __str__(self) -> str:
        return self.tag


def categorize_market(
    title: str,
    slug: str = "",
    api_category: str = "",
) -> MarketCategory:
    """Categorize a market based on its title, slug, and optional API category.

    Returns the most specific category found. Falls back to "Other" if no match.

    Args:
        title: Market question/title (e.g., "BTC above $85,000 at 3:00 PM?")
        slug: URL slug (e.g., "btc-above-85000-march-21")
        api_category: Category from Polymarket API (groupItemTitle)

    Returns:
        MarketCategory with category, subcategory, and display tag.
    """
    # Combine title + slug for broader matching
    text = f" {title} {slug} ".lower()

    # 1. Quick check: ticker at start of title (most common for crypto price markets)
    ticker_match = TICKER_PATTERN.match(title.strip())
    if ticker_match:
        ticker = ticker_match.group(1).upper()
        # Map known tickers
        ticker_map = {
            "POL": "MATIC",
        }
        sub = ticker_map.get(ticker, ticker)
        return MarketCategory(
            category="Crypto",
            subcategory=sub,
            tag=f"Crypto/{sub}",
            confidence=0.95,
        )

    # 2. Scan all categories for keyword matches
    best_match: Optional[MarketCategory] = None
    best_score = 0

    for cat_name, subcats in CATEGORY_KEYWORDS.items():
        for subcat_name, keywords in subcats.items():
            if subcat_name == "_general":
                continue  # Check specific subcats first

            for kw in keywords:
                if kw in text:
                    # Score: longer keyword = more specific = higher confidence
                    score = len(kw) + (10 if subcat_name != "_general" else 0)
                    if score > best_score:
                        best_score = score
                        best_match = MarketCategory(
                            category=cat_name,
                            subcategory=subcat_name,
                            tag=f"{cat_name}/{subcat_name}",
                            confidence=min(0.9, 0.5 + score * 0.03),
                        )

    if best_match:
        return best_match

    # 3. Check general keywords (less specific)
    for cat_name, subcats in CATEGORY_KEYWORDS.items():
        general_kws = subcats.get("_general", [])
        for kw in general_kws:
            if kw in text:
                return MarketCategory(
                    category=cat_name,
                    subcategory="General",
                    tag=cat_name,
                    confidence=0.5,
                )

    # 4. Fallback to API category if provided
    if api_category:
        return MarketCategory(
            category=api_category,
            subcategory="General",
            tag=api_category,
            confidence=0.3,
        )

    # 5. Unknown
    return MarketCategory(
        category="Other",
        subcategory="Unknown",
        tag="Other",
        confidence=0.1,
    )


def categorize_markets_batch(
    items: list[dict],
) -> dict[str, list[dict]]:
    """Categorize a batch of markets/activities and group by tag.

    Args:
        items: List of dicts with at least 'title' key, optionally 'slug'.

    Returns:
        Dict mapping category tags to lists of items:
        {"Crypto/BTC": [...], "Sports/NFL": [...], ...}
    """
    groups: dict[str, list[dict]] = {}

    for item in items:
        cat = categorize_market(
            title=item.get("title", ""),
            slug=item.get("slug", ""),
        )
        item["_category"] = cat
        tag = cat.tag
        if tag not in groups:
            groups[tag] = []
        groups[tag].append(item)

    # Sort groups by count (most active first)
    return dict(sorted(groups.items(), key=lambda x: len(x[1]), reverse=True))


def get_all_category_tags() -> list[str]:
    """Return all possible category tags for UI display."""
    tags = []
    for cat_name, subcats in CATEGORY_KEYWORDS.items():
        for subcat_name in subcats:
            if subcat_name == "_general":
                tags.append(cat_name)
            else:
                tags.append(f"{cat_name}/{subcat_name}")
    return sorted(tags)
