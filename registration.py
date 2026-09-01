"""ساخت راهنمای ثبت‌نام قدم‌به‌قدم — دوزبانه (فارسی + کلیدواژه‌های انگلیسی)."""


def _wallet_for_chain(chain: str) -> str:
    return {
        "solana": "Phantom",
        "ethereum": "MetaMask",
        "arbitrum": "MetaMask (شبکه Arbitrum)",
        "base": "MetaMask یا Coinbase Wallet (شبکه Base)",
        "polygon": "MetaMask (شبکه Polygon)",
        "bsc": "MetaMask (شبکه BNB Chain)",
        "bitcoin": "کیف پول بیت‌کوین با پشتیبانی Ordinals",
        "ton": "TON Keeper / کیف پول تلگرام",
        "aptos": "Petra",
        "sui": "Sui Wallet / Ethos",
    }.get(chain, "MetaMask / Phantom (مطابق زنجیرهٔ پروژه)")


def build_steps(chain_hints: list[str], free_terms: list[str]) -> list[str]:
    chain = chain_hints[0] if chain_hints else ""
    wallet = _wallet_for_chain(chain)

    steps: list[str] = []
    steps.append(
        f"وارد وب‌سایت رسمی پروژه شوید (آدرس را خودتان تایپ کنید؛ به لینک‌های داخل کامنت‌ها/پیام‌های خصوصی اعتماد نکنید)."
    )
    steps.append(
        f"کیف پول {wallet} آماده کنید — برای پروژه‌های جدید بهتر است یک کیف پول «جدا» بسازید، نه کیف پولی که دارایی اصلی‌تان در آن است."
    )
    steps.append(
        "در سایت، دکمهٔ Connect Wallet / ثبت‌نام را بزنید و کیف پول را متصل کنید (فقط امضای اتصال؛ هیچ تراکنش پرداختی لازم نیست)."
    )
    steps.append(
        "حساب‌هایتان را تأیید کنید: معمولاً ایمیل + توییتر/X + دیسکورد (Verify) — این مرحله معمولاً رایگان است."
    )
    steps.append(
        "اگر شرط دارد، در دیسکورد/تلگرام پروژه عضو شوید و نقش بگیرید (اغلب شرط eligibility است)."
    )
    steps.append(
        "وقتی مینت/کلایم باز شد (Mint / Claim / Free Claim)، دکمه را بزنید. فقط هزینهٔ گس (Gas) بدهید؛ هر درخواست پرداخت بیشتر = نشانهٔ خطر."
    )
    if chain:
        steps.append(
            f"توکن/ان‌اف‌تی را با آدرس قرارداد رسمی از Etherscan/Solscan یا وب‌سایت رسمی به کیف پول اضافه کنید — آدرس را فقط از منابع رسمی کپی کنید."
        )
    else:
        steps.append(
            "توکن/ان‌اف‌تی را با آدرس قرارداد رسمی به کیف پول اضافه کنید — آدرس را فقط از منابع رسمی کپی کنید."
        )
    steps.append(
        "⚠️ قانون طلایی: هرگز Seed Phrase / عبارت بازیابی را به هیچ سایت یا فردی ندهید. هیچ پروژهٔ واقعی آن را نمی‌خواهد."
    )
    return steps
