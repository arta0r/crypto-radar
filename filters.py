"""فیلترهای کلیدواژه‌ای مشترک: تشخیص پروژه کریپتو/ان‌اف‌تی، رایگان بودن، تازه بودن، و پرچم‌های قرمز."""
import re

# ---------- تشخیص موضوع کریپتو / NFT ----------
CRYPTO_TERMS = [
    "nft", "airdrop", "mint", "token", "coin", "crypto", "web3", "defi",
    "solana", "ethereum", "eth", "bitcoin", "btc", "base chain", "arbitrum",
    "polygon", "matic", "bsc", "binance", "opensea", "magic eden", "magiceden",
    "wallet", "claim", "tge", "ido", "presale", "launchpad", "staking",
    "yield", "dao", "metaverse", "play-to-earn", "p2e", "collectible",
    "sui", "aptos", "ton", "near", "avalanche", "avax", "fantom", "blast",
    "zksync", "starknet", "inscription", "ordinals", "rarible", "blur",
]

# عبارات «قصد ثبت‌نام/کلایم» — پروژه باید واقعاً دعوت به اقدام بکند
# ساختار: (برچسب نمایشی، الگوی regex)
INTENT_PATTERNS = [
    ("airdrop", r"\bairdrop\w*\b"),
    ("free mint", r"\bfree\s+mint\b"),
    ("free claim", r"\bfree\s+claim\b"),
    ("mint", r"\bmint\w*\b"),
    ("claim", r"\bclaim\w*\b"),
    ("whitelist", r"\bwhitelist\w*\b"),
    ("allowlist", r"\ballowlist\w*\b"),
    ("presale", r"\bpresale\w*\b"),
    ("launch", r"\blaunch\w*\b"),
    ("TGE", r"\btge\b"),
    ("IDO", r"\bido\b"),
    ("registration", r"\bregistr\w*\b"),
    ("sign up", r"\bsign\s*up\b"),
    ("beta access", r"\bbeta\s+access\b"),
    ("early access", r"\bearly\s+access\b"),
    ("testnet", r"\btestnet\b"),
    ("snapshot", r"\bsnapshot\w*\b"),
    ("listing", r"\blisting\w*\b"),
    ("faucet", r"\bfaucet\w*\b"),
    ("mint starts", r"\bmint\s+starts\b"),
    ("goes live", r"\bgoes\s+live\b"),
    ("open now", r"\bopen\s+now\b"),
    ("live now", r"\blive\s+now\b"),
]

# عبارات «رایگان بودن» — شرط اصلی (با تطبیق سرکلمه‌ای تا «freezes» شبیه «free» شمرده نشود)
FREE_PATTERNS = [
    ("airdrop", r"\bairdrop\w*\b"),
    ("free mint", r"\bfree\s+mint\b"),
    ("free claim", r"\bfree\s+claim\b"),
    ("free NFT", r"\bfree\s+nft\b"),
    ("free token", r"\bfree\s+token\b"),
    ("free allocation", r"\bfree\s+allocation\b"),
    ("free project", r"\bfree\s+project\b"),
    ("claim your", r"\bclaim\s+your\b"),
    ("claim now", r"\bclaim\s+now\b"),
    ("claim free", r"\bclaim\s+free\b"),
    ("free", r"\bfree\b"),
    ("zero cost", r"\bzero[-\s]?cost\b"),
    ("no cost", r"\bno[-\s]?cost\b"),
    ("no payment", r"\bno\s+payment\b"),
    ("gasless", r"\bgasless\b"),
    ("mint for free", r"\bmint\s+for\s+free\b"),
    ("faucet", r"\bfaucet\w*\b"),
    ("grab your", r"\bgrab\s+your\b"),
    ("get your free", r"\bget\s+your\s+free\b"),
]

# ---------- پرچم‌های قرمز (نشانه کلاهبرداری) ----------
RED_FLAG_PATTERNS = [
    r"guaranteed (profit|return|income)",
    r"double your (money|eth|btc)",
    r"\b100x\b", r"\b1000x\b", r"\b10000x\b",
    r"risk[ -]?free",
    r"get rich",
    r"send \d+ (eth|btc|bnb|sol|usdt) to",
    r"deposit .* earn \d+",
    r"instant profit",
    r"no risk",
    r"ponzi", r"pyramid",
    r"limited slots",
    r"act (now|fast)",
    r"don.?t miss",
    r"\bfomo\b",
    r"official (binance|coinbase|ethereum|solana) giveaway",
    r"giveaway.*(eth|btc|sol)",
    r"guaranteed (free|airdrop) ?$",
    r"free .* if you send",
    r"verify your wallet",
    r"we will send you",
]

# ---------- ابزارهای گیت‌هاب که پروژه نیستند ----------
GITHUB_TOOL_TERMS = [
    "bot", "sniper", "scraper", "hunter", "automated", "tracker", "checker",
    "scanner", "dashboard", "api client", "cli", "sdk", "indexer", "sweeper",
    "auto", "farm tool", "claimer", "wrapper",
]

# ویدیوهای آموزشی که پروژه نیستند
TUTORIAL_TERMS = [
    "how to", "tutorial", "guide", "step by step", "explained", "review",
    "top 5", "top 10", "best airdrops", "best nft", "update", "news recap",
    "my experience", "tips", "for beginners", "roadmap", "interview",
]

# عنوان‌های سوالی در ردیت
QUESTION_PREFIXES = [
    "is ", "any ", "what ", "how ", "should ", "does ", "why ", "can ",
    "who ", "help", "recommend", "worth it", "scam?", "legit?",
]

# ---------- تشخیص زنجیره ----------
CHAIN_HINTS = {
    "solana": ["solana", "phantom", "magic eden", "jup.ag", "metaplex", "tensor"],
    "ethereum": ["ethereum", "eth ", "erc-20", "erc-721", "opensea", "lido", "uniswap"],
    "arbitrum": ["arbitrum"],
    "base": ["base chain", " on base", "base network", "coinbase wallet"],
    "polygon": ["polygon", "matic"],
    "bsc": ["binance smart chain", "bsc", "bnb chain", "pancakeswap"],
    "bitcoin": ["bitcoin", "ordinals", "inscription", "runes"],
    "ton": ["ton ", "telegram wallet", "toncoin"],
    "aptos": ["aptos"],
    "sui": ["sui "],
}

TLD_GOOD = {"com", "io", "org", "net", "app", "dev", "co", "gg"}
TLD_SUSPICIOUS = {"xyz", "top", "cc", "buzz", "click", "site", "icu", "cyou", "shop"}

GENERIC_DOMAINS = {
    "reddit.com", "youtube.com", "youtu.be", "twitter.com", "x.com", "github.com",
    "medium.com", "t.me", "discord.gg", "telegram.me", "mirror.xyz",
}


def _text(content: str) -> str:
    return (content or "").lower()


def _match_patterns(patterns: list[tuple[str, str]], text: str) -> list[str]:
    t = _text(text)
    return [label for label, pat in patterns if re.search(pat, t)]


def is_crypto_related(text: str) -> bool:
    t = _text(text)
    return any(term in t for term in CRYPTO_TERMS)


def free_terms_found(text: str) -> list[str]:
    return _match_patterns(FREE_PATTERNS, text)


def is_free(text: str) -> bool:
    """رایگان بودن شرط اصلی است: حتماً باید حداقل یک عبارت رایگان/ایردراپ داشته باشد."""
    return bool(free_terms_found(text))


def intent_terms_found(text: str) -> list[str]:
    """آیا متن دعوت به اقدام (claim/mint/whitelist/...) دارد؟ برای فیلتر کردن خبرهای بی‌ربط."""
    return _match_patterns(INTENT_PATTERNS, text)


def has_intent(text: str) -> bool:
    return bool(intent_terms_found(text))


def upcoming_terms_found(text: str) -> list[str]:
    t = _text(text)
    return [term for term in UPCOMING_TERMS if term in t]


def red_flags(text: str) -> list[str]:
    t = _text(text)
    found = []
    for pat in RED_FLAG_PATTERNS:
        if re.search(pat, t):
            found.append(pat)
    return found


def is_tutorial(text: str) -> bool:
    t = _text(text)
    return any(term in t for term in TUTORIAL_TERMS)


def is_question(text: str) -> bool:
    t = _text(text).strip()
    return any(t.startswith(prefix) for prefix in QUESTION_PREFIXES)


def is_github_tool(repo_name: str, description: str) -> bool:
    r = _text(repo_name)
    d = _text(description)
    return any(term in r or term in d for term in GITHUB_TOOL_TERMS)


def detect_chain(text: str) -> list[str]:
    t = _text(text)
    found = []
    for chain, hints in CHAIN_HINTS.items():
        if any(h in t for h in hints):
            found.append(chain)
    return found


def extract_socials(text: str) -> list[str]:
    t = text or ""
    urls = re.findall(r"https?://(?:x\.com|twitter\.com|t\.me|discord\.gg|discord\.com)[^\s\"'<>]+", t)
    return list(dict.fromkeys(urls))


def extract_github(text: str) -> str:
    t = text or ""
    m = re.search(r"https?://github\.com/[\w\-\.]+/[\w\-\.]+", t)
    return m.group(0) if m else ""


def extract_domains(text: str) -> list[str]:
    t = text or ""
    return list(dict.fromkeys(re.findall(r"https?://([\w\-\.]+)", t)))


def extract_domain(url: str) -> str:
    if not url:
        return ""
    m = re.match(r"https?://([\w\-\.]+)", url)
    if not m:
        return ""
    d = m.group(1).lower()
    d = d[4:] if d.startswith("www.") else d
    return d


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u0600-\u06FF]", "", title.lower())[:80]


def project_key(title: str, url: str, domain: str, github_url: str = "") -> str:
    """کلید یکتا برای حذف تکراری‌ها."""
    if github_url:
        return "gh:" + re.sub(r"[^a-z0-9]", "", github_url.lower())
    if domain and domain not in GENERIC_DOMAINS:
        return "web:" + re.sub(r"[^a-z0-9\.\-]", "", domain)
    return "t:" + normalize_title(title)


def tld_penalty(domain: str) -> int:
    if not domain:
        return 0
    tld = domain.rsplit(".", 1)[-1]
    if tld in TLD_GOOD:
        return 5
    if tld in TLD_SUSPICIOUS:
        return -5
    return 0
