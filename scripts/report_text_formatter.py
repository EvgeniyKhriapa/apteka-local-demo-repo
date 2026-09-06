# -*- coding: utf-8 -*-
"""
report_text_formatter.py

Форматування щоденного текстового звіту "Гармонія 2000".
Порядок секцій: Аптеки (АНР) -> Сайт -> Аналітика -> Facebook -> Google Ads
-> Search Console (опційно, тільки повна версія).

Використання: імпортувати build_report(data, report_date, gsc=None) і
передати словник з даними, зібраними daily_report.py з OpenCart / GA4 /
Meta / Google Ads / АНР. Структуру data див. у прикладі внизу файлу
(if __name__ == "__main__").
"""

# Поріг, вище якого падіння/зростання вважається "помітним" і триггерить ⚠️
WARNING_THRESHOLD_PCT = 30

# Короткі назви для довгих назв кампаній Facebook (щоб не ламали рядок)
FB_CAMPAIGN_SHORT_NAMES = {
    "Допис: \"💚 ГАРМОНІЯ ТВОГО ЛІТА: вигравайте iPhone 17,...\"": "iPhone 17 розіграш",
    "Липневі знижки у аптечній мережі «Гармонія 2000»🍀": "Липневі знижки 🍀",
    "Ретаргет — динамічний каталог": "Ретаргет — динам. каталог",
}

# Короткі назви для довгих назв кампаній Google Ads
GOOGLE_ADS_SHORT_NAMES = {
    "Performance Max — Препарати OTC": "PMax — Препарати OTC",
}

CAMPAIGN_NAME_MAX_LEN = 28  # якщо назви немає у словнику - обрізаємо до цієї довжини
PRODUCT_NAME_MAX_LEN = 34   # аналогічно для назв товарів у топ-5
QUERY_NAME_MAX_LEN = 30     # аналогічно для пошукових запитів Search Console


# ------------------------------------------------------------------
# Базові хелпери форматування
# ------------------------------------------------------------------

def fmt_num(value, decimals=0):
    """617676.35 -> '617 676' або '617 676.35' з пробілом як розділювачем тисяч."""
    if value is None:
        return "н/д"
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", " ")


def fmt_currency(value, currency="₴", decimals=0):
    return f"{fmt_num(value, decimals)} {currency}"


def fmt_usd(value, decimals=2):
    return f"${value:,.{decimals}f}"


def delta_arrow(current, previous, period_label="позавчора"):
    """
    Повертає рядок типу '🔺 +50.0%  (14 позавчора)' або '🔻 -47.9%  (499 позавчора)'.
    Якщо previous відсутній або 0 - повертає позначку "н/д" без ділення на нуль.
    period_label: підпис періоду порівняння (за замовчуванням "позавчора" для
    щоденного звіту; передайте, наприклад, "попередній місяць" для місячного).
    """
    if previous is None:
        return "н/д (немає даних за попередній період)"
    if previous == 0:
        return f"н/д ({period_label} було 0)"

    pct = (current - previous) / previous * 100
    if pct > 0.05:
        arrow = "🔺"
        sign = "+"
    elif pct < -0.05:
        arrow = "🔻"
        sign = ""
    else:
        arrow = "➖"
        sign = ""

    return f"{arrow} {sign}{pct:.1f}%  ({fmt_num(previous)} {period_label})"


def is_warning(current, previous, threshold=WARNING_THRESHOLD_PCT):
    """True, якщо зміна перевищує поріг (в будь-який бік)."""
    if not previous:
        return False
    pct = abs((current - previous) / previous * 100)
    return pct >= threshold


def short_campaign_name(name, short_names_map=None, max_len=CAMPAIGN_NAME_MAX_LEN):
    short_names_map = short_names_map or FB_CAMPAIGN_SHORT_NAMES
    if name in short_names_map:
        return short_names_map[name]
    if len(name) <= max_len:
        return name
    return name[: max_len - 1].rstrip() + "…"


def truncate(text, max_len=PRODUCT_NAME_MAX_LEN):
    text = text.strip().rstrip(".")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def divider(char="─", length=18):
    return char * length


def bar(char="━", length=28):
    return char * length


# ------------------------------------------------------------------
# Секції звіту
# ------------------------------------------------------------------

def build_apteky_section(d):
    """
    d = {
        "available": True,
        "date": "2026-07-08",
        "revenue": 617676.35,
        "markup": 110349.80,
        "top5": [
            {"name": "Аптечний пункт №2 — вул. Фастівська, 2", "revenue": 119990.13},
            ...
        ],
    }
    Якщо АНР ще не прислали фід за цю дату: {"available": False, "date": "..."}.
    """
    lines = []
    lines.append("🏪 ПРОДАЖІ ПО АПТЕКАХ (АНР)")
    lines.append(divider())

    if not d.get("available", True):
        lines.append("(даних від АНР за цю дату ще немає)")
        return "\n".join(lines)

    lines.append(f"Виручка по мережі   {fmt_currency(d['revenue'])}")
    lines.append(f"Націнка по мережі   {fmt_currency(d['markup'])}")
    lines.append("")
    lines.append("Топ-5 аптек за виручкою:")
    for i, apt in enumerate(d["top5"], start=1):
        lines.append(f" {i}. {apt['name']:<38} {fmt_currency(apt['revenue']):>12}")
    return "\n".join(lines)


def build_site_section(d, show_top_products=True):
    """
    d = {
        "orders_yesterday": 21,
        "orders_day_before": 14,
        "sales_amount_yesterday": 15463.00,
        "avg_check_7d": 670.41,
        "orders_count_7d": 109,
        "anr_available": True,
        "anr_confirmed_amount": 9839.50,
        "anr_confirmed_count": 20,
        "anr_pickup": 20,
        "anr_delivery": 0,
        "top5": [
            {"name": "ЕРИТРОМІЦИНОВА МАЗЬ 5% 20 г. №1.", "qty": 11, "amount": 1980.00},
            ...
        ],
    }
    """
    lines = []
    lines.append("🛒 САЙТ: ПРОДАЖІ")
    lines.append(divider())
    if not d.get("available", True):
        lines.append("(дані OpenCart тимчасово недоступні)")
        return "\n".join(lines)
    lines.append(
        f"Замовлень вчора      {d['orders_yesterday']:<3} "
        f"{delta_arrow(d['orders_yesterday'], d['orders_day_before'])}"
    )
    lines.append(f"Сума продажів     {fmt_currency(d['sales_amount_yesterday'])}")
    lines.append(
        f"Сер. чек, 7 днів     {fmt_currency(d['avg_check_7d'])}  "
        f"({d['orders_count_7d']} замовлень)"
    )
    lines.append("")
    lines.append("Підтверджено АНР (закриті чеки з сайту):")
    if d.get("anr_available", True) and d.get("anr_confirmed_amount") is not None:
        lines.append(
            f"  {fmt_currency(d['anr_confirmed_amount'])} — {d['anr_confirmed_count']} чеків "
            f"({d['anr_pickup']} самовивіз · {d['anr_delivery']} доставка)"
        )
    else:
        lines.append("  дані ще не надійшли")
    if show_top_products:
        lines.append("")
        lines.append("Топ-5 товарів (7 днів):")
        for i, item in enumerate(d["top5"], start=1):
            name = truncate(item["name"])
            lines.append(
                f" {i}. {name:<{PRODUCT_NAME_MAX_LEN}} {item['qty']:>2} шт · {fmt_currency(item['amount']):>9}"
            )
    return "\n".join(lines)


def build_analytics_section(d):
    """
    d = {"users_yesterday": 260, "users_day_before": 499}
    """
    lines = []
    lines.append("📈 АНАЛІТИКА САЙТУ")
    lines.append(divider())
    if not d.get("available", True):
        lines.append("(дані GA4 тимчасово недоступні)")
        return "\n".join(lines)
    lines.append(
        f"Активні користувачі  {d['users_yesterday']:<3} "
        f"{delta_arrow(d['users_yesterday'], d['users_day_before'])}"
    )
    if is_warning(d["users_yesterday"], d["users_day_before"]):
        lines.append("⚠️ помітна просадка — варто перевірити вручну")
    return "\n".join(lines)


def build_facebook_section(d):
    """
    d = {
        "spend_yesterday": 4.36,
        "impressions_yesterday": 7656,
        "campaigns": [
            {"name": "...", "spend": 1.97, "impressions": 6456},
            ...
        ],
    }
    """
    lines = []
    lines.append("📣 FACEBOOK MARKETING")
    lines.append(divider())
    if not d.get("available", True):
        lines.append("(дані Facebook Ads тимчасово недоступні)")
        return "\n".join(lines)
    lines.append(f"Витрати вчора      {fmt_usd(d['spend_yesterday'])}")
    lines.append(f"Покази вчора        {fmt_num(d['impressions_yesterday'])}")
    lines.append("")
    for c in d["campaigns"]:
        name = short_campaign_name(c["name"], FB_CAMPAIGN_SHORT_NAMES)
        lines.append(
            f" • {name:<{CAMPAIGN_NAME_MAX_LEN}} {fmt_usd(c['spend']):>7} · {fmt_num(c['impressions']):>6} показів"
        )
    return "\n".join(lines)


def build_google_ads_section(d):
    """
    d = {
        "spend_yesterday": 243.47,
        "impressions_yesterday": 2313,
        "campaigns": [
            {"name": "Аптека — Пошук — Чернівці", "spend": 174.45, "impressions": 376},
            ...
        ],
    }
    """
    lines = []
    lines.append("🔎 GOOGLE ADS")
    lines.append(divider())
    if not d.get("available", True):
        lines.append("(дані Google Ads тимчасово недоступні)")
        return "\n".join(lines)
    lines.append(f"Витрати вчора     {fmt_currency(d['spend_yesterday'], decimals=2)}")
    lines.append(f"Покази вчора        {fmt_num(d['impressions_yesterday'])}")
    lines.append("")
    for c in d["campaigns"]:
        name = short_campaign_name(c["name"], GOOGLE_ADS_SHORT_NAMES)
        lines.append(
            f" • {name:<{CAMPAIGN_NAME_MAX_LEN}} {fmt_currency(c['spend'], decimals=2):>10} · {fmt_num(c['impressions']):>6} показів"
        )
    return "\n".join(lines)


def build_pharma_news_section(d, show_links=True):
    """
    d = {
        "date": "2026-07-12",
        "items": [{"title": "...", "link": "..."}, ...],
    }
    """
    lines = []
    lines.append(f"💊 НОВИНИ ФАРМАЦІЇ (apteka.ua, {d['date']})")
    lines.append(divider())
    if d["items"]:
        for i, item in enumerate(d["items"], start=1):
            lines.append(f" {i}. {item['title']}")
            if show_links:
                lines.append(f"    {item['link']}")
    else:
        lines.append("(новин не знайдено)")
    return "\n".join(lines)


def build_search_console_section(d):
    """
    d = {
        "date": "2026-07-07",
        "rows": [
            {"query": "...", "clicks": 3, "impressions": 28, "ctr": 0.1071, "position": 3.0},
            ...
        ],
        "note": "optional — shown when the date fell back from yesterday",
    }
    """
    lines = []
    lines.append(f"🔍 SEARCH CONSOLE: ТОП-10 ЗАПИТІВ ЗА {d['date']}")
    lines.append(divider())
    if d["rows"]:
        for row in d["rows"]:
            query = truncate(row["query"], QUERY_NAME_MAX_LEN)
            lines.append(
                f" • {query:<{QUERY_NAME_MAX_LEN}} {row['clicks']:>3} кл · {row['impressions']:>4} пок · "
                f"CTR {row['ctr'] * 100:.1f}% · поз {row['position']:.1f}"
            )
    else:
        lines.append("(даних немає)")
    if d.get("note"):
        lines.append("")
        lines.append(d["note"])
    return "\n".join(lines)


# ------------------------------------------------------------------
# Збірка повного звіту
# ------------------------------------------------------------------

def build_report(data, report_date, gsc=None, pharma_news=None, compact=False):
    """
    data = {
        "apteky": {...},       # див. build_apteky_section
        "site": {...},         # див. build_site_section
        "analytics": {...},    # див. build_analytics_section
        "facebook": {...},     # див. build_facebook_section
        "google_ads": {...},   # див. build_google_ads_section
    }
    report_date: рядок 'DD.MM.YYYY' для заголовка
    gsc: опційно {...} (див. build_search_console_section) — якщо None,
         секцію Search Console пропускаємо (використовується для компактної
         версії, яка йде в чат Telegram).
    pharma_news: опційно {...} (див. build_pharma_news_section) — на відміну
         від gsc, показуємо в обох версіях, якщо дані передані. Йде
         останньою секцією звіту.
    compact: True для компактної версії (чат Telegram) — ховає топ-5 товарів
         у секції "Сайт" і посилання в секції новин, щоб скоротити повідомлення.
    """
    parts = []
    parts.append(f"📋 ГАРМОНІЯ 2000 — ЗВІТ ЗА {report_date}")
    parts.append(bar())
    parts.append("")
    parts.append(build_apteky_section(data["apteky"]))
    parts.append("")
    parts.append(build_site_section(data["site"], show_top_products=not compact))
    parts.append("")
    parts.append(build_analytics_section(data["analytics"]))
    parts.append("")
    parts.append(build_facebook_section(data["facebook"]))
    parts.append("")
    parts.append(build_google_ads_section(data["google_ads"]))
    if gsc is not None:
        parts.append("")
        parts.append(build_search_console_section(gsc))
    if pharma_news is not None:
        parts.append("")
        parts.append(build_pharma_news_section(pharma_news, show_links=not compact))
    parts.append("")
    parts.append(bar())
    return "\n".join(parts)


# ------------------------------------------------------------------
# Приклад використання на реальних даних із звіту 09.07.2026
# ------------------------------------------------------------------

if __name__ == "__main__":
    sample_data = {
        "apteky": {
            "available": True,
            "date": "2026-07-08",
            "revenue": 617676.35,
            "markup": 110349.80,
            "top5": [
                {"name": "Аптечний пункт №2 — вул. Фастівська, 2", "revenue": 119990.13},
                {"name": "Аптека №4 — пр-т Незалежності, 119", "revenue": 73786.30},
                {"name": "Аптека №1 — вул. Руська, 17", "revenue": 57532.20},
                {"name": "Аптека №13 — вул. Героїв Майдану, 40", "revenue": 41415.66},
                {"name": "Аптечний пункт №3 — м. Кіцмань", "revenue": 40037.16},
            ],
        },
        "site": {
            "orders_yesterday": 21,
            "orders_day_before": 14,
            "sales_amount_yesterday": 15463.00,
            "avg_check_7d": 670.41,
            "orders_count_7d": 109,
            "anr_available": True,
            "anr_confirmed_amount": 9839.50,
            "anr_confirmed_count": 20,
            "anr_pickup": 20,
            "anr_delivery": 0,
            "top5": [
                {"name": "ЕРИТРОМІЦИНОВА МАЗЬ 5% 20 г. №1.", "qty": 11, "amount": 1980.00},
                {"name": "МАЛЮТКА 3 350 г ХОРОЛ", "qty": 7, "amount": 1032.50},
                {"name": "ВАЛІДОЛ-ДАРНИЦЯ табл. 60 мг №10 конт. чар. уп.", "qty": 5, "amount": 117.50},
                {"name": "ЛЕВАНА ІС табл. 2 мг №10 в пачці ІНТЕРХІМ", "qty": 4, "amount": 1400.00},
                {"name": "ГЕНТАМІЦИНОВА МАЗЬ 1% 15 г №1.", "qty": 4, "amount": 440.00},
            ],
        },
        "analytics": {
            "users_yesterday": 260,
            "users_day_before": 499,
        },
        "facebook": {
            "spend_yesterday": 4.36,
            "impressions_yesterday": 7656,
            "campaigns": [
                {
                    "name": "Допис: \"💚 ГАРМОНІЯ ТВОГО ЛІТА: вигравайте iPhone 17,...\"",
                    "spend": 1.97,
                    "impressions": 6456,
                },
                {
                    "name": "Липневі знижки у аптечній мережі «Гармонія 2000»🍀",
                    "spend": 1.28,
                    "impressions": 409,
                },
                {"name": "Ретаргет — динамічний каталог", "spend": 1.11, "impressions": 791},
            ],
        },
        "google_ads": {
            "spend_yesterday": 243.47,
            "impressions_yesterday": 2313,
            "campaigns": [
                {"name": "Аптека — Пошук — Чернівці", "spend": 174.45, "impressions": 376},
                {"name": "Performance Max — Препарати OTC", "spend": 69.02, "impressions": 1937},
            ],
        },
    }

    report_text = build_report(sample_data, report_date="09.07.2026")
    print(report_text)
