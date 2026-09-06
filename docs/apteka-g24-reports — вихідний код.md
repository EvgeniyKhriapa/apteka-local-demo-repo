# apteka-g24-reports — вихідний код (доповнення до технічної документації)

Цей документ доповнює основну технічну документацію повним вихідним кодом усіх Python-скриптів репозиторію, у порядку від дрібних джерел даних до оркестраторів і бота. Перед кожним файлом — коротке пояснення: звідки в ньому беруться змінні, константи та (якщо є) класи.

**Про класи одразу:** у власному коді проєкту немає жодного оголошення `class ...` — уся логіка написана у функціональному стилі: один файл = один namespace функцій плюс кілька модульних констант нагорі. Єдині класи, що фігурують у проєкті, — готові класи сторонніх бібліотек, які лише використовуються (наприклад `google.oauth2.credentials.Credentials`, `telegram.Update`, `telegram.ext.Application`) — вони не написані в цьому репозиторії, а імпортуються.

---

## 1. anr_sales.py — розбір XML-фіду АНР

`scripts/anr_sales.py`

Немає жодного класу — модуль побудований як набір функцій, що працюють з одним
спільним "форматом" словника (dict), який один раз описаний у докстрінгу файлу.

- `SCRIPT_DIR`, `CONNECTORS_DIR` — обчислюються від `__file__`, а не хардкодяться,
  щоб той самий код працював і локально, і на сервері з дзеркальною структурою тек.
- `PROD_SALES_DIR` — абсолютний шлях на бойовому сервері (`/home/fz453955/...`);
  `LOCAL_SAMPLE_SALES_DIR` — шлях до тестових прикладів локально. Яка з двох тек
  реально використовується, вирішує `_sales_dir()` (просто перевіряє, яка з них
  існує — жодної змінної середовища для цього не заведено, "zero deploy-config risk").
- `BRANCH_NAMES` — словник "код складу → людська назва", вручну перенесений зі
  скриншоту адмінки клієнта (це не з БД і не з API — константа в коді).
- `_parse_amount(value)` — конвертує рядок із комою як десятковим роздільником
  (формат самого XML-джерела) у `float`.
- `_parse_file(path)` перетворює один XML-файл (`ET.parse(path).getroot()`,
  теги `<Sale>`/`<Branches><Branch>`) у внутрішній словник; звідти значення
  `site_revenue`, `network_total_sales` тощо обчислюються прямо тут же
  агрегацією списків (`sum(...)`, `sorted(...)`), а не беруться готовими з фіду.
- `get_data`/`get_monthly_data` — публічний контракт, який очікує `daily_report.py`
  і `monthly_report.py`; `render_site_confirmation`/`render_section` — текстовий
  вивід.

```python
#!/usr/bin/env python3
"""Parse the daily ANR sales feed (`dataxml/sales/sales_YYYY-MM-DD.xml`) — real
closed receipts per pharmacy branch, as opposed to OpenCart's "order placed"
data which can't tell whether a self-pickup order was actually collected.

On the production server this reads directly from the OpenCart site's
filesystem (same hosting account, no network hop needed). Locally, where that
path doesn't exist, it falls back to `opencart/sales_samples/` for preview/
testing with sample files.
"""
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent

PROD_SALES_DIR = Path("/home/fz453955/g24.ua/apteka/dataxml/sales")
LOCAL_SAMPLE_SALES_DIR = CONNECTORS_DIR / "opencart" / "sales_samples"

# Branch code (warehouse ID) -> display name, from the client's own warehouse
# admin table. Falls back to "Філія {code}" for any code not listed here (new
# branch opened, or a typo in the feed) rather than failing.
BRANCH_NAMES = {
    "54160": "Аптека №1 — вул. Руська, 17",
    "54007": "Аптека №10 — м. Коломия, пл. Вічевий Майдан, 2",
    "53791": "Аптека №11 — вул. Небесної Сотні, 8",
    "53633": "Аптека №12 — вул. С. Скальда, 31",
    "52323": "Аптека №13 — вул. Героїв Майдану, 40",
    "53706": "Аптека №14 — м. Кіцмань, вул. Незалежності, 20/1",
    "53752": "Аптека №2 — пр-кт Незалежності, 78",
    "53960": "Аптека №3 — смт Глибока, вул. Першотравнева, 2А",
    "53802": "Аптека №4 — пр-кт Незалежності, 119",
    "54227": "Аптека №5 — вул. Головна, 103",
    "53948": "Аптека №6 — вул. Галицький Шлях, 46П",
    "54006": "Аптека №7 — вул. Ентузіастів, 3",
    "54050": "Аптека №8 — вул. Головна, 102",
    "53843": "Аптека №9 — м. Кіцмань, вул. Незалежності, 39",
    "53874": "Аптечний пункт №1 — м. Кіцмань, вул. Незалежності, 1",
    "54049": "Аптечний пункт №2 — вул. Фастівська, 2",
    "53746": "Аптечний пункт №3 — м. Кіцмань, вул. Незалежності, 1",
    "53961": "Аптечний пункт №4 — смт Глибока, вул. Шевченка, 14",
    "53875": "Аптечний пункт №5 — Стрілецький Кут",
    "53962": "Аптечний пункт (АН№3) — Тереблече",
    "51869": "Центральна база",
}


def branch_label(code):
    return BRANCH_NAMES.get(code, f"Філія {code}")


def _sales_dir():
    return PROD_SALES_DIR if PROD_SALES_DIR.is_dir() else LOCAL_SAMPLE_SALES_DIR


def _parse_amount(value):
    if not value:
        return 0.0
    return float(value.replace(",", ".").replace(" ", ""))


def _parse_file(path):
    """Parse one sales_YYYY-MM-DD.xml into the shared per-day shape (minus
    the "available"/"date" wrapper) — used by both get_data() (single day,
    "yesterday" relative to a report date) and get_monthly_data() (a whole
    month's worth of files)."""
    root = ET.parse(path).getroot()

    sales = []
    for sale_el in root.findall("Sale"):
        sales.append({
            "order_id": sale_el.get("OrderId"),
            "branch": sale_el.get("Branch"),
            "delivery_type": sale_el.get("DeliveryType"),
            "payment_method": sale_el.get("PaymentMethod"),
            "total": _parse_amount(sale_el.get("Total")),
            "status": sale_el.get("Status"),
        })

    branches = []
    branches_el = root.find("Branches")
    if branches_el is not None:
        for b in branches_el.findall("Branch"):
            code = b.get("Name")
            branches.append({
                "name": code,
                "label": branch_label(code),
                "total_sales": _parse_amount(b.get("TotalSales")),
                "total_markup": _parse_amount(b.get("TotalMarkup")),
            })
    branches.sort(key=lambda b: b["total_sales"], reverse=True)

    paid = [s for s in sales if s["status"] == "paid"]
    refunded = [s for s in sales if s["status"] == "refunded"]
    site_revenue = sum(s["total"] for s in paid) - sum(s["total"] for s in refunded)

    return {
        "site_receipts_count": len(paid),
        "site_refunds_count": len(refunded),
        "site_pickup_count": sum(1 for s in paid if s["delivery_type"] == "pickup"),
        "site_delivery_count": sum(1 for s in paid if s["delivery_type"] == "delivery"),
        "site_revenue": site_revenue,
        "branches": branches,
        "network_total_sales": sum(b["total_sales"] for b in branches),
        "network_total_markup": sum(b["total_markup"] for b in branches),
    }


def get_data(report_date, sales_dir=None):
    yesterday = report_date - timedelta(days=1)
    sales_dir = sales_dir or _sales_dir()
    path = sales_dir / f"sales_{yesterday.isoformat()}.xml"

    if not path.exists():
        return {"available": False, "date": yesterday}

    return {"available": True, "date": yesterday, **_parse_file(path)}


def get_monthly_data(start_date, end_date, sales_dir=None):
    """Aggregate every daily ANR file in [start_date, end_date] (inclusive).
    Days with a missing file are silently skipped (not every day may have
    been delivered yet) — the caller can compare `days_available` against
    the calendar length of the month to see how complete the picture is."""
    sales_dir = sales_dir or _sales_dir()

    days_available = 0
    branch_totals = {}
    network_total_sales = 0.0
    network_total_markup = 0.0
    site_revenue = 0.0
    site_receipts_count = 0

    d = start_date
    while d <= end_date:
        path = sales_dir / f"sales_{d.isoformat()}.xml"
        if path.exists():
            day_data = _parse_file(path)
            days_available += 1
            network_total_sales += day_data["network_total_sales"]
            network_total_markup += day_data["network_total_markup"]
            site_revenue += day_data["site_revenue"]
            site_receipts_count += day_data["site_receipts_count"]
            for b in day_data["branches"]:
                acc = branch_totals.setdefault(b["name"], {"label": b["label"], "total_sales": 0.0, "total_markup": 0.0})
                acc["total_sales"] += b["total_sales"]
                acc["total_markup"] += b["total_markup"]
        d += timedelta(days=1)

    branches = sorted(branch_totals.values(), key=lambda b: b["total_sales"], reverse=True)

    return {
        "available": days_available > 0,
        "days_available": days_available,
        "days_in_range": (end_date - start_date).days + 1,
        "network_total_sales": network_total_sales,
        "network_total_markup": network_total_markup,
        "site_revenue": site_revenue,
        "site_receipts_count": site_receipts_count,
        "branches": branches,
    }


def _fmt(amount):
    return f"{amount:,.2f}".replace(",", " ")


def render_site_confirmation(data=None, report_date=None):
    """One-line confirmed-revenue figure for the "Сайт: Продажі" block —
    real closed/paid receipts linked to a site OrderId, as opposed to
    OpenCart's own total which includes never-confirmed pending pickups."""
    if data is None:
        data = get_data(report_date)

    if not data["available"]:
        return "Підтверджено АНР: дані за цю дату ще не надійшли"

    return (
        f"Підтверджено продано через сайт (реальні закриті чеки, АНР): "
        f"{_fmt(data['site_revenue'])} грн — {data['site_receipts_count']} чеків "
        f"({data['site_pickup_count']} самовивіз, {data['site_delivery_count']} доставка)"
    )


def render_section(report_date, data=None):
    if data is None:
        data = get_data(report_date)

    lines = ["🏪 РЕАЛЬНІ ПРОДАЖІ ПО АПТЕКАХ (АНР)", ""]

    if not data["available"]:
        lines.append("(даних від АНР за цю дату ще немає)")
        lines.append("")
        return "\n".join(lines)

    lines.append(
        f"Виручка по мережі за {data['date'].isoformat()}: "
        f"{_fmt(data['network_total_sales'])} грн"
    )
    lines.append(f"Націнка по мережі: {_fmt(data['network_total_markup'])} грн")
    if data["site_refunds_count"]:
        lines.append(f"Повернень: {data['site_refunds_count']}")
    lines.append("")

    if data["branches"]:
        lines.append("Топ-5 аптек за виручкою:")
        for b in data["branches"][:5]:
            lines.append(f"- {b['label']} — {_fmt(b['total_sales'])} грн")
        lines.append("")

    return "\n".join(lines)


def main():
    report_date = date.today()
    print(render_section(report_date))


if __name__ == "__main__":
    main()

```

---

## 2. opencart_sales.py — продажі з MySQL OpenCart

`scripts/opencart_sales.py`

Без класів. `VALID_ORDER_FILTER = "order_status_id > 0"` — єдине бізнес-правило
модуля, винесене в константу, щоб не дублювати умову в кожному SQL-запиті.
`ENV_PATH` будується відносно файлу (`opencart/.env`, окремий від `.env`
Google/Meta-модулів — кожне джерело має власний секретний файл).

`connect(env)` створює `pymysql.connect(...)` з даними, зчитаними `read_env`
(словник `KEY=value`, тобто прямо з `.env`-файлу), і одразу виконує
`SET SESSION TRANSACTION READ ONLY` — захист на рівні самого MySQL, а не лише
дисципліни коду. Усі змінні на кшталт `product_id`, `product_name`,
`total_quantity` в `fetch_top_products` — це прямі аліаси колонок SQL-запиту
(`op.name AS product_name` тощo), тобто беруться безпосередньо зі схеми таблиць
`oc_order`/`oc_order_product`, попередньо звірених вручну через `DESCRIBE`.

```python
#!/usr/bin/env python3
"""Read-only sales analytics from the OpenCart database (apteka.g24.ua).

Connects with SET SESSION TRANSACTION READ ONLY, so even an accidental
write statement is rejected by MySQL itself. Only SELECT queries are used.

Tables used (verified via DESCRIBE before writing any query):
  oc_order          - one row per order, total in UAH, order_status_id,
                       date_added, currency_code (always UAH here)
  oc_order_product  - line items per order (product_id, name, quantity)

order_status_id = 0 is OpenCart's placeholder for abandoned/unconfirmed
checkouts (never became a real order) and is excluded everywhere below.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pymysql

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"

VALID_ORDER_FILTER = "order_status_id > 0"


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def connect(env):
    conn = pymysql.connect(
        host=env["DB_HOSTNAME"],
        user=env["DB_USERNAME"],
        password=env["DB_PASSWORD"],
        database=env["DB_DATABASE"],
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn


def fetch_order_count(conn, target_date):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM oc_order "
            f"WHERE DATE(date_added) = %s AND {VALID_ORDER_FILTER}",
            (target_date,),
        )
        return cur.fetchone()["cnt"]


def fetch_total_sales(conn, target_date):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(total), 0) AS sum_total FROM oc_order "
            f"WHERE DATE(date_added) = %s AND {VALID_ORDER_FILTER}",
            (target_date,),
        )
        return float(cur.fetchone()["sum_total"])


def fetch_top_products(conn, since_date, limit=10):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT op.name AS product_name,
                   SUM(op.quantity) AS total_quantity,
                   SUM(op.total) AS total_revenue
            FROM oc_order_product op
            JOIN oc_order o ON o.order_id = op.order_id
            WHERE DATE(o.date_added) >= %s AND o.{VALID_ORDER_FILTER}
            GROUP BY op.product_id, op.name
            ORDER BY total_quantity DESC
            LIMIT %s
            """,
            (since_date, limit),
        )
        return cur.fetchall()


def fetch_order_count_range(conn, start_date, end_date):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM oc_order "
            f"WHERE DATE(date_added) BETWEEN %s AND %s AND {VALID_ORDER_FILTER}",
            (start_date, end_date),
        )
        return cur.fetchone()["cnt"]


def fetch_total_sales_range(conn, start_date, end_date):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(SUM(total), 0) AS sum_total FROM oc_order "
            f"WHERE DATE(date_added) BETWEEN %s AND %s AND {VALID_ORDER_FILTER}",
            (start_date, end_date),
        )
        return float(cur.fetchone()["sum_total"])


def fetch_top_products_range(conn, start_date, end_date, limit=10):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT op.name AS product_name,
                   SUM(op.quantity) AS total_quantity,
                   SUM(op.total) AS total_revenue
            FROM oc_order_product op
            JOIN oc_order o ON o.order_id = op.order_id
            WHERE DATE(o.date_added) BETWEEN %s AND %s AND o.{VALID_ORDER_FILTER}
            GROUP BY op.product_id, op.name
            ORDER BY total_quantity DESC
            LIMIT %s
            """,
            (start_date, end_date, limit),
        )
        return cur.fetchall()


def fetch_average_check(conn, since_date):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT AVG(total) AS avg_total, COUNT(*) AS cnt FROM oc_order "
            f"WHERE DATE(date_added) >= %s AND {VALID_ORDER_FILTER}",
            (since_date,),
        )
        row = cur.fetchone()
        avg_total = float(row["avg_total"]) if row["avg_total"] is not None else 0.0
        return avg_total, row["cnt"]


def pct_change_emoji(old, new):
    """Same thresholds as daily_report.pct_change_value: 🔺 growth >=5%,
    🔻 decline <=-5%, ▪️ everything in between / no data."""
    if old == 0:
        if new == 0:
            return "▪️н/д"
        return "🔺+∞%"
    change = (new - old) / old * 100
    sign = "+" if change >= 0 else ""
    text = f"{sign}{change:.1f}%"
    if change >= 5:
        return f"🔺{text}"
    if change <= -5:
        return f"🔻{text}"
    return f"▪️{text}"


def get_data(report_date):
    """Fetch all sales figures as plain data (used by both markdown and HTML renderers)."""
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        yesterday = report_date - timedelta(days=1)
        day_before = report_date - timedelta(days=2)
        week_ago = report_date - timedelta(days=7)

        orders_yesterday = fetch_order_count(conn, yesterday)
        orders_day_before = fetch_order_count(conn, day_before)
        sales_yesterday = fetch_total_sales(conn, yesterday)
        top_products = fetch_top_products(conn, week_ago, limit=10)
        avg_check, orders_7d = fetch_average_check(conn, week_ago)
    finally:
        conn.close()

    return {
        "yesterday": yesterday,
        "day_before": day_before,
        "orders_yesterday": orders_yesterday,
        "orders_day_before": orders_day_before,
        "sales_yesterday": sales_yesterday,
        "top_products": [
            {
                "name": row["product_name"],
                "quantity": int(row["total_quantity"]),
                "revenue": float(row["total_revenue"]),
            }
            for row in top_products
        ],
        "avg_check": avg_check,
        "orders_7d": orders_7d,
    }


def render_section(report_date, data=None):
    if data is None:
        data = get_data(report_date)

    orders_change = pct_change_emoji(data["orders_day_before"], data["orders_yesterday"])

    lines = []
    lines.append("🛒 САЙТ: ПРОДАЖІ")
    lines.append("")
    lines.append(
        f"Замовлень: {data['orders_yesterday']} (вчора) vs "
        f"{data['orders_day_before']} (позавчора) {orders_change}"
    )
    lines.append(f"Сума продажів вчора: {data['sales_yesterday']:,.2f} грн".replace(",", " "))
    lines.append(
        f"Середній чек за останні 7 днів ({data['orders_7d']} замовлень): "
        f"{data['avg_check']:,.2f} грн".replace(",", " ")
    )
    lines.append("")

    lines.append("Топ-5 товарів за кількістю продажів (останні 7 днів):")
    top5 = data["top_products"][:5]
    if top5:
        for i, p in enumerate(top5, start=1):
            revenue = f"{p['revenue']:,.2f}".replace(",", " ")
            # non-breaking spaces around qty/revenue so numbers never split mid-line
            lines.append(f"{i}. {p['name']} — {p['quantity']} шт, {revenue} грн")
    else:
        lines.append("(даних немає)")
    lines.append("")

    return "\n".join(lines)


def main():
    report_date = date.today()
    print(render_section(report_date))


if __name__ == "__main__":
    main()

```

---

## 3. google_ads.py — Google Ads через сирий REST

`scripts/google_ads.py`

Без класів, без офіційного `google-ads` SDK. `API_VERSION` — версія REST API,
підправлена в коментарі-коміті (`rk (2026-08-07): Google заблокував v21...`) —
тобто значення підбиралось емпірично після реальної помилки Google, а не
вибиралось наперед. `CLIENT_CUSTOMER_ID = "5559398809"` — хардкод, бо в акаунті
всього один реальний клієнтський обліковий запис під MCC.

`get_access_token(env)` обмінює `refresh_token` (з `.env`) на короткоживучий
`access_token` напряму через `requests.post` до `oauth2.googleapis.com/token` —
без бібліотеки `google-auth`, вручну. `_search(env, access_token, query)` —
єдина точка виклику Google Ads API: `query` — це рядок GAQL, який кожна
функція-споживач (`fetch_account_summary`, `fetch_campaign_breakdown`) формує
сама через f-string з датою. Значення `spend`/`impressions` дістаються з
відповіді як `int(metrics.get("costMicros", 0)) / 1_000_000` — тобто Google
Ads API повертає гроші в мікро-одиницях, і ділення на мільйон — це переклад
у звичайну валюту, зроблений тут-таки в коді.

```python
#!/usr/bin/env python3
"""Read-only Google Ads stats via the Google Ads API (REST search endpoint),
using the developer token approved for Basic Access.

MCC: "Гармонія 2000" (3933012815) — login-customer-id / manager account.
Client account with real campaigns: 5559398809 (linked under the MCC),
currency UAH.

Uses an explicit segments.date = 'YYYY-MM-DD' filter rather than
"DURING YESTERDAY" — the latter resolves against the Google Ads account's
own timezone and disagreed with our own yesterday/day_before by up to a
full day when tested.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "google-ads" / ".env"

# rk (2026-08-07): Google заблокував v21 ("Version v21 is deprecated. Requests
# to this version will be blocked") — щоденний звіт падав на блоці Google Ads.
# Перевірено того ж дня: v22, v23, v24 віддають 200. Взято v23 як середню.
API_VERSION = "v23"
CLIENT_CUSTOMER_ID = "5559398809"


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def get_access_token(env):
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": env["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": env["GOOGLE_OAUTH_CLIENT_SECRET"],
            "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _search(env, access_token, query):
    login_customer_id = env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "login-customer-id": login_customer_id,
        "Content-Type": "application/json",
    }
    url = (
        f"https://googleads.googleapis.com/{API_VERSION}/customers/"
        f"{CLIENT_CUSTOMER_ID}/googleAds:search"
    )
    resp = requests.post(url, headers=headers, json={"query": query}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def fetch_account_summary(env, access_token, target_date):
    iso = target_date.isoformat()
    query = (
        "SELECT metrics.cost_micros, metrics.impressions FROM customer "
        f"WHERE segments.date = '{iso}'"
    )
    results = _search(env, access_token, query)
    if not results:
        return {"spend": 0.0, "impressions": 0}
    metrics = results[0]["metrics"]
    return {
        "spend": int(metrics.get("costMicros", 0)) / 1_000_000,
        "impressions": int(metrics.get("impressions", 0)),
    }


def fetch_campaign_breakdown(env, access_token, target_date):
    iso = target_date.isoformat()
    query = (
        "SELECT campaign.name, metrics.cost_micros, metrics.impressions FROM campaign "
        f"WHERE segments.date = '{iso}' AND metrics.cost_micros > 0"
    )
    results = _search(env, access_token, query)
    campaigns = []
    for r in results:
        metrics = r["metrics"]
        campaigns.append({
            "name": r["campaign"]["name"],
            "spend": int(metrics.get("costMicros", 0)) / 1_000_000,
            "impressions": int(metrics.get("impressions", 0)),
        })
    campaigns.sort(key=lambda c: c["spend"], reverse=True)
    return campaigns


def get_monthly_data(start_date, end_date):
    env = read_env(ENV_PATH)
    access_token = get_access_token(env)

    since, until = start_date.isoformat(), end_date.isoformat()

    summary_query = (
        "SELECT metrics.cost_micros, metrics.impressions FROM customer "
        f"WHERE segments.date BETWEEN '{since}' AND '{until}'"
    )
    summary_results = _search(env, access_token, summary_query)
    spend_total = sum(int(r["metrics"].get("costMicros", 0)) for r in summary_results) / 1_000_000
    impressions_total = sum(int(r["metrics"].get("impressions", 0)) for r in summary_results)

    campaign_query = (
        "SELECT campaign.name, metrics.cost_micros, metrics.impressions FROM campaign "
        f"WHERE segments.date BETWEEN '{since}' AND '{until}'"
    )
    campaign_results = _search(env, access_token, campaign_query)
    campaign_totals = {}
    for r in campaign_results:
        name = r["campaign"]["name"]
        metrics = r["metrics"]
        acc = campaign_totals.setdefault(name, {"name": name, "spend": 0.0, "impressions": 0})
        acc["spend"] += int(metrics.get("costMicros", 0)) / 1_000_000
        acc["impressions"] += int(metrics.get("impressions", 0))
    campaigns = sorted(
        (c for c in campaign_totals.values() if c["spend"] > 0),
        key=lambda c: c["spend"], reverse=True,
    )

    return {
        "spend_total": spend_total,
        "impressions_total": impressions_total,
        "campaigns": campaigns,
    }


def get_data(report_date):
    env = read_env(ENV_PATH)
    access_token = get_access_token(env)

    yesterday = report_date - timedelta(days=1)
    summary = fetch_account_summary(env, access_token, yesterday)
    campaigns = fetch_campaign_breakdown(env, access_token, yesterday)

    return {
        "yesterday": yesterday,
        "spend_yesterday": summary["spend"],
        "impressions_yesterday": summary["impressions"],
        "campaigns": campaigns,
    }


def render_section(report_date, data=None):
    if data is None:
        data = get_data(report_date)

    lines = []
    lines.append("🔎 GOOGLE ADS")
    lines.append("")
    lines.append(f"Витрати вчора: {data['spend_yesterday']:.2f} грн")
    lines.append(f"Покази вчора: {data['impressions_yesterday']}")
    lines.append("")

    if data["campaigns"]:
        lines.append("Активні кампанії (вчора):")
        for c in data["campaigns"]:
            lines.append(f"- {c['name']} — {c['spend']:.2f} грн, {c['impressions']} показів")
    else:
        lines.append("Вчора жодна кампанія не мала витрат.")
    lines.append("")

    return "\n".join(lines)


def main():
    report_date = date.today()
    print(render_section(report_date))


if __name__ == "__main__":
    main()

```

---

## 4. meta_ads.py — Facebook/Meta Ads Graph API

`scripts/meta_ads.py`

Без класів. `GRAPH_API_VERSION = "v21.0"`, `ACCOUNT_FIELDS`/`CAMPAIGN_FIELDS`
— рядки полів, які Graph API Insights приймає як параметр `fields` (беруться
з документації Facebook Marketing API, не з відповіді). Список тестових
кампаній для виключення з підсумків — константа в коді (ID кампаній, вручну
визначені як "не реальна реклама").

`_insights_request`/`_insights_request_range` — низькорівнева обгортка над
`requests.get(...)` до `/act_<id>/insights`; `token`/`account_id` приходять з
`.env` (`meta-ads/.env`). `_fetch_campaign_rows` розкладає відповідь Graph API
(список словників з ключами `campaign_id`, `campaign_name`, `spend`,
`impressions` — прямо з полів запиту) на Python-структуру; `_excluded_totals`/
`_display_campaigns` фільтрують тестові кампанії з константи вище.

```python
#!/usr/bin/env python3
"""Read-only Facebook Marketing (Meta Ads) stats via the Graph API Insights
endpoint, using a permanent System User access token (ads_read only).

Account: "Pavlo Kaspruk" (act_765189840172487) — personal ad account under
Business Manager "Kaspruk Pavel", runs the apteka.g24.ua campaigns.

Reports yesterday's total spend/impressions plus a per-campaign breakdown
(spend + impressions) for campaigns that had spend yesterday ("active").
"""
import re
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "meta-ads" / ".env"

GRAPH_API_VERSION = "v21.0"
ACCOUNT_FIELDS = "spend,impressions"
CAMPAIGN_FIELDS = "campaign_id,campaign_name,spend,impressions"

# Test campaigns to hide from reports — not real marketing spend, just noise.
# "Таргет" (id 52530220277262): flagged by the user 2026-07-20 as a test
# campaign that shouldn't appear in the daily/monthly breakdown.
EXCLUDED_CAMPAIGN_IDS = {"52530220277262"}


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def _insights_request_range(token, account_id, since, until, fields, level=None, time_increment=None):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/insights"
    params = {
        "access_token": token,
        "time_range": f'{{"since":"{since.isoformat()}","until":"{until.isoformat()}"}}',
        "fields": fields,
    }
    if level:
        params["level"] = level
    if time_increment:
        params["time_increment"] = time_increment
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


def _insights_request(token, account_id, target_date, fields, level=None):
    return _insights_request_range(token, account_id, target_date, target_date, fields, level=level)


def _fetch_campaign_rows(token, account_id, since, until):
    """Raw per-campaign rows, unfiltered — every campaign the account has,
    whether or not it had spend."""
    rows = _insights_request_range(
        token, account_id, since, until, CAMPAIGN_FIELDS, level="campaign"
    )
    return [
        {
            "id": row.get("campaign_id"),
            "name": row.get("campaign_name", "?"),
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
        }
        for row in rows
    ]


def _excluded_totals(campaign_rows):
    excluded = [r for r in campaign_rows if r["id"] in EXCLUDED_CAMPAIGN_IDS]
    return sum(r["spend"] for r in excluded), sum(r["impressions"] for r in excluded)


def _display_campaigns(campaign_rows):
    campaigns = [
        {"name": r["name"], "spend": r["spend"], "impressions": r["impressions"]}
        for r in campaign_rows
        if r["id"] not in EXCLUDED_CAMPAIGN_IDS and r["spend"] > 0
    ]
    campaigns.sort(key=lambda c: c["spend"], reverse=True)
    return campaigns


def fetch_account_summary(token, account_id, target_date):
    rows = _insights_request(token, account_id, target_date, ACCOUNT_FIELDS)
    if not rows:
        return {"spend": 0.0, "impressions": 0}
    row = rows[0]
    return {
        "spend": float(row.get("spend", 0)),
        "impressions": int(row.get("impressions", 0)),
    }


def get_monthly_data(start_date, end_date):
    env = read_env(ENV_PATH)
    token = env["META_ACCESS_TOKEN"]
    account_id = env["META_AD_ACCOUNT_ID"]

    rows = _insights_request_range(token, account_id, start_date, end_date, ACCOUNT_FIELDS)
    raw_spend = float(rows[0].get("spend", 0)) if rows else 0.0
    raw_impressions = int(rows[0].get("impressions", 0)) if rows else 0

    campaign_rows = _fetch_campaign_rows(token, account_id, start_date, end_date)
    excluded_spend, excluded_impressions = _excluded_totals(campaign_rows)

    return {
        "spend_total": raw_spend - excluded_spend,
        "impressions_total": raw_impressions - excluded_impressions,
        "campaigns": _display_campaigns(campaign_rows),
    }


def get_data(report_date):
    env = read_env(ENV_PATH)
    token = env["META_ACCESS_TOKEN"]
    account_id = env["META_AD_ACCOUNT_ID"]

    yesterday = report_date - timedelta(days=1)
    summary = fetch_account_summary(token, account_id, yesterday)
    campaign_rows = _fetch_campaign_rows(token, account_id, yesterday, yesterday)
    excluded_spend, excluded_impressions = _excluded_totals(campaign_rows)

    return {
        "yesterday": yesterday,
        "spend_yesterday": summary["spend"] - excluded_spend,
        "impressions_yesterday": summary["impressions"] - excluded_impressions,
        "campaigns": _display_campaigns(campaign_rows),
    }


def render_section(report_date, data=None):
    if data is None:
        data = get_data(report_date)

    lines = []
    lines.append("📣 FACEBOOK MARKETING")
    lines.append("")
    lines.append(f"Витрати вчора: {data['spend_yesterday']:.2f} USD")
    lines.append(f"Покази вчора: {data['impressions_yesterday']}")
    lines.append("")

    if data["campaigns"]:
        lines.append("Активні кампанії (вчора):")
        for c in data["campaigns"]:
            lines.append(f"- {c['name']} — {c['spend']:.2f} USD, {c['impressions']} показів")
    else:
        lines.append("Вчора жодна кампанія не мала витрат.")
    lines.append("")

    return "\n".join(lines)


def main():
    report_date = date.today()
    print(render_section(report_date))


if __name__ == "__main__":
    main()

```

---

## 5. pharma_news.py — RSS-новини apteka.ua

`scripts/pharma_news.py`

Найкоротший і найпростіший модуль, без класів. `RSS_URL`, `TOP_N=3` —
константи; `ADMIN_NOTICE_RE` — регулярка, що відсікає адміністративні записи
("Розпорядження від...") від фіду — підібрана вручну під конкретний формат
джерела. `get_data` тягне RSS через `requests.get(RSS_URL)`, парсить
`xml.etree.ElementTree`, і для кожного `<item>` бере `title`/`link`/`pubDate`
прямо з тегів фіду; `pubDate` конвертується `email.utils.parsedate_to_datetime`
(стандартний RFC-2822 формат дат в RSS) у `datetime`, з якого потім береться
`.date()` для порівняння з `report_date`.

```python
#!/usr/bin/env python3
"""Top pharmacy-industry news for the report, sourced from apteka.ua's public
RSS feed and filtered to the previous calendar day (same "вчора" convention
as the rest of the report).
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

import requests

RSS_URL = "https://www.apteka.ua/rss"
TOP_N = 3

# apteka.ua's RSS mixes real articles with bare administrative-document
# postings ("Розпорядження від 10.07.2026 р. № 328-...", "Лист від ...") that
# have no real headline — filter those out so only actual news remains.
ADMIN_NOTICE_RE = re.compile(r"^(Розпорядження|Лист|Наказ|Постанова)\s+від\s+\d")


def get_data(report_date, limit=TOP_N, max_lookback_days=5):
    """apteka.ua doesn't publish on weekends, so if "yesterday" has nothing
    (e.g. a Monday report looking for Sunday's news), walk backwards to the
    most recent date that does — same fallback pattern as Search Console.
    """
    yesterday = report_date - timedelta(days=1)

    resp = requests.get(RSS_URL, timeout=15)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    all_items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate") or ""
        try:
            pub_dt = parsedate_to_datetime(pub_date_raw)
        except (TypeError, ValueError):
            continue
        if ADMIN_NOTICE_RE.match(title):
            continue
        all_items.append({"title": title, "link": link, "date": pub_dt})

    for offset in range(max_lookback_days + 1):
        d = yesterday - timedelta(days=offset)
        day_items = sorted(
            (i for i in all_items if i["date"].date() == d),
            key=lambda i: i["date"], reverse=True,
        )
        if day_items:
            return {"date": d, "items": day_items[:limit]}

    return {"date": yesterday, "items": []}


def render_section(report_date, data=None):
    if data is None:
        data = get_data(report_date)

    lines = [f"💊 НОВИНИ ФАРМАЦІЇ (apteka.ua, {data['date'].isoformat()})", ""]
    if data["items"]:
        for i, item in enumerate(data["items"], start=1):
            lines.append(f"{i}. {item['title']}")
            lines.append(f"   {item['link']}")
    else:
        lines.append("(новин не знайдено)")
    lines.append("")
    return "\n".join(lines)


def main():
    print(render_section(date.today()))


if __name__ == "__main__":
    main()

```

---

## 6. product_categories.py — категорії товарів

`scripts/product_categories.py`

Без класів. `fetch_mid_tier_category_map(conn)` читає таблиці категорій
OpenCart (`oc_category`/`oc_category_description` — точні назви видно в самому
SQL нижче) і будує в пам'яті словник `product_id → назва середньої категорії`.
`reaches_root(category_id)` — вкладена функція (замикання на `conn`/кеш
категорій), що рекурсивно піднімається по `parent_id`, доки не досягне кореня
(`parent_id=0|1`) — це і є критерій "середнього рівня" дерева. `get_category_map()`
кешує результат у модульному рівні (просте `functools.lru_cache`-подібне
глобальне значення), щоб не перечитувати БД повторно з інших модулів
(`seasonality.py`, `stock_history_status.py`), які його імпортують.

```python
#!/usr/bin/env python3
"""Категорії товарів — для розбивки звітів (дефектура/мертвий вантаж) по
терапевтичних групах ("Для серця та судин", "Вітаміни та мінерали" тощо),
а не тільки плоским списком.

Категорії в OpenCart уже призначені (не треба чекати ні на 1С, ні на АНР)
— 670 категорій, дерево 2-3 рівні: корінь (parent_id=0, напр. "Лікарські
засоби", "Косметика", "Вироби медичного призначення") → середній рівень
(терапевтична група, саме він нам треба) → іноді ще підгрупа. Середньо
~2.8 категорій на товар (весь ланцюжок предків).

Беремо СЕРЕДНІЙ рівень: категорія, чий parent_id сам є коренем
(parent_id=0). Якщо товар має кілька таких (рідко) — перша знайдена.
Якщо жодної (товар лише в корені, без середнього рівня) — назва кореня.
"""
from pathlib import Path

from opencart_sales import connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"


def fetch_mid_tier_category_map(conn):
    """Повертає {product_id: category_name} — по одній "середній"
    категорії на товар, для групування звітів."""
    with conn.cursor() as cur:
        cur.execute("SELECT category_id FROM oc_category WHERE parent_id = 0")
        root_ids = {r["category_id"] for r in cur.fetchall()}

        cur.execute("""
            SELECT p2c.product_id, c.category_id, c.parent_id, cd.name
            FROM oc_product_to_category p2c
            JOIN oc_category c ON c.category_id = p2c.category_id
            JOIN oc_category_description cd
                ON cd.category_id = c.category_id AND cd.language_id = 3
        """)
        rows = cur.fetchall()

    root_names = {}
    mid_by_product = {}
    for row in rows:
        pid = row["product_id"]
        if row["category_id"] in root_ids:
            root_names.setdefault(pid, row["name"])
            continue
        if row["parent_id"] in root_ids and pid not in mid_by_product:
            mid_by_product[pid] = row["name"]

    result = dict(mid_by_product)
    for pid, name in root_names.items():
        result.setdefault(pid, name)
    return result


def get_category_map():
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        return fetch_mid_tier_category_map(conn)
    finally:
        conn.close()


MEDICAL_SUPPLIES_ROOT_NAME = "Вироби медичного призначення"


def fetch_medical_supplies_product_ids(conn):
    """Товари під коренем 'Вироби медичного призначення' (шприци, маски,
    рукавички, бахіли, серветки тощо) — витратники, не лікарські засоби.
    В мертвому вантажі вони систематично хибно потрапляють у неліквід, бо
    роздаються/використовуються під час обслуговування, а не продаються
    класичним чеком (правило користувача 2026-08-11)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.category_id FROM oc_category c
            JOIN oc_category_description cd
                ON cd.category_id = c.category_id AND cd.language_id = 3
            WHERE c.parent_id = 0 AND cd.name = %s
        """, (MEDICAL_SUPPLIES_ROOT_NAME,))
        root_row = cur.fetchone()
        if not root_row:
            return set()
        root_id = root_row["category_id"]

        cur.execute("SELECT category_id, parent_id FROM oc_category")
        parent_by_cat = {r["category_id"]: r["parent_id"] for r in cur.fetchall()}

        cur.execute("SELECT product_id, category_id FROM oc_product_to_category")
        assignments = cur.fetchall()

    def reaches_root(category_id):
        cid = category_id
        seen = set()
        while cid is not None and cid not in seen:
            if cid == root_id:
                return True
            seen.add(cid)
            cid = parent_by_cat.get(cid)
        return False

    return {row["product_id"] for row in assignments if reaches_root(row["category_id"])}


if __name__ == "__main__":
    cat_map = get_category_map()
    print(f"Категорій зіставлено для {len(cat_map)} товарів")
    from collections import Counter
    top = Counter(cat_map.values()).most_common(15)
    for name, cnt in top:
        print(f"  {name}: {cnt} товарів")

```

---

## 7. sales_1c.py — разовий знімок продажів з 1С

`scripts/sales_1c.py`

Без класів. `XLSX_PATH` — шлях до файлу, який користувач вручну кладе на
сервер після вигрузки з 1С. `norm_product_name`/`norm_filial_name` — текстова
нормалізація (прибрати зайві пробіли/регістр) над сирими рядками з `.xlsx`,
щоб зіставити їх із назвами в `oc_product`/`oc_warehouses_description`.
`parse_1c_export` читає файл через `openpyxl.load_workbook(..., data_only=True)`
і рядок за рядком (`ws.iter_rows`) агрегує кількість/суму по товару+філії — самі
назви колонок і їхній порядок задані форматом конкретного звіту 1С ("Товар",
"Філія", "Кількість витрат"), зафіксованим у докстрінгу. `archive_current_snapshot()`
переносить попередній файл в архівну підпапку перед тим, як новий перезапише
його — це і є "разовість": на диску завжди лише один активний знімок.

```python
#!/usr/bin/env python3
"""Реальні продажі по кожній аптеці й товару окремо — з ручного експорту 1С
("Рух товару", вигружається користувачем через RDP, кладеться на сервер
скопом при оновленні).

Це замінює попередній мережевий проксі (oc_order-based) — той, на відміну
від цього, ловив ЛИШЕ сайтові замовлення (мала частка реальних продажів,
основна маса — живі відвідувачі, яких сайт не бачить). Формат 1С:
колонка "Товар" (назва, без артикулу) x "Філія" (назва аптеки) x
"Кількість витрат" (продано за період). Період і дата вигрузки — в
шапці файлу.

Зіставлення з нашою базою: 99%+ товарів і аптек співпадають після
нормалізації тексту (перевірено вручну на реальному файлі 2026-08-10,
65703 рядки, 12534 унікальних товари, 21 філія). Товар зіставляється за
НАЗВОЮ (в 1С немає артикулу в цьому звіті) — ризик хибного зіставлення
малий, але не нульовий; незіставлені рядки просто відкидаються, не
намагаємось вгадувати.
"""
import re
from datetime import datetime
from pathlib import Path

import openpyxl

from opencart_sales import connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"

# Куди користувач/я кладе останній експорт з 1С. Оновлюється вручну (scp),
# коли з'являється новий файл — немає автоматичного зв'язку з 1С.
XLSX_PATH = CONNECTORS_DIR / "opencart" / "sales_1c.xlsx"

# Попередній знімок — ПЕРЕД заливкою нового sales_1c.xlsx старий файл
# спершу копіюється сюди (archive_current_snapshot()), щоб можна було
# порахувати РЕАЛЬНУ свіжу швидкість продажу (дельта між двома знімками),
# а не грубе середнє за весь період з початку року (див.
# project-apteka-g24-defectura, застереження користувача 2026-08-10).
PREVIOUS_XLSX_PATH = CONNECTORS_DIR / "opencart" / "sales_1c_previous.xlsx"

# Відомі назви аптек з боку сайту (oc_warehouses_description.title) —
# довші рядки перевіряються першими, щоб "АПункт_№1 А№3" не хибно
# зматчився частиною "АПункт №1 А№1" через спільний префікс "АПункт".
_KNOWN_TITLES_CACHE = None


def norm_product_name(s):
    """1С часто вставляє порожній плейсхолдер '{}' всередину назви (десь
    там мав бути додатковий атрибут, не заповнений) — на сайті замість
    нього просто пробіл. Прибираємо, звужуємо пробіли."""
    s = str(s).replace("{}", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_filial_name(s):
    """'_Аптека№10 ...' -> 'Аптека №10 ...' (прибрати провідні '_', додати
    пробіл між 'Аптека' і номером, де його нема); 'Центральна база' (укр,
    1С) -> 'Центральная база' (рос, так записано на сайті)."""
    s = str(s).lstrip("_").strip()
    s = s.replace("Центральна база", "Центральная база")
    s = re.sub(r"Аптека№(\d)", r"Аптека №\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_filial(fname, titles_sorted_desc):
    for title in titles_sorted_desc:
        if fname == title or fname.startswith(title + " ") or fname.startswith(title + ","):
            return title
    return None


def parse_1c_export(xlsx_path=XLSX_PATH):
    """Парсить xlsx-вигрузку "Рух товару" з 1С. Повертає список
    {tovar_norm, filial_norm, vytraty} — БЕЗ зіставлення з БД (це окремий
    крок, потребує з'єднання)."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["TDSheet"]

    period_start = re.sub(r"^[^:]+:\s*", "", str(ws["C4"].value or ""))
    period_end = re.sub(r"^[^:]+:\s*", "", str(ws["C5"].value or ""))

    rows = []
    for row in ws.iter_rows(min_row=10, values_only=True):
        filial, tovar, vytraty = row[0], row[3], row[7]
        if tovar is None or filial in (None, "Итого", "Філія"):
            continue
        try:
            qty = float(vytraty) if vytraty is not None else 0.0
        except (TypeError, ValueError):
            qty = 0.0
        rows.append({
            "filial_raw": filial,
            "tovar_norm": norm_product_name(tovar),
            "filial_norm": norm_filial_name(filial),
            "vytraty": qty,
        })

    return rows, {"period_start": period_start, "period_end": period_end}


_CACHE = {}  # xlsx_path (str) -> (sold_all_min0, meta) — раз на процес


def load_sold_qty_by_pharmacy(xlsx_path=XLSX_PATH, min_sold=0):
    """Головна точка входу. Повертає:
    {(product_id, warehouse_id): sold_qty за весь період файлу}
    плюс metadata (period_start/end, matched_rows, total_rows).

    Немає файлу на диску (ще не залито) -> повертає ({}, None) — виклик
    відповідає за fallback на старий проксі.

    Парсинг+зіставлення (найдорожча частина — 65k+ рядків xlsx і 2 SQL-
    запити) кешується на рівні процесу: перший виклик рахує все й кладе
    в _CACHE, усі наступні (навіть з іншим min_sold) просто фільтрують
    уже готовий словник. Без цього кожен модуль (defectura/redistribution/
    low_stock_alert), викликаний в одному скрипті (напр.
    stock_history_status.py), парсив файл заново — 6-7 разів за один
    запуск, і на сервері з обмеженою пам'яттю (CloudLinux LVE) це вбивало
    процес (exit 137), знайдено й виправлено 2026-08-10.
    """
    cache_key = str(xlsx_path)
    if cache_key not in _CACHE:
        _CACHE[cache_key] = _load_and_match(xlsx_path)

    sold_all, meta = _CACHE[cache_key]
    if meta is None:
        return {}, None
    if min_sold:
        sold = {k: v for k, v in sold_all.items() if v >= min_sold}
    else:
        sold = dict(sold_all)
    return sold, meta


def _load_and_match(xlsx_path):
    if not Path(xlsx_path).exists():
        return {}, None

    rows, period = parse_1c_export(xlsx_path)

    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.product_id, pd.name FROM oc_product p "
                "JOIN oc_product_description pd "
                "ON pd.product_id = p.product_id AND pd.language_id = 3"
            )
            name_to_pid = {norm_product_name(r["name"]): r["product_id"] for r in cur.fetchall()}

            cur.execute("SELECT warehouses_id, title FROM oc_warehouses_description")
            wh_rows = cur.fetchall()
            title_to_wid = {r["title"]: r["warehouses_id"] for r in wh_rows}
    finally:
        conn.close()

    titles_sorted_desc = sorted(title_to_wid, key=len, reverse=True)

    sold = {}
    matched = 0
    for row in rows:
        pid = name_to_pid.get(row["tovar_norm"])
        if pid is None:
            continue
        matched_title = _match_filial(row["filial_norm"], titles_sorted_desc)
        if matched_title is None:
            continue
        wid = title_to_wid[matched_title]
        matched += 1
        key = (pid, wid)
        sold[key] = sold.get(key, 0.0) + row["vytraty"]

    meta = {
        "period_start": period["period_start"],
        "period_end": period["period_end"],
        "matched_rows": matched,
        "total_rows": len(rows),
        "file_mtime": Path(xlsx_path).stat().st_mtime,
    }
    return sold, meta


def archive_current_snapshot():
    """Викликати ПЕРЕД тим, як залити НОВИЙ sales_1c.xlsx на сервер —
    копіює поточний файл у PREVIOUS_XLSX_PATH, щоб наступний виклик
    load_recent_sold_qty_by_pharmacy() міг порахувати реальну дельту
    (свіжу швидкість продажу) між двома знімками, а не грубе середнє за
    весь період з початку року. Без цього кроку старий знімок втрачається
    назавжди, коли новий файл перезаписує sales_1c.xlsx."""
    import shutil
    if XLSX_PATH.exists():
        shutil.copy2(XLSX_PATH, PREVIOUS_XLSX_PATH)
        return True
    return False


def load_recent_sold_qty_by_pharmacy(min_sold=0):
    """Свіжа швидкість продажу — дельта між ПОТОЧНИМ і ПОПЕРЕДНІМ
    знімками 1С (не середнє з початку року). Значно точніше за
    load_sold_qty_by_pharmacy() для товарів з нерівномірним/сезонним
    продажем — фіксує знято користувачем 2026-08-10 (див.
    project-apteka-g24-defectura).

    Повертає ({(product_id, warehouse_id): delta_qty}, meta) або
    (None, None), якщо PREVIOUS_XLSX_PATH ще не існує (тільки один знімок
    поки що) — виклик відповідає за fallback на повноперіодне середнє.

    meta містить period_start/period_end ПОТОЧНОГО знімку (для сумісності
    з source_note()) плюс days_between і previous_period_end.
    """
    if not PREVIOUS_XLSX_PATH.exists():
        return None, None

    current_sold, current_meta = load_sold_qty_by_pharmacy(min_sold=0)
    if current_meta is None:
        return None, None

    previous_sold, previous_meta = load_sold_qty_by_pharmacy(
        xlsx_path=PREVIOUS_XLSX_PATH, min_sold=0
    )
    if previous_meta is None:
        return None, None

    d1 = datetime.strptime(previous_meta["period_end"], "%d.%m.%Y %H:%M:%S")
    d2 = datetime.strptime(current_meta["period_end"], "%d.%m.%Y %H:%M:%S")
    days_between = (d2 - d1).days
    if days_between <= 0:
        # той самий файл скопійований в обидва місця (архівування щойно
        # відбулось, новий ще не залитий) — дельта безглузда, не повертати
        return None, None

    delta = {}
    for key, qty in current_sold.items():
        prev_qty = previous_sold.get(key, 0.0)
        d = qty - prev_qty
        if d > 0:
            delta[key] = d

    if min_sold:
        delta = {k: v for k, v in delta.items() if v >= min_sold}

    meta = {
        "period_start": previous_meta["period_end"],
        "period_end": current_meta["period_end"],
        "days_between": days_between,
        "matched_rows": current_meta["matched_rows"],
        "total_rows": current_meta["total_rows"],
    }
    return delta, meta


if __name__ == "__main__":
    sold, meta = load_sold_qty_by_pharmacy()
    if meta is None:
        print(f"Файл не знайдено: {XLSX_PATH}")
    else:
        print(f"Період: {meta['period_start']} — {meta['period_end']}")
        print(f"Зіставлено: {meta['matched_rows']} / {meta['total_rows']} рядків")
        print(f"Унікальних пар (товар, аптека): {len(sold)}")

```

---

## 8. sales_daily.py — поденна історія продажів (SQLite)

`scripts/sales_daily.py`

Без класів. `SCHEMA` — рядок `CREATE TABLE ...` з повним DDL (`daily_sales`,
`ingested_files`) — сама схема SQLite-бази визначена прямо тут, у коді, а не в
окремій міграції. `DB_PATH` — шлях до файлу `sales_daily.db` (у `.gitignore`).

`norm_filial(s)` — нормалізація назви філії з конкретними правилами, знайденими
емпірично на реальних файлах ("Центральна база"→"Центральная база" тощо).
`ingest_file(xlsx_path, mysql_conn=None)` — головна функція: читає `xlsx`,
з `oc_product`/`oc_warehouses_description` (через MySQL-з'єднання, яке можна
передати ззовні або відкрити самому) будує словники `model_to_pid`/`title_to_wid`
для зіставлення, потім рядок за рядком розбирає структуру аркуша "TDSheet"
(групування Філія→Місяць→День→Товар, з конкретними індексами колонок `row[0]`,
`row[3]`, `row[5]`, `row[7]`, `row[8]`, `row[9]` — визначеними вручну під
формат саме цього звіту 1С) і зберігає підсумки в SQLite через
`INSERT ... ON CONFLICT ... DO UPDATE` (ідемпотентний upsert).

```python
#!/usr/bin/env python3
"""Реальна ПОДЕННА історія продажів — з ручних вигрузок 1С звіту
"Реалізація товару" з групуванням Філія → Місяць → День → Товар.Код
(не плутати зі старим sales_1c.py, який читає ОДИН сукупний знімок за
весь період без розбивки по днях — той лишається fallback-джерелом,
якщо цей набір даних порожній).

ВАЖЛИВО (пастка, знайдена 2026-08-11): у 1С звіті "Реалізація товару"
поле "День" саме по собі (без "Місяць") дає ДЕНЬ МІСЯЦЯ (1-31), і при
виборі періоду довшого за один місяць 1С СХЛОПУЄ однакові числа місяця
з РІЗНИХ місяців в один рядок (1 січня + 1 лютого + 1 березня → один
"День 1"). Поле "Період рік.День года"/"Період рік.Місяць" теж не
працює — виявилось прив'язаним до кінця періоду (завжди 31 грудня),
а не до дати самого чека. **Правильна комбінація, підтверджена вручну:
"Період: День.Части дат.Місяць" (ієрархія) + "Період: День.Части
дат.День" (без ієрархії)** — обидва з родини "Період: День", не
"Період рік". Перевірено: суми збігаються на всіх рівнях, товарний код
100% покритий, місяці в правильному діапазоні без "місяця 12" в
серпневих даних.

Джерело також відфільтроване в самому 1С на "Документ видатка: Вид
Равно 'ЧекАптека'" — тобто це ТІЛЬКИ реальні чеки продажу, БЕЗ
внутрішніх переміщень товару між аптеками (підтверджено емпірично на
кейсі Цефаселю, Аптека №13, 2026-08-11).

Формат xlsx: колонки (0-indexed) — 0=Філія, 3=Місяць (тільки на
рядку-маркері дня), 5=День (той самий рядок), 7=Товар.Код (тільки на
товарному рядку), 8=Кількість, 9=Сума виторг. Рік для кожного файлу
береться з "Початок періоду" в шапці (C4) — один xlsx = один календарний
рік чи його частина, рік не змінюється всередині файлу.

Товар зіставляється НАПРЯМУ за кодом (oc_product.model) — жодного
fuzzy-матчингу за назвою, як у sales_1c.py. Філія — та сама
регулярка, що й в sales_1c.py (Аптека№10 -> Аптека №10 і т.д.).
"""
import re
import sqlite3
from datetime import date
from pathlib import Path

import openpyxl

from opencart_sales import connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
DB_PATH = CONNECTORS_DIR / "opencart" / "sales_daily.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_sales (
    product_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    sale_date TEXT NOT NULL,
    qty REAL NOT NULL,
    revenue REAL NOT NULL,
    PRIMARY KEY (product_id, warehouse_id, sale_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_sales_pw ON daily_sales (product_id, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_daily_sales_date ON daily_sales (sale_date);

CREATE TABLE IF NOT EXISTS ingested_files (
    filename TEXT PRIMARY KEY,
    period_start TEXT,
    period_end TEXT,
    total_rows INTEGER,
    matched_rows INTEGER,
    ingested_at TEXT
);
"""


def norm_filial(s):
    s = str(s).lstrip("_").strip()
    s = s.replace("Центральна база", "Центральная база")
    s = re.sub(r"Аптека№(\d)", r"Аптека №\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def open_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def ingest_file(xlsx_path, mysql_conn=None):
    """Парсить один поденний xlsx і зливає (INSERT OR REPLACE) у
    sales_daily.db. Повертає dict зі статистикою. Ідемпотентно — той
    самий файл можна залити повторно, дублів не буде (PRIMARY KEY
    product_id+warehouse_id+sale_date перезаписує)."""
    xlsx_path = Path(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["TDSheet"]

    period_start_raw = str(ws["C4"].value or "")
    year_match = re.search(r"(\d{4})", period_start_raw)
    if not year_match:
        raise ValueError(f"Не вдалось визначити рік з C4: {period_start_raw!r}")
    year = int(year_match.group(1))
    period_end_raw = str(ws["C5"].value or "")

    own_conn = mysql_conn is None
    if own_conn:
        env = read_env(ENV_PATH)
        mysql_conn = connect(env)
    try:
        with mysql_conn.cursor() as cur:
            cur.execute("SELECT model, product_id FROM oc_product")
            model_to_pid = {r["model"]: r["product_id"] for r in cur.fetchall()}
            cur.execute("SELECT warehouses_id, title FROM oc_warehouses_description")
            title_to_wid = {r["title"]: r["warehouses_id"] for r in cur.fetchall()}
    finally:
        if own_conn:
            mysql_conn.close()

    titles_sorted_desc = sorted(title_to_wid, key=len, reverse=True)

    def match_filial(fname):
        for t in titles_sorted_desc:
            if fname == t or fname.startswith(t + " ") or fname.startswith(t + ","):
                return title_to_wid[t]
        return None

    aggregated = {}  # (product_id, warehouse_id, date) -> [qty, revenue]
    total_rows = 0
    matched_rows = 0
    cur_wid = None
    cur_month = None
    cur_day = None

    for row in ws.iter_rows(min_row=8, values_only=True):
        filial, month, day, sku, qty, revenue = row[0], row[3], row[5], row[7], row[8], row[9]
        if filial is not None:
            cur_wid = match_filial(norm_filial(filial))
            cur_month = None
            cur_day = None
            continue
        if month is not None:
            cur_month = month
            cur_day = day
            continue
        if sku is None:
            continue
        total_rows += 1
        if cur_wid is None:
            continue
        pid = model_to_pid.get(sku)
        if pid is None:
            continue
        try:
            d = date(year, cur_month, cur_day)
        except (ValueError, TypeError):
            continue
        matched_rows += 1
        key = (pid, cur_wid, d.isoformat())
        entry = aggregated.setdefault(key, [0.0, 0.0])
        entry[0] += qty or 0
        entry[1] += revenue or 0

    hist = open_db()
    try:
        hist.executemany(
            "INSERT INTO daily_sales (product_id, warehouse_id, sale_date, qty, revenue) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(product_id, warehouse_id, sale_date) DO UPDATE SET "
            "qty = excluded.qty, revenue = excluded.revenue",
            [(pid, wid, d, q, r) for (pid, wid, d), (q, r) in aggregated.items()],
        )
        hist.execute(
            "INSERT OR REPLACE INTO ingested_files "
            "(filename, period_start, period_end, total_rows, matched_rows, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (xlsx_path.name, period_start_raw, period_end_raw, total_rows, matched_rows),
        )
        hist.commit()
    finally:
        hist.close()

    return {
        "filename": xlsx_path.name,
        "year": year,
        "total_rows": total_rows,
        "matched_rows": matched_rows,
        "unique_days": len(aggregated),
    }


def get_sold_qty_since(days_back=None, since_date=None, min_sold=0):
    """{(product_id, warehouse_id): sold_qty} за останні days_back днів
    (від сьогодні) або з конкретної дати since_date. Один із двох
    параметрів обов'язковий."""
    if since_date is None:
        if days_back is None:
            raise ValueError("Потрібен days_back або since_date")
        since_date = (date.today() - __import__("datetime").timedelta(days=days_back)).isoformat()
    elif hasattr(since_date, "isoformat"):
        since_date = since_date.isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT product_id, warehouse_id, SUM(qty) FROM daily_sales "
            "WHERE sale_date >= ? GROUP BY product_id, warehouse_id",
            (since_date,),
        ).fetchall()
    finally:
        conn.close()

    result = {(pid, wid): qty for pid, wid, qty in rows if qty >= min_sold}
    return result


def get_sold_qty_since_blended(days_back=None, since_date=None, min_sold=0):
    """Як get_sold_qty_since(), але автоматично продовжує вікно поза межі
    ручної 1С-вигрузки (заморожена 11.08.2026, разова базова вибірка для
    калібрування) даними з власного 15-хвилинного трекера падінь залишку
    (stock_snapshot.stock_drops) — бо повторних ручних вигрузок з 1С не
    планується, а Rest-фід від АНР оновлюється постійно.

    Джерела ОБОВ'ЯЗКОВО складаються по (product_id, warehouse_id) ДО
    застосування min_sold, а не фільтруються кожне окремо — інакше товар,
    що продавався лише в "хвостовій" (stock_drops) частині вікна, хибно
    відсіється, хоча сумарно продажі є."""
    import stock_snapshot
    from datetime import datetime, timedelta

    if since_date is None:
        if days_back is None:
            raise ValueError("Потрібен days_back або since_date")
        since_date_obj = date.today() - timedelta(days=days_back)
    elif hasattr(since_date, "isoformat"):
        since_date_obj = since_date if not isinstance(since_date, datetime) else since_date.date()
    else:
        since_date_obj = date.fromisoformat(since_date)

    combined = dict(get_sold_qty_since(since_date=since_date_obj, min_sold=0))

    coverage = get_coverage()
    max_date = coverage["max_date"]
    gap_start = date.fromisoformat(max_date) + timedelta(days=1) if max_date else since_date_obj
    if gap_start < since_date_obj:
        gap_start = since_date_obj

    if gap_start <= date.today():
        gap_start_dt = datetime.combine(gap_start, datetime.min.time())
        drops_part = stock_snapshot.get_sold_qty_since(gap_start_dt)
        for key, qty in drops_part.items():
            combined[key] = combined.get(key, 0) + qty

    return {key: qty for key, qty in combined.items() if qty >= min_sold}


def get_sold_qty_by_product_in_range(start_date, end_date):
    """{product_id: sold_qty} по ВСІЙ МЕРЕЖІ (не по аптеках окремо) за
    замкнутий діапазон [start_date, end_date] — на відміну від
    get_sold_qty_since (яка завжди рахує ДО СЬОГОДНІ), тут обидва кінці
    можуть бути в минулому. Потрібно для порівняння того самого періоду
    рік-до-року (сезонність, seasonality.py)."""
    if hasattr(start_date, "isoformat"):
        start_date = start_date.isoformat()
    if hasattr(end_date, "isoformat"):
        end_date = end_date.isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT product_id, SUM(qty) FROM daily_sales "
            "WHERE sale_date >= ? AND sale_date <= ? GROUP BY product_id",
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    return {pid: qty for pid, qty in rows}


def get_sold_qty_by_pw_in_range(start_date, end_date):
    """{(product_id, warehouse_id): sold_qty} за замкнутий діапазон
    [start_date, end_date] — та сама ідея, що й get_sold_qty_by_product_in_range,
    але з розбивкою по аптеках (потрібно для перевірки стабільності
    попиту САМЕ В КОНКРЕТНІЙ аптеці, redistribution.py)."""
    if hasattr(start_date, "isoformat"):
        start_date = start_date.isoformat()
    if hasattr(end_date, "isoformat"):
        end_date = end_date.isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT product_id, warehouse_id, SUM(qty) FROM daily_sales "
            "WHERE sale_date >= ? AND sale_date <= ? GROUP BY product_id, warehouse_id",
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    return {(pid, wid): qty for pid, wid, qty in rows}


def has_data():
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        n = conn.execute("SELECT COUNT(*) FROM daily_sales").fetchone()[0]
        return n > 0
    finally:
        conn.close()


def get_coverage():
    """Метадані про накопичену історію — min/max дата, кількість файлів."""
    conn = sqlite3.connect(DB_PATH)
    try:
        min_d, max_d, total = conn.execute(
            "SELECT MIN(sale_date), MAX(sale_date), COUNT(*) FROM daily_sales"
        ).fetchone()
        files = conn.execute(
            "SELECT filename, period_start, period_end, matched_rows FROM ingested_files"
        ).fetchall()
    finally:
        conn.close()
    return {"min_date": min_d, "max_date": max_d, "total_rows": total, "files": files}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Використання: sales_daily.py <файл1.xlsx> [файл2.xlsx ...]")
        print()
        if has_data():
            cov = get_coverage()
            print(f"Поточна історія: {cov['min_date']} — {cov['max_date']}, {cov['total_rows']} записів")
            for f in cov["files"]:
                print(f"  {f[0]}: {f[1]} — {f[2]}, {f[3]} рядків зіставлено")
        else:
            print("База ще порожня.")
        sys.exit(0)

    env = read_env(ENV_PATH)
    mysql_conn = connect(env)
    try:
        for path in sys.argv[1:]:
            print(f"Заливаю {path}...")
            stats = ingest_file(path, mysql_conn=mysql_conn)
            print(f"  {stats['matched_rows']}/{stats['total_rows']} рядків, "
                  f"{stats['unique_days']} унікальних (товар,аптека,день), рік {stats['year']}")
    finally:
        mysql_conn.close()

    cov = get_coverage()
    print(f"\nРазом в базі: {cov['min_date']} — {cov['max_date']}, {cov['total_rows']} записів")

```

---

## 9. stock_snapshot.py — власний трекер падінь залишків

`scripts/stock_snapshot.py`

Без класів. `open_history_db()` відкриває/створює SQLite-базу з власною
схемою (падіння кількості по товару+складу+часу). `fetch_current_warehouse_state`
читає `product_warehouse` з MySQL (той самий read-only `connect`/`read_env` з
`opencart_sales.py`, імпортовані звідти напряму — не продубльовані). `run_snapshot()`
порівнює щойно прочитаний стан із попереднім записом у SQLite і зберігає лише
рядки, де кількість **зменшилась** — сама умова "зменшення = продаж" це
бізнес-припущення, зафіксоване в докстрінгу, а не факт з джерела даних.

```python
#!/usr/bin/env python3
"""Власний трекер зміни залишків — доки АНР не дає per-SKU продажі по аптеці
(див. project-apteka-g24-defectura, доповнення в opencart/ANR_sales_export_TZ.md).

Кожен запуск порівнює поточний product_warehouse (real-time, ~15 хв від АНР
через Rest*.xml) з останнім відомим станом і логує ТІЛЬКИ зменшення кількості
в окрему SQLite-базу (не пишемо нічого в саму OpenCart DB — вона навмисно
read-only). Зменшення = проксі на "продано" — і для сайтових замовлень, і
для живих відвідувачів, що купили на місці: обидва однаково зменшують
product_warehouse.quantity, на відміну від oc_order, який бачить лише сайт.

Не 100% точно (сюди ж потрапить, наприклад, списання/пересорт), але значно
ближче до реальності, ніж рахувати тільки сайтові замовлення.

Запускати періодично (рекомендовано кожні 15 хв, тим самим кроном, що й
update_quantity.php на сервері) — довше проміжок між запусками, то більше
шанс "проґавити" проміжне падіння-і-відновлення кількості між двома знімками.
"""
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from opencart_sales import connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
DB_PATH = CONNECTORS_DIR / "opencart" / "stock_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS current_state (
    product_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (product_id, warehouse_id)
);

CREATE TABLE IF NOT EXISTS stock_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL,
    qty_before REAL NOT NULL,
    qty_after REAL NOT NULL,
    drop_amount REAL NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drops_product_wh_time
    ON stock_drops (product_id, warehouse_id, captured_at);
"""


def open_history_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def fetch_current_warehouse_state(mysql_conn):
    with mysql_conn.cursor() as cur:
        cur.execute("SELECT product_id, warehouse_id, quantity FROM product_warehouse")
        return cur.fetchall()


def run_snapshot():
    env = read_env(ENV_PATH)
    mysql_conn = connect(env)
    try:
        rows = fetch_current_warehouse_state(mysql_conn)
    finally:
        mysql_conn.close()

    now = datetime.utcnow().isoformat(timespec="seconds")
    hist = open_history_db()
    try:
        cur = hist.execute("SELECT product_id, warehouse_id, quantity FROM current_state")
        known = {(r[0], r[1]): r[2] for r in cur.fetchall()}

        drops = 0
        seen = set()
        for row in rows:
            key = (row["product_id"], row["warehouse_id"])
            seen.add(key)
            new_qty = row["quantity"]
            old_qty = known.get(key)

            if old_qty is not None and new_qty < old_qty:
                hist.execute(
                    "INSERT INTO stock_drops "
                    "(product_id, warehouse_id, qty_before, qty_after, drop_amount, captured_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key[0], key[1], old_qty, new_qty, old_qty - new_qty, now),
                )
                drops += 1

            if old_qty != new_qty:
                hist.execute(
                    "INSERT INTO current_state (product_id, warehouse_id, quantity, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(product_id, warehouse_id) DO UPDATE SET quantity=excluded.quantity, updated_at=excluded.updated_at",
                    (key[0], key[1], new_qty, now),
                )

        hist.commit()
        return {"pairs_seen": len(seen), "drops_logged": drops, "known_before": len(known)}
    finally:
        hist.close()


def sold_qty_since(product_id, warehouse_id, since_dt):
    hist = open_history_db()
    try:
        cur = hist.execute(
            "SELECT COALESCE(SUM(drop_amount), 0) FROM stock_drops "
            "WHERE product_id = ? AND warehouse_id = ? AND captured_at >= ?",
            (product_id, warehouse_id, since_dt.isoformat(timespec="seconds")),
        )
        return cur.fetchone()[0]
    finally:
        hist.close()


def get_sold_qty_since(since_dt):
    """{(product_id, warehouse_id): sold_qty} по ВСІХ товарах з stock_drops
    від since_dt (datetime) до зараз — масова версія sold_qty_since(), щоб
    не робити окремий запит на кожен товар. Формою повернення співпадає з
    sales_daily.get_sold_qty_since(), щоб дані з двох джерел можна було
    змішувати за однаковим ключем."""
    hist = open_history_db()
    try:
        rows = hist.execute(
            "SELECT product_id, warehouse_id, SUM(drop_amount) FROM stock_drops "
            "WHERE captured_at >= ? GROUP BY product_id, warehouse_id",
            (since_dt.isoformat(timespec="seconds"),),
        ).fetchall()
        return {(pid, wid): qty for pid, wid, qty in rows}
    finally:
        hist.close()


def main():
    stats = run_snapshot()
    print(
        f"[{datetime.utcnow().isoformat(timespec='seconds')}] "
        f"pairs={stats['pairs_seen']} known_before={stats['known_before']} "
        f"drops_logged={stats['drops_logged']}"
    )


if __name__ == "__main__":
    main()

```

---

## 10. defectura.py — товар з нульовим залишком

`scripts/defectura.py`

Без класів. Константи `DEFECTURA_WINDOW_DAYS`, `SALES_WINDOW_DAYS` —
бізнес-правила ("скільки днів вважати за 'зазвичай продається'"), підібрані і
змінені за прямими вказівками користувача (див. коментарі з датами в коді).
Кожна з чотирьох `fetch_defectura_per_pharmacy_from_*` функцій має однаковий
контракт (бере `conn`, повертає список рядків "товар/аптека/скільки зазвичай
продавалось") але різне джерело даних усередині: `sales_daily` (SQLite,
`import sales_daily`), `sales_1c` (Excel-знімок), `stock_snapshot` (власний
SQLite-трекер) або прямий SQL по `oc_order`. `fetch_defectura_per_pharmacy`
викликає їх по черзі (`if data: return data, source_name`) — перше непорожнє
джерело і визначає, які саме `source`/`meta` побачить користувач у звіті.

```python
#!/usr/bin/env python3
"""Дефектура: товари, що зазвичай продаються В КОНКРЕТНІЙ АПТЕЦІ, але зараз
мають там 0 залишку.

Той самий read-only доступ до OpenCart DB, що й opencart_sales.py.

Логіка реального залишку повторює catalog/model/catalog/product.php::getProduct()
з боку сайту (див. project-apteka-g24-stock-sync): якщо у товару є рядки в
product_warehouse — реальний залишок це SUM(quantity) по аптеках (там уже
цілі упаковки, порахував нічний cron); якщо рядків немає — fallback на
застаріле oc_product.quantity.

"Зазвичай продається" — РЕАЛЬНІ дані по кожній аптеці окремо.
Чотириступеневий fallback (2026-08-11, після переходу на поденні дані):
  1. `daily` (sales_daily.py, SQLite `opencart/sales_daily.db`) —
     НАЙКРАЩЕ джерело: справжня поденна історія (Філія→Місяць→День→
     Товар.Код) з ручних вигрузок 1С, зіставлення за кодом (не за
     назвою), охоплення 2025-01-01 і далі. "Продається" рахується у
     ROLLING вікні (DEFECTURA_WINDOW_DAYS днів від сьогодні), не за весь
     період — товар, що продавався пів року тому й затих, більше НЕ
     вважається дефектурою (див. правило користувача 2026-08-11:
     "якщо препарат стоїть місяць — переходить в неліквіди", реалізовано
     тут через recency-вікно, а не статичний період).
  2. 1С (sales_1c.py) — старий формат: один сукупний знімок за ввесь
     період вигрузки (зазвичай з початку року), без розбивки по днях.
     Гірше за (1), бо не відрізняє "продавалось нещодавно" від "продавалось
     давно й затихло" — лишається fallback, якщо daily-бази ще нема.
  3. stock_drops (stock_snapshot.py, SQLite `opencart/stock_history.db`) —
     власний трекер падінь product_warehouse.quantity кожні 15 хв, теж
     ловить живих відвідувачів (не тільки сайт), але це проксі на "продано"
     (могло бути й списання/пересорт) і історія лише відколи почали
     трекати (з 2026-08-04)
  4. Мережевий проксі по сайтових замовленнях (SALES_WINDOW_DAYS днів,
     oc_order) — найслабший, лишається як останній рубіж, щоб код не падав
"""
import functools
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import sales_1c
import sales_daily
from opencart_sales import VALID_ORDER_FILTER, connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
STOCK_HISTORY_DB_PATH = CONNECTORS_DIR / "opencart" / "stock_history.db"

SALES_WINDOW_DAYS = 30  # тільки для fallback-проксі, якщо 1С файлу нема
DEFECTURA_WINDOW_DAYS = 90  # "продається" = продавалось в останні N днів (daily-рівень)
RATE_WINDOW_DAYS = 30  # коротше вікно для швидкості продажу (est_daily_loss) —
# 90-денне середнє може включати період, коли товару вже не було в наявності,
# й занижувати реальний поточний темп (питання користувача 2026-08-11)


def fetch_defectura_per_pharmacy_from_daily(conn, window_days=DEFECTURA_WINDOW_DAYS, min_sold=1):
    """Найкращий рівень — реальна поденна історія (sales_daily.py). Товар
    вважається дефектурою в аптеці, якщо продавався там (sold_qty >=
    min_sold) за останні window_days днів (rolling, не статичний період)
    і зараз quantity <= 0.

    Повертає (by_pharmacy, meta) або (None, None), якщо база sales_daily
    ще порожня — виклик відповідає за fallback.
    """
    if not sales_daily.has_data():
        return None, None

    sold_by_pw = sales_daily.get_sold_qty_since_blended(days_back=window_days, min_sold=min_sold)
    if not sold_by_pw:
        return None, None

    # окреме коротше вікно ЛИШЕ для швидкості продажу (est_daily_loss) —
    # eligibility ("чи це взагалі ходовий товар") лишається на window_days
    recent_sold_by_pw = sales_daily.get_sold_qty_since_blended(days_back=RATE_WINDOW_DAYS, min_sold=0)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   p.model, pw.price, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity <= 0 AND pd.name NOT LIKE 'КАРТКА%'
        """)
        zero_stock_rows = cur.fetchall()

    by_pharmacy = {}
    for row in zero_stock_rows:
        key = (row["product_id"], row["warehouse_id"])
        sold_qty = sold_by_pw.get(key)
        if not sold_qty:
            continue
        wid = row["warehouse_id"]
        entry = by_pharmacy.setdefault(
            wid, {"label": row["warehouse_title"] or f"Склад {wid}", "items": []}
        )
        price = float(row["price"]) if row["price"] is not None else 0.0
        recent_sold_qty = recent_sold_by_pw.get(key, 0)
        # оцінна щоденна втрата продажу через відсутність товару САМЕ ТУТ:
        # швидкість продажу за коротше RATE_WINDOW_DAYS-вікно (актуальніше за
        # 90-денне середнє) × ціна
        daily_rate = recent_sold_qty / RATE_WINDOW_DAYS
        entry["items"].append({
            "product_id": row["product_id"],
            "model": row["model"],
            "product_name": row["product_name"],
            "sold_qty": sold_qty,
            "recent_sold_qty": recent_sold_qty,
            "price": price,
            "est_daily_loss": daily_rate * price,
        })

    for entry in by_pharmacy.values():
        entry["items"].sort(key=lambda x: -x["est_daily_loss"])

    network_est_daily_loss = sum(
        item["est_daily_loss"] for entry in by_pharmacy.values() for item in entry["items"]
    )
    meta = {
        "period_start": f"останні {window_days} дн.",
        # 1С-вигрузка заморожена на 11.08.2026 — далі вікно продовжується
        # даними з власного трекера падінь залишку (get_sold_qty_since_blended),
        # тому реальна межа даних — сьогодні, а не cov["max_date"]
        "period_end": date.today().isoformat(),
        "network_est_daily_loss": network_est_daily_loss,
        "rate_window_days": RATE_WINDOW_DAYS,
    }
    return by_pharmacy, meta


def fetch_defectura_per_pharmacy_from_1c(conn, min_sold=1):
    """Дефектура по кожній аптеці на РЕАЛЬНИХ даних з 1С: товар продавався
    (sold_qty >= min_sold) саме в цій аптеці за період вигрузки, а зараз
    там quantity <= 0.

    Повертає (by_pharmacy, meta) або (None, None), якщо файл 1С не
    знайдено — виклик відповідає за fallback.
    """
    sold_by_pw, meta = sales_1c.load_sold_qty_by_pharmacy(min_sold=min_sold)
    if meta is None:
        return None, None

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   p.model, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity <= 0 AND pd.name NOT LIKE 'КАРТКА%'
        """)
        zero_stock_rows = cur.fetchall()

    by_pharmacy = {}
    for row in zero_stock_rows:
        key = (row["product_id"], row["warehouse_id"])
        sold_qty = sold_by_pw.get(key)
        if not sold_qty:
            continue
        wid = row["warehouse_id"]
        entry = by_pharmacy.setdefault(
            wid, {"label": row["warehouse_title"] or f"Склад {wid}", "items": []}
        )
        entry["items"].append({
            "product_id": row["product_id"],
            "model": row["model"],
            "product_name": row["product_name"],
            "sold_qty": sold_qty,
        })

    for entry in by_pharmacy.values():
        entry["items"].sort(key=lambda x: -x["sold_qty"])

    return by_pharmacy, meta


def fetch_defectura_per_pharmacy_from_stock_drops(conn, min_sold=1):
    """Середній fallback: власний трекер падінь product_warehouse.quantity
    (stock_snapshot.py, кожні 15 хв) — сума падінь за (product_id,
    warehouse_id) за весь час трекінгу як проксі на "продано САМЕ ТУТ".

    Повертає (by_pharmacy, meta) або (None, None), якщо база ще не
    створена/порожня — виклик відповідає за подальший fallback.
    """
    if not STOCK_HISTORY_DB_PATH.exists():
        return None, None

    hist = sqlite3.connect(STOCK_HISTORY_DB_PATH)
    try:
        first_seen = hist.execute("SELECT MIN(updated_at) FROM current_state").fetchone()[0]
        rows = hist.execute(
            "SELECT product_id, warehouse_id, SUM(drop_amount) FROM stock_drops "
            "GROUP BY product_id, warehouse_id"
        ).fetchall()
    finally:
        hist.close()

    if not rows or first_seen is None:
        return None, None

    sold_by_pw = {(pid, wid): qty for pid, wid, qty in rows if qty >= min_sold}
    if not sold_by_pw:
        return None, None

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   p.model, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity <= 0 AND pd.name NOT LIKE 'КАРТКА%'
        """)
        zero_stock_rows = cur.fetchall()

    by_pharmacy = {}
    for row in zero_stock_rows:
        key = (row["product_id"], row["warehouse_id"])
        sold_qty = sold_by_pw.get(key)
        if not sold_qty:
            continue
        wid = row["warehouse_id"]
        entry = by_pharmacy.setdefault(
            wid, {"label": row["warehouse_title"] or f"Склад {wid}", "items": []}
        )
        entry["items"].append({
            "product_id": row["product_id"],
            "model": row["model"],
            "product_name": row["product_name"],
            "sold_qty": sold_qty,
        })

    for entry in by_pharmacy.values():
        entry["items"].sort(key=lambda x: -x["sold_qty"])

    meta = {"period_start": first_seen, "period_end": "зараз"}
    return by_pharmacy, meta


def fetch_defectura_per_pharmacy_network_proxy(conn, sales_window_days=SALES_WINDOW_DAYS):
    """Старий fallback (мережевий проксі по сайтових замовленнях) — тільки
    якщо файл 1С ще не залитий на сервер. Товар вважається дефектурою в
    конкретній аптеці, якщо в product_warehouse Є рядок з quantity=0, і
    товар продавався ХОЧ ДЕСЬ у мережі (не обов'язково саме тут) за
    sales_window_days днів."""
    since = date.today() - timedelta(days=sales_window_days)
    query = f"""
        SELECT
            pw.warehouse_id,
            wd.title AS warehouse_title,
            p.product_id,
            p.model,
            pd.name AS product_name,
            s.sold_qty
        FROM product_warehouse pw
        JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
        JOIN oc_product_description pd
            ON pd.product_id = p.product_id AND pd.language_id = 3
        LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
        JOIN (
            SELECT op.product_id, SUM(op.quantity) AS sold_qty
            FROM oc_order_product op
            JOIN oc_order o ON o.order_id = op.order_id
            WHERE DATE(o.date_added) >= %s AND {VALID_ORDER_FILTER}
            GROUP BY op.product_id
        ) s ON s.product_id = p.product_id
        WHERE pw.quantity <= 0 AND pd.name NOT LIKE 'КАРТКА%%'
        ORDER BY wd.title, s.sold_qty DESC
    """
    with conn.cursor() as cur:
        cur.execute(query, (since,))
        rows = cur.fetchall()

    by_pharmacy = {}
    for row in rows:
        wid = row["warehouse_id"]
        entry = by_pharmacy.setdefault(
            wid, {"label": row["warehouse_title"] or f"Склад {wid}", "items": []}
        )
        entry["items"].append({
            "product_id": row["product_id"],
            "model": row["model"],
            "product_name": row["product_name"],
            "sold_qty": row["sold_qty"],
        })
    return by_pharmacy


def fetch_defectura_per_pharmacy(conn, sales_window_days=SALES_WINDOW_DAYS, min_sold=1):
    """Диспетчер на спільному conn (для перевикористання іншими модулями,
    напр. redistribution.py) — чотириступеневий fallback: daily → 1С →
    stock_drops → мережевий проксі. Повертає (by_pharmacy, data_source, meta)."""
    by_pharmacy, meta = fetch_defectura_per_pharmacy_from_daily(conn, min_sold=min_sold)
    if by_pharmacy is not None:
        return by_pharmacy, "daily", meta

    by_pharmacy, meta = fetch_defectura_per_pharmacy_from_1c(conn, min_sold=min_sold)
    if by_pharmacy is not None:
        return by_pharmacy, "1c", meta

    by_pharmacy, meta = fetch_defectura_per_pharmacy_from_stock_drops(conn, min_sold=min_sold)
    if by_pharmacy is not None:
        return by_pharmacy, "stock_drops", meta

    by_pharmacy = fetch_defectura_per_pharmacy_network_proxy(
        conn, sales_window_days=sales_window_days
    )
    return by_pharmacy, "network_proxy", None


@functools.lru_cache(maxsize=8)
def get_data_per_pharmacy(sales_window_days=SALES_WINDOW_DAYS, min_sold=1):
    """Кешується на рівні процесу (той самий параметр -> той самий
    результат, повторний виклик не б'є по БД знову) — без цього
    stock_history_status.py рахував дефектуру по 3-4 рази незалежно за
    один запуск (дайджест + розбивка по категоріях кожен викликали
    заново), і на обмеженій пам'яті сервера це іноді спричиняло тихе
    падіння на гірший fallback (знайдено й виправлено 2026-08-11)."""
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        by_pharmacy, data_source, meta = fetch_defectura_per_pharmacy(
            conn, sales_window_days=sales_window_days, min_sold=min_sold
        )
    finally:
        conn.close()

    return {
        "data_source": data_source,
        "sales_window_days": sales_window_days if data_source == "network_proxy" else None,
        "period": meta,
        "pharmacies": by_pharmacy,
        "total_items": sum(len(v["items"]) for v in by_pharmacy.values()),
        # оцінка недоотриманого щоденного продажу по всій мережі — тільки для
        # daily-рівня (тільки там є реальна швидкість продажу по кожній парі
        # товар×аптека, за якою можна вважати ціну втрат)
        "total_est_daily_loss": (meta or {}).get("network_est_daily_loss") if data_source == "daily" else None,
    }


def get_data(sales_window_days=SALES_WINDOW_DAYS, min_sold=1, limit=None):
    """Мережевий підсумок (усі аптеки разом): товар з нульовим залишком
    ПО ВСІЙ МЕРЕЖІ (не по одній аптеці), відсортований за сумарними
    реальними продажами."""
    per_pharmacy = get_data_per_pharmacy(sales_window_days=sales_window_days, min_sold=min_sold)

    agg = {}
    for entry in per_pharmacy["pharmacies"].values():
        for item in entry["items"]:
            pid = item["product_id"]
            agg.setdefault(pid, {
                "product_id": pid,
                "model": item["model"],
                "product_name": item["product_name"],
                "sold_qty": 0,
                "recent_sold_qty": 0,
                "est_daily_loss": 0.0,
            })
            agg[pid]["sold_qty"] += item["sold_qty"]
            agg[pid]["recent_sold_qty"] += item.get("recent_sold_qty", 0)
            agg[pid]["est_daily_loss"] += item.get("est_daily_loss", 0.0)

    # на daily-рівні сортуємо за грн-втратою (дорогий рідкісний препарат не
    # має губитись за дешевим ходовим товаром); на fallback-рівнях ціни нема
    # — сортуємо як раніше, за кількістю проданого
    if per_pharmacy["data_source"] == "daily":
        items = sorted(agg.values(), key=lambda x: -x["est_daily_loss"])
    else:
        items = sorted(agg.values(), key=lambda x: -x["sold_qty"])
    if limit:
        items = items[:limit]

    return {
        "data_source": per_pharmacy["data_source"],
        "sales_window_days": per_pharmacy["sales_window_days"],
        "period": per_pharmacy["period"],
        "items": items,
        "count": len(agg),
        "total_est_daily_loss": per_pharmacy["total_est_daily_loss"],
    }


def render_section(data=None):
    if data is None:
        data = get_data()

    lines = []
    lines.append("📦 ДЕФЕКТУРА (0 залишку по всій мережі, товари що продаються)")
    lines.append("")
    if data["data_source"] == "network_proxy":
        lines.append(
            f"⚠️ Файл 1С не знайдено — мережевий проксі "
            f"(вікно {data['sales_window_days']} дн., тільки сайтові замовлення)."
        )
    lines.append(f"Знайдено {data['count']} товар(ів) з нульовим залишком по мережі")
    lines.append("")

    if data["items"]:
        for i, item in enumerate(data["items"], start=1):
            model = item["model"] or f"id{item['product_id']}"
            lines.append(
                f"{i}. {item['product_name']} ({model}) — продано {item['sold_qty']:g} шт"
            )
    else:
        lines.append("(дефектури немає)")
    lines.append("")

    return "\n".join(lines)


def render_section_per_pharmacy(data=None):
    if data is None:
        data = get_data_per_pharmacy()

    lines = []
    lines.append("📦 ДЕФЕКТУРА ПО АПТЕКАХ")
    lines.append("")
    if data["data_source"] == "daily":
        lines.append(
            f"✅ Реальна поденна історія (продажі саме в цій аптеці), "
            f"{data['period']['period_start']}, дані по {data['period']['period_end']}"
        )
    elif data["data_source"] == "1c":
        lines.append(
            f"✅ Реальні дані з 1С (продажі саме в цій аптеці), "
            f"період: {data['period']['period_start']} — {data['period']['period_end']}"
        )
    elif data["data_source"] == "stock_drops":
        lines.append(
            f"🟡 Файл 1С не знайдено — власний трекер падінь залишку "
            f"(по-аптечний сигнал, але з {data['period']['period_start']}, коротша історія)."
        )
    else:
        lines.append(
            f"⚠️ Ні 1С, ні трекер падінь недоступні — мережевий проксі "
            f"(вікно {data['sales_window_days']} дн., не по-аптечний сигнал)."
        )
    lines.append("")
    lines.append(f"Разом: {data['total_items']} позицій дефектури в {len(data['pharmacies'])} аптеках")
    lines.append("")

    for wid in sorted(data["pharmacies"], key=lambda w: data["pharmacies"][w]["label"]):
        entry = data["pharmacies"][wid]
        if not entry["items"]:
            continue
        lines.append(f"🏪 {entry['label']} — {len(entry['items'])} поз.")
        for item in entry["items"]:
            model = item["model"] or f"id{item['product_id']}"
            lines.append(
                f"   • {item['product_name']} ({model}) — продано {item['sold_qty']:g} шт"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Список дефектури (0 залишку)")
    parser.add_argument(
        "--days", type=int, default=SALES_WINDOW_DAYS,
        help="вікно для fallback-проксі, якщо файлу 1С нема (default: %(default)s)",
    )
    parser.add_argument("--limit", type=int, default=None, help="обмежити кількість рядків (тільки мережевий режим)")
    parser.add_argument(
        "--per-pharmacy", action="store_true",
        help="розбити по кожній аптеці окремо замість мережевого підсумку",
    )
    args = parser.parse_args()

    if args.per_pharmacy:
        data = get_data_per_pharmacy(sales_window_days=args.days)
        print(render_section_per_pharmacy(data))
    else:
        data = get_data(sales_window_days=args.days, limit=args.limit)
        print(render_section(data))


if __name__ == "__main__":
    main()

```

---

## 11. low_stock_alert.py — товар, що скоро закінчиться

`scripts/low_stock_alert.py`

Без класів. `DAYS_THRESHOLD`, `RECENT_WINDOW_DAYS`, `MIN_SOLD_TOTAL` —
бізнес-пороги. `_fetch_current_stock(conn)` читає поточні залишки з MySQL;
`_seasonal_multiplier_by_product()` тягне поправочний коефіцієнт із
`seasonality.py`, щоб не занижувати прогноз для товарів "на вході в сезон".
`_build_alerts(stock_rows, sold_by_pw, days_span, days_threshold, seasonal_multiplier=None)`
— чиста функція обчислення: на вхід подаються вже готові дані (звідки саме —
вирішує виклик "на рівень вище", один із п'яти `fetch_low_stock_from_*`), а
тут лише ділення `quantity / (продано_за_день)` і порівняння з порогом.

```python
#!/usr/bin/env python3
"""Товари, що СКОРО закінчаться в конкретній аптеці — на відміну від
defectura.py (яка вже 0), тут quantity > 0, але при поточному темпі
продажу закінчиться за DAYS_THRESHOLD днів. Рахується як
"поточний залишок / темп продажу в день".

П'ятиступеневий fallback, від найточнішого до найгрубішого (2026-08-11,
після переходу на поденні дані):
1. `daily` — реальна поденна історія (sales_daily.py), швидкість продажу
   за останні RECENT_WINDOW_DAYS днів (rolling). НАЙТОЧНІШЕ джерело —
   справжні щоденні продажі, зіставлені за кодом товару, охоплення
   2025-01-01 і далі.
2. `recent_1c` — дельта між ДВОМА знімками 1С (sales_1c.load_recent_sold_qty_by_pharmacy)
   — гірше за (1), бо це лише два точкові знімки, не справжня щоденна
   історія, але краще за статичне середнє.
3. `1c` — грубе середнє за ВЕСЬ період вигрузки (напр. з початку року).
   **Користувач слушно зауважив (2026-08-10): це неточно для товарів з
   нерівномірним/сезонним продажем** — весняний сплеск і зараз-затихло
   виглядають однаково як "стабільний темп". Позначається окремим
   застереженням у рендері (не 🟡/✅ як інші джерела, а явне ⚠️
   "може бути неточним").
4. `stock_drops` — власний трекер падінь (з 2026-08-04), теж середнє за
   період трекінгу, але значно коротший вікно — менше шансів приховати
   сезонність.
5. `unavailable` — недостатньо даних, розділ не показувати.

MIN_SOLD_TOTAL відсікає товари з випадковими поодинокими продажами.
Службові рядки з 1С (напр. "_Індивідуальный рецепт") відсіюються —
назва товару, що починається з "_", це не реальний SKU. Картки
(дисконтні/подарункові/VIP, назва починається з "КАРТКА") теж
відсіюються — це не товар, що потребує поповнення.
"""
import functools
import sqlite3
from datetime import date, datetime
from pathlib import Path

import sales_1c
import sales_daily
from opencart_sales import connect, read_env
from product_categories import get_category_map
from seasonality import get_data as get_seasonality_data

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
STOCK_HISTORY_DB_PATH = CONNECTORS_DIR / "opencart" / "stock_history.db"

MIN_SOLD_TOTAL = 10
DAYS_THRESHOLD = 5
RECENT_WINDOW_DAYS = 30  # вікно для daily-рівня


def _fetch_current_stock(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, pw.quantity,
                   wd.title AS warehouse_title, p.model, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity > 0
        """)
        return cur.fetchall()


def _seasonal_multiplier_by_product():
    """product_id -> множник (1 + growth_pct/100) для товарів у категоріях
    з очікуваним сезонним ростом (seasonality.py, forward-прогноз на
    основі торішнього періоду). Застосовується ЛИШЕ до daily-рівня — 30-
    денне вікно саме по собі не встигає вловити старт сезону, тому темп
    свідомо коригується консервативніше (запит користувача 2026-08-12).
    Ніколи не сповільнює оцінку — тільки прискорює (growth_pct тут завжди
    додатний, seasonality.py вже відсіює категорії з ростом < MIN_GROWTH_PCT)."""
    seasonality_data = get_seasonality_data()
    if seasonality_data["data_source"] is None or not seasonality_data["categories"]:
        return {}
    growth_by_category = {c["name"]: c["growth_pct"] for c in seasonality_data["categories"]}
    cat_map = get_category_map()
    return {
        pid: 1 + growth_by_category[cat] / 100
        for pid, cat in cat_map.items()
        if cat in growth_by_category
    }


def _build_alerts(stock_rows, sold_by_pw, days_span, days_threshold, seasonal_multiplier=None):
    alerts = []
    seasonal_multiplier = seasonal_multiplier or {}
    for row in stock_rows:
        if row["product_name"].startswith("_") or row["product_name"].startswith("КАРТКА"):
            continue
        key = (row["product_id"], row["warehouse_id"])
        sold_qty = sold_by_pw.get(key)
        if not sold_qty:
            continue
        boost = seasonal_multiplier.get(row["product_id"], 1.0)
        daily_rate = sold_qty / days_span * boost
        days_left = row["quantity"] / daily_rate
        if days_left <= days_threshold:
            alerts.append({
                "product_id": row["product_id"],
                "warehouse_id": row["warehouse_id"],
                "warehouse_title": row["warehouse_title"] or f"Склад {row['warehouse_id']}",
                "model": row["model"],
                "product_name": row["product_name"],
                "quantity": row["quantity"],
                "sold_qty": sold_qty,
                "daily_rate": daily_rate,
                "days_left": days_left,
                "seasonal_adjusted": boost > 1.0,
            })
    alerts.sort(key=lambda a: a["days_left"])
    return alerts


def fetch_low_stock_from_daily(conn, min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD,
                                window_days=RECENT_WINDOW_DAYS):
    """Найточніший рівень — реальна поденна історія, справжня швидкість
    продажу за останні window_days днів. (None, None), якщо sales_daily.db
    ще порожня."""
    if not sales_daily.has_data():
        return None, None

    sold_by_pw = sales_daily.get_sold_qty_since_blended(days_back=window_days, min_sold=min_sold)
    stock_rows = _fetch_current_stock(conn)
    seasonal_multiplier = _seasonal_multiplier_by_product()
    alerts = _build_alerts(stock_rows, sold_by_pw, window_days, days_threshold, seasonal_multiplier)

    # 1С-вигрузка заморожена на 11.08.2026 — далі вікно продовжується
    # даними з власного трекера падінь залишку (get_sold_qty_since_blended),
    # тому реальна межа даних — сьогодні
    meta = {"period_start": f"останні {window_days} дн.", "period_end": date.today().isoformat()}
    return alerts, meta


def fetch_low_stock_recent_1c(conn, min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD):
    """Найточніший рівень — дельта між двома знімками 1С. (None, None),
    якщо ще нема другого знімка."""
    sold_by_pw, meta = sales_1c.load_recent_sold_qty_by_pharmacy(min_sold=min_sold)
    if meta is None:
        return None, None
    stock_rows = _fetch_current_stock(conn)
    alerts = _build_alerts(stock_rows, sold_by_pw, meta["days_between"], days_threshold)
    return alerts, meta


def fetch_low_stock_from_1c(conn, min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD):
    """Грубе середнє за весь період вигрузки — див. застереження в
    docstring модуля про неточність для сезонних товарів."""
    sold_by_pw, meta = sales_1c.load_sold_qty_by_pharmacy(min_sold=min_sold)
    if meta is None:
        return None, None

    d1 = datetime.strptime(meta["period_start"], "%d.%m.%Y %H:%M:%S")
    d2 = datetime.strptime(meta["period_end"], "%d.%m.%Y %H:%M:%S")
    days_in_period = max((d2 - d1).days, 1)

    stock_rows = _fetch_current_stock(conn)
    alerts = _build_alerts(stock_rows, sold_by_pw, days_in_period, days_threshold)
    return alerts, meta


def fetch_low_stock_from_stock_drops(conn, min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD):
    if not STOCK_HISTORY_DB_PATH.exists():
        return None, None

    hist = sqlite3.connect(STOCK_HISTORY_DB_PATH)
    try:
        first_seen = hist.execute("SELECT MIN(updated_at) FROM current_state").fetchone()[0]
        rows = hist.execute(
            "SELECT product_id, warehouse_id, SUM(drop_amount) FROM stock_drops "
            "GROUP BY product_id, warehouse_id"
        ).fetchall()
    finally:
        hist.close()

    if not rows or first_seen is None:
        return None, None

    days_tracked = max((datetime.utcnow() - datetime.fromisoformat(first_seen)).days, 1)
    sold_by_pw = {(pid, wid): qty for pid, wid, qty in rows if qty >= min_sold}
    if not sold_by_pw:
        return None, None

    stock_rows = _fetch_current_stock(conn)
    alerts = _build_alerts(stock_rows, sold_by_pw, days_tracked, days_threshold)
    meta = {"period_start": first_seen, "period_end": "зараз"}
    return alerts, meta


def fetch_low_stock(conn, min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD):
    """Диспетчер: daily (реальна поденна історія) → recent_1c (дельта) →
    1c (грубе середнє) → stock_drops → недоступно.
    Повертає (alerts, data_source, meta)."""
    alerts, meta = fetch_low_stock_from_daily(conn, min_sold=min_sold, days_threshold=days_threshold)
    if alerts is not None:
        return alerts, "daily", meta

    alerts, meta = fetch_low_stock_recent_1c(conn, min_sold=min_sold, days_threshold=days_threshold)
    if alerts is not None:
        return alerts, "recent_1c", meta

    alerts, meta = fetch_low_stock_from_1c(conn, min_sold=min_sold, days_threshold=days_threshold)
    if alerts is not None:
        return alerts, "1c", meta

    alerts, meta = fetch_low_stock_from_stock_drops(conn, min_sold=min_sold, days_threshold=days_threshold)
    if alerts is not None:
        return alerts, "stock_drops", meta

    return [], "unavailable", None


@functools.lru_cache(maxsize=8)
def get_data(min_sold=MIN_SOLD_TOTAL, days_threshold=DAYS_THRESHOLD):
    """Кешується на рівні процесу — те саме обґрунтування, що й
    defectura.get_data_per_pharmacy() (2026-08-11)."""
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        alerts, data_source, meta = fetch_low_stock(
            conn, min_sold=min_sold, days_threshold=days_threshold
        )
    finally:
        conn.close()
    return {
        "alerts": alerts,
        "data_source": data_source,
        "meta": meta,
        "days_threshold": days_threshold,
    }


def render_section(data=None):
    if data is None:
        data = get_data()

    lines = []
    lines.append(f"⏳ СКОРО ЗАКІНЧАТЬСЯ (менше {data['days_threshold']} дн. запасу)")
    lines.append("")
    if data["data_source"] == "daily":
        m = data["meta"]
        lines.append(f"✅ Реальна поденна історія, швидкість за {m['period_start']} (дані по {m['period_end']})")
    elif data["data_source"] == "recent_1c":
        m = data["meta"]
        lines.append(f"✅ Свіжа швидкість продажу (1С, дельта за {m['days_between']} дн.)")
    elif data["data_source"] == "1c":
        lines.append(
            f"⚠️ Середнє з {data['meta']['period_start']} — може бути неточним "
            f"для сезонних товарів (ще нема другого знімка 1С для реальної дельти)"
        )
    elif data["data_source"] == "stock_drops":
        lines.append(f"🟡 Власний трекер падінь залишку (1С не знайдено), з {data['meta']['period_start']}")
    else:
        lines.append("⚠️ Недостатньо даних для прогнозу")
    lines.append("")
    lines.append(f"Знайдено: {len(data['alerts'])}")
    lines.append("")
    for a in data["alerts"]:
        model = a["model"] or f"id{a['product_id']}"
        seasonal_note = " 🌦" if a.get("seasonal_adjusted") else ""
        lines.append(
            f"• {a['product_name']} ({model}) — {a['warehouse_title']}: "
            f"залишок {a['quantity']:g} шт, ~{a['daily_rate']:.1f} шт/день, "
            f"лишилось ~{a['days_left']:.1f} дн.{seasonal_note}"
        )
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Товари, що скоро закінчаться")
    parser.add_argument("--days", type=int, default=DAYS_THRESHOLD, help="поріг днів запасу")
    parser.add_argument("--min-sold", type=int, default=MIN_SOLD_TOTAL)
    args = parser.parse_args()

    data = get_data(min_sold=args.min_sold, days_threshold=args.days)
    print(render_section(data))


if __name__ == "__main__":
    main()

```

---

## 12. redistribution.py — перерозподіл і мертвий вантаж

`scripts/redistribution.py`

Без класів. `DEAD_STOCK_DAYS = 60` (з коментарем "⚠️ ЗМІНЕНО 2026-08-12,
було 30" — тобто значення в коді прямо документує історію зміни бізнес-правила),
`MIN_DEAD_QUANTITY` — поріг кількості, нижче якого залишок не вважається
"мертвим вантажем" навіть якщо не продавався. `fetch_redistribution(conn,
sales_window_days=...)` бере дефектуру з `defectura.fetch_defectura_per_pharmacy`
(імпорт з іншого модуля, не дублювання логіки) і зіставляє з наявністю в інших
аптеках. `_demand_stability_map(needs)` рахує додаткову метрику стабільності
попиту прямо з переданого списку потреб. Мертвий вантаж повторює той самий
чотириступеневий fallback-патерн, що й `defectura.py` (`fetch_dead_stock_from_daily/
_1c/_stock_drops/network_proxy`), і `_exclude_medical_supplies` прибирає з
результату категорію "Вироби медичного призначення" через `product_categories`.

```python
#!/usr/bin/env python3
"""Рекомендації по залишках: перерозподіл між аптеками + мертвий вантаж.

Той самий read-only доступ до OpenCart DB, що й defectura.py/opencart_sales.py.

1. Перерозподіл: товар з нульовим залишком в одній аптеці (дефектура,
   див. defectura.fetch_defectura_per_pharmacy), який Є на складі в іншій
   аптеці — підказка "звідки везти". Не враховує логістику/відстань між
   аптеками — тільки факт "десь є, десь нема".

2. Мертвий вантаж (= "неліквід"): товар лежить (quantity >= MIN_DEAD_QUANTITY)
   в якійсь аптеці, але РЕАЛЬНО не продавався САМЕ ТУТ за останні
   DEAD_STOCK_DAYS днів. Чотириступеневий fallback, той самий що й в
   defectura.py: `daily` (sales_daily.py, rolling-вікно) → 1С (sales_1c.py,
   весь період вигрузки — статичний, гірше відрізняє "давно затихло" від
   "стабільно продається") → stock_drops (власний трекер падінь, з
   2026-08-04) → мережевий oc_order-проксі (найслабший — зашумлений
   витратниками: шприци/рукавички/картки постійно хибно потрапляли в
   "мертві", бо ніколи не йшли через сайтове замовлення).

   DEAD_STOCK_DAYS=60 (⚠️ ЗМІНЕНО 2026-08-12, було 30) реалізує правило
   користувача: неліквід = 0 продажів за останні 60 днів. На `daily`-рівні
   це genuine rolling-вікно — рахується від "сьогодні" щоразу заново, тож
   саме зсувається на день вперед з кожним новим запуском без жодних змін
   коду (це і є "неліквід", а не статична перевірка за фіксований період).
"""
import functools
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import sales_1c
import sales_daily
from defectura import RATE_WINDOW_DAYS, fetch_defectura_per_pharmacy
from opencart_sales import VALID_ORDER_FILTER, connect, read_env
from product_categories import fetch_medical_supplies_product_ids

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
STOCK_HISTORY_DB_PATH = CONNECTORS_DIR / "opencart" / "stock_history.db"

SALES_WINDOW_DAYS = 30
DEAD_STOCK_DAYS = 60  # "неліквід" = 0 продажів за останні 60 днів (правило користувача, 2026-08-12)
MIN_DEAD_QUANTITY = 1  # знижено з 3 (2026-08-12): звірка з реальним 1С-звітом
# "Рух товару" по Аптеці №13 показала, що поріг >=3 ховав 95% реального
# неліквіду (685 з 714 позицій, 245929 з 257635 грн мали 0.5-2 шт —
# дрібні по одній, але велика сума в сумі)
MIN_DONOR_QUANTITY = 2  # донор має лишити собі хоч 1 шт після передачі
MIN_DONOR_RESERVE_DAYS = 7  # донор лишає собі стільки днів ВЛАСНОГО споживання,
# перш ніж решта пропонується як надлишок на перенесення — запит
# користувача 2026-08-12: "щоб агент враховував мінімальний залишок,
# який забрати не можна". Рахується на власній швидкості продажу донора
# ЦЬОГО товару (RATE_WINDOW_DAYS-вікно, той самий що й в defectura.py).
STABILITY_WINDOW_DAYS = 30
STABILITY_N_WINDOWS = 6  # той самий критерій "первинного асортименту"
# (2026-08-12): у скількох з останніх N 30-денних вікон товар продавався
# САМЕ В ЦІЙ аптеці — 6/6 = стабільний постійний попит, 1/6 = разовий
# випадковий продаж. Перерозподіл сортується за цим, а не за розміром
# надлишку в донора — щоб пріоритет мали аптеки, де товар РЕАЛЬНО
# постійно потрібен (запит користувача: "направляти в ту аптеку де він
# постійно продається а його там нема").


def _demand_stability_map(needs):
    """{(product_id, warehouse_id): к-ть з останніх STABILITY_N_WINDOWS
    30-денних вікон, де товар продавався САМЕ ТУТ}. 6 запитів на всю
    мережу разом (не по кожній парі окремо) — дешево навіть для тисяч
    позицій дефектури."""
    if not sales_daily.has_data():
        return {}

    today = date.today()
    windows_sold = []
    for i in range(STABILITY_N_WINDOWS):
        end = today - timedelta(days=i * STABILITY_WINDOW_DAYS)
        start = end - timedelta(days=STABILITY_WINDOW_DAYS - 1)
        windows_sold.append(sales_daily.get_sold_qty_by_pw_in_range(start, end))

    keys = {(n["product_id"], n["warehouse_id"]) for n in needs}
    return {
        key: sum(1 for w in windows_sold if w.get(key, 0) > 0)
        for key in keys
    }


def fetch_redistribution(conn, sales_window_days=SALES_WINDOW_DAYS):
    """Для кожної позиції дефектури (аптека X, товар з quantity=0) шукає
    аптеки-донори — де цей же товар є в наявності з НАДЛИШКОМ (quantity
    мінус MIN_DONOR_RESERVE_DAYS днів власного споживання донора >=
    MIN_DONOR_QUANTITY), відсортовані за надлишком спадаюче (найбільший
    надлишок — найкращий донор). donors[i]["quantity"] — це вже НАДЛИШОК
    понад власний резерв донора, НЕ повний фізичний залишок на складі
    (запит користувача 2026-08-12: "щоб агент враховував мінімальний
    залишок, який забрати не можна").

    Повертає (список записів {product_name, model, product_id, needs_at
    (label аптеки з дефіцитом), donors: [{label, quantity (=надлишок),
    own_reserve}, ...], demand_stability}, data_source, meta). Пропускає
    позиції, для яких донорів немає взагалі (реальна мережева дефектура
    — нема де взяти, тільки замовляти у постачальника).

    Список сортується за demand_stability (0-STABILITY_N_WINDOWS, скільки
    з останніх 30-денних вікон товар продавався САМЕ В АПТЕЦІ, ЩО
    ПОТРЕБУЄ) спадаюче, НЕ за розміром надлишку в донора — пріоритет
    мають передачі туди, де товар постійно й надійно продається, а не
    просто там, де випадково є найбільший запас у когось іншого (запит
    користувача 2026-08-12).
    """
    by_pharmacy, data_source, meta = fetch_defectura_per_pharmacy(
        conn, sales_window_days=sales_window_days
    )

    needs = []
    for wid, entry in by_pharmacy.items():
        for item in entry["items"]:
            needs.append({
                "warehouse_id": wid,
                "needs_at": entry["label"],
                "product_id": item["product_id"],
                "model": item["model"],
                "product_name": item["product_name"],
                "sold_qty": item["sold_qty"],
                "recent_sold_qty": item.get("recent_sold_qty"),
                "price": item.get("price"),
                "est_daily_loss": item.get("est_daily_loss"),
            })

    if not needs:
        return [], data_source, meta

    product_ids = sorted({n["product_id"] for n in needs})
    placeholders = ",".join(["%s"] * len(product_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT pw.product_id, pw.warehouse_id, pw.quantity, wd.title AS warehouse_title
            FROM product_warehouse pw
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.product_id IN ({placeholders}) AND pw.quantity >= %s
            """,
            product_ids + [MIN_DONOR_QUANTITY],
        )
        stock_rows = cur.fetchall()

    # Донор має лишити собі запас на MIN_DONOR_RESERVE_DAYS ВЛАСНОГО
    # споживання цього товару — пропонуємо лише надлишок понад цей резерв,
    # не весь фізичний залишок. Якщо sales_daily ще порожня, own_sold_by_pw
    # порожній і reserve=0 (поводиться як раніше — без регресії).
    own_sold_by_pw = (
        sales_daily.get_sold_qty_since_blended(days_back=RATE_WINDOW_DAYS, min_sold=0)
        if sales_daily.has_data() else {}
    )

    donors_by_product = {}
    for row in stock_rows:
        key = (row["product_id"], row["warehouse_id"])
        own_daily_rate = own_sold_by_pw.get(key, 0) / RATE_WINDOW_DAYS
        reserve = own_daily_rate * MIN_DONOR_RESERVE_DAYS
        surplus = row["quantity"] - reserve
        if surplus < MIN_DONOR_QUANTITY:
            continue
        donors_by_product.setdefault(row["product_id"], []).append({
            "label": row["warehouse_title"] or f"Склад {row['warehouse_id']}",
            "quantity": round(surplus, 1),
            "own_reserve": round(reserve, 1),
        })
    for donors in donors_by_product.values():
        donors.sort(key=lambda d: d["quantity"], reverse=True)

    stability_map = _demand_stability_map(needs)

    results = []
    for n in needs:
        donors = donors_by_product.get(n["product_id"])
        if not donors:
            continue
        stability = stability_map.get((n["product_id"], n["warehouse_id"]))
        results.append({**n, "donors": donors, "demand_stability": stability})

    # спочатку стабільність попиту в аптеці, що потребує (6/6 — постійний
    # товар, найвищий пріоритет), сирий обсяг продажу — лише тайбрейк
    results.sort(key=lambda r: (-(r["demand_stability"] or 0), -r["sold_qty"]))
    return results, data_source, meta


def fetch_dead_stock_from_daily(conn, dead_stock_days=DEAD_STOCK_DAYS, min_quantity=MIN_DEAD_QUANTITY):
    """Найкращий рівень — реальна поденна історія. Товар лежить
    (quantity >= min_quantity), але 0 продажів САМЕ ТУТ за останні
    dead_stock_days днів (rolling-вікно, не статичний період — реалізує
    правило користувача "60 днів без руху -> неліквід"). Повертає
    (rows, meta) або (None, None), якщо sales_daily.db ще порожня.
    """
    if not sales_daily.has_data():
        return None, None

    # min_sold=0 (не 1!) — 1С визначає неліквід як "Кількість витрат
    # РІВНО 0", тобто БУДЬ-ЯКИЙ рух (навіть 0.4 шт — продаж частини
    # упаковки) виключає товар зі списку. min_sold=1 хибно прирівнював
    # "продано <1 шт" до "продано 0" (звірка з реальним 1С-звітом
    # користувача, 2026-08-12: пояснювало 14-29% хибних позицій).
    sold_by_pw = sales_daily.get_sold_qty_since_blended(days_back=dead_stock_days, min_sold=0)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   pw.quantity, p.model, pw.price, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity >= %s AND pd.name NOT LIKE 'КАРТКА%%'
        """, (min_quantity,))
        candidates = cur.fetchall()

    dead = [
        row for row in candidates
        if (row["product_id"], row["warehouse_id"]) not in sold_by_pw
    ]
    for row in dead:
        price = float(row["price"]) if row["price"] is not None else 0.0
        row["price"] = price
        row["value"] = float(row["quantity"]) * price
    dead.sort(key=lambda r: -r["quantity"])

    # 1С-вигрузка заморожена на 11.08.2026 — далі вікно продовжується
    # даними з власного трекера падінь залишку (get_sold_qty_since_blended),
    # тому реальна межа даних — сьогодні
    meta = {
        "period_start": f"останні {dead_stock_days} дн.",
        "period_end": date.today().isoformat(),
    }
    return dead, meta


def fetch_dead_stock_from_1c(conn, min_quantity=MIN_DEAD_QUANTITY):
    """Товари, які лежать (quantity >= min_quantity) в конкретній аптеці,
    але РЕАЛЬНО (з 1С) там не продавались за весь період вигрузки —
    ані разу. Повертає (rows, meta) або (None, None), якщо файл 1С не
    знайдено — виклик відповідає за fallback.
    """
    sold_by_pw, meta = sales_1c.load_sold_qty_by_pharmacy(min_sold=0)
    if meta is None:
        return None, None

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   pw.quantity, p.model, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity >= %s AND pd.name NOT LIKE 'КАРТКА%%'
        """, (min_quantity,))
        candidates = cur.fetchall()

    dead = [
        row for row in candidates
        if (row["product_id"], row["warehouse_id"]) not in sold_by_pw
    ]
    dead.sort(key=lambda r: -r["quantity"])
    return dead, meta


def fetch_dead_stock_from_stock_drops(conn, min_quantity=MIN_DEAD_QUANTITY):
    """Середній fallback: товар лежить (quantity >= min_quantity), але
    (product_id, warehouse_id) НІКОЛИ не з'являвся в stock_drops (жодного
    падіння з моменту, коли почали трекати). Коротша історія й слабший
    сигнал за 1С (може пропустити щось, якщо трекер стартував пізніше
    завезення товару), але значно краще за мережевий проксі.
    """
    if not STOCK_HISTORY_DB_PATH.exists():
        return None, None

    hist = sqlite3.connect(STOCK_HISTORY_DB_PATH)
    try:
        first_seen = hist.execute("SELECT MIN(updated_at) FROM current_state").fetchone()[0]
        drop_pairs = set(
            hist.execute("SELECT DISTINCT product_id, warehouse_id FROM stock_drops").fetchall()
        )
    finally:
        hist.close()

    if first_seen is None:
        return None, None

    with conn.cursor() as cur:
        cur.execute("""
            SELECT pw.product_id, pw.warehouse_id, wd.title AS warehouse_title,
                   pw.quantity, p.model, pd.name AS product_name
            FROM product_warehouse pw
            JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
            JOIN oc_product_description pd
                ON pd.product_id = p.product_id AND pd.language_id = 3
            LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
            WHERE pw.quantity >= %s AND pd.name NOT LIKE 'КАРТКА%%'
        """, (min_quantity,))
        candidates = cur.fetchall()

    dead = [
        row for row in candidates
        if (row["product_id"], row["warehouse_id"]) not in drop_pairs
    ]
    dead.sort(key=lambda r: -r["quantity"])
    meta = {"period_start": first_seen, "period_end": "зараз"}
    return dead, meta


def fetch_dead_stock_network_proxy(conn, dead_stock_days=DEAD_STOCK_DAYS, min_quantity=MIN_DEAD_QUANTITY):
    """Старий fallback (мережевий проксі) — тільки якщо файл 1С ще не
    залитий. Зашумлений витратниками (шприци/рукавички/картки) — див.
    docstring модуля."""
    since = date.today() - timedelta(days=dead_stock_days)
    query = f"""
        SELECT
            pw.product_id,
            pw.warehouse_id,
            wd.title AS warehouse_title,
            pw.quantity,
            p.model,
            pd.name AS product_name
        FROM product_warehouse pw
        JOIN oc_product p ON p.product_id = pw.product_id AND p.status = 1
        JOIN oc_product_description pd
            ON pd.product_id = p.product_id AND pd.language_id = 3
        LEFT JOIN oc_warehouses_description wd ON wd.warehouses_id = pw.warehouse_id
        LEFT JOIN (
            SELECT DISTINCT op.product_id
            FROM oc_order_product op
            JOIN oc_order o ON o.order_id = op.order_id
            WHERE DATE(o.date_added) >= %s AND {VALID_ORDER_FILTER}
        ) recent ON recent.product_id = pw.product_id
        WHERE pw.quantity >= %s AND recent.product_id IS NULL AND pd.name NOT LIKE 'КАРТКА%%'
        ORDER BY pw.quantity DESC
    """
    with conn.cursor() as cur:
        cur.execute(query, (since, min_quantity))
        return cur.fetchall()


# Резервний фільтр за назвою — для товарів без категорії в OpenCart, куди
# fetch_medical_supplies_product_ids не дотягується (напр. "МАСКА МЕДИЧНА
# ...зелена" не категоризована, хоча однотипна "...блакитна" — так). НЕ
# використовувати голе "МАСКА" — серед товарів є реальна косметика (маски
# для волосся/обличчя Phyto Color, Альгінатна тощо), яка має лишатись
# видимою, якщо вона реально неліквід.
UNCATEGORIZED_CONSUMABLE_PREFIXES = ("ПАКЕТ", "РУКАВИЦІ", "МАСКА МЕДИЧНА")


def _exclude_medical_supplies(conn, rows):
    """Прибирає витратники (шприци/маски/бахіли/серветки/пакети/рукавички —
    див. docstring fetch_medical_supplies_product_ids) з мертвого вантажу
    незалежно від того, який fallback-рівень спрацював (правило
    користувача 2026-08-11)."""
    excluded_ids = fetch_medical_supplies_product_ids(conn)
    return [
        row for row in rows
        if row["product_id"] not in excluded_ids
        and not row["product_name"].strip().startswith(UNCATEGORIZED_CONSUMABLE_PREFIXES)
    ]


def fetch_dead_stock(conn, dead_stock_days=DEAD_STOCK_DAYS, min_quantity=MIN_DEAD_QUANTITY):
    """Диспетчер: daily → 1С → stock_drops → мережевий проксі.
    Повертає (rows, data_source, meta)."""
    rows, meta = fetch_dead_stock_from_daily(conn, dead_stock_days=dead_stock_days, min_quantity=min_quantity)
    if rows is not None:
        return _exclude_medical_supplies(conn, rows), "daily", meta

    rows, meta = fetch_dead_stock_from_1c(conn, min_quantity=min_quantity)
    if rows is not None:
        return _exclude_medical_supplies(conn, rows), "1c", meta

    rows, meta = fetch_dead_stock_from_stock_drops(conn, min_quantity=min_quantity)
    if rows is not None:
        return _exclude_medical_supplies(conn, rows), "stock_drops", meta

    rows = fetch_dead_stock_network_proxy(
        conn, dead_stock_days=dead_stock_days, min_quantity=min_quantity
    )
    rows = _exclude_medical_supplies(conn, rows)
    return rows, "network_proxy", None


@functools.lru_cache(maxsize=8)
def get_data(sales_window_days=SALES_WINDOW_DAYS, dead_stock_days=DEAD_STOCK_DAYS,
             min_dead_quantity=MIN_DEAD_QUANTITY):
    """Кешується на рівні процесу — те саме обґрунтування, що й
    defectura.get_data_per_pharmacy() (2026-08-11)."""
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        redistribution, redistribution_source, redistribution_meta = fetch_redistribution(
            conn, sales_window_days=sales_window_days
        )
        dead_stock, dead_stock_source, dead_stock_meta = fetch_dead_stock(
            conn, dead_stock_days=dead_stock_days, min_quantity=min_dead_quantity
        )
    finally:
        conn.close()
    # гривневий еквівалент заморожений в неліквіді — тільки для daily-рівня
    # (тільки там ціна порахована при вибірці, див. fetch_dead_stock_from_daily)
    dead_stock_total_value = (
        sum(row.get("value", 0.0) for row in dead_stock) if dead_stock_source == "daily" else None
    )
    return {
        "sales_window_days": sales_window_days,
        "dead_stock_days": dead_stock_days,
        "redistribution": redistribution,
        "redistribution_source": redistribution_source,
        "redistribution_meta": redistribution_meta,
        "dead_stock": dead_stock,
        "dead_stock_source": dead_stock_source,
        "dead_stock_meta": dead_stock_meta,
        "dead_stock_total_value": dead_stock_total_value,
    }


def render_redistribution(data):
    lines = []
    lines.append("🔄 ПЕРЕРОЗПОДІЛ МІЖ АПТЕКАМИ")
    lines.append("")
    if data["redistribution_source"] == "daily":
        meta = data["redistribution_meta"]
        lines.append(
            f"✅ 'Потрібно' — реальна поденна історія САМЕ В ЦІЙ аптеці "
            f"({meta['period_start']}, дані по {meta['period_end']}). "
            f"'Є на складі' — реальний залишок зараз."
        )
    elif data["redistribution_source"] == "1c":
        meta = data["redistribution_meta"]
        lines.append(
            f"✅ 'Потрібно' — реальні продажі САМЕ В ЦІЙ аптеці "
            f"(1С, період {meta['period_start']} — {meta['period_end']}). "
            f"'Є на складі' — реальний залишок зараз."
        )
    elif data["redistribution_source"] == "stock_drops":
        meta = data["redistribution_meta"]
        lines.append(
            f"🟡 'Потрібно' — власний трекер падінь залишку САМЕ В ЦІЙ аптеці "
            f"(з {meta['period_start']}, файл 1С не знайдено). "
            f"'Є на складі' — реальний залишок зараз."
        )
    else:
        lines.append(
            f"⚠️ 'Потрібно' — продається десь у мережі за останні "
            f"{data['sales_window_days']} дн., не обов'язково саме в цій аптеці "
            f"(ні 1С, ні трекер падінь недоступні). 'Є на складі' — реальний залишок зараз."
        )
    lines.append("")
    if not data["redistribution"]:
        lines.append("(немає позицій із донорами)")
    for r in data["redistribution"]:
        model = r["model"] or f"id{r['product_id']}"
        lines.append(f"• {r['product_name']} ({model})")
        lines.append(f"   Немає в: {r['needs_at']} (продано {r['sold_qty']:g} шт)")
        donors_str = ", ".join(f"{d['label']} ({d['quantity']:g} шт)" for d in r["donors"][:5])
        lines.append(f"   Є в: {donors_str}")
        lines.append("")
    return "\n".join(lines)


def render_dead_stock(data):
    lines = []
    lines.append("🧊 НЕЛІКВІДИ (лежить, реально не продається САМЕ ТУТ)")
    lines.append("")
    if data["dead_stock_source"] == "daily":
        meta = data["dead_stock_meta"]
        lines.append(
            f"✅ Реальна поденна історія, {meta['period_start']} (дані по {meta['period_end']}). "
            f"Товари з quantity ≥ {MIN_DEAD_QUANTITY}, 0 продажів в ЦІЙ аптеці за цей час — "
            f"це і є 'неліквід'."
        )
    elif data["dead_stock_source"] == "1c":
        meta = data["dead_stock_meta"]
        lines.append(
            f"✅ Реальні дані з 1С, період: {meta['period_start']} — {meta['period_end']}. "
            f"Товари з quantity ≥ {MIN_DEAD_QUANTITY}, 0 продажів в ЦІЙ аптеці за весь період."
        )
    elif data["dead_stock_source"] == "stock_drops":
        meta = data["dead_stock_meta"]
        lines.append(
            f"🟡 Файл 1С не знайдено — власний трекер падінь залишку (з {meta['period_start']}). "
            f"Товари з quantity ≥ {MIN_DEAD_QUANTITY}, жодного падіння в ЦІЙ аптеці за цей час."
        )
    else:
        lines.append(
            f"⚠️ Ні 1С, ні трекер падінь недоступні — мережевий проксі, зашумлений витратниками. "
            f"Товари з quantity ≥ {MIN_DEAD_QUANTITY}, 0 продажів по всій мережі "
            f"за останні {data['dead_stock_days']} дн."
        )
    lines.append("")
    if not data["dead_stock"]:
        lines.append("(не знайдено)")
    for row in data["dead_stock"]:
        model = row["model"] or f"id{row['product_id']}"
        label = row["warehouse_title"] or f"Склад {row['warehouse_id']}"
        lines.append(f"• {row['product_name']} ({model}) — {label}: {row['quantity']:g} шт")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Рекомендації по залишках")
    parser.add_argument("--mode", choices=["redistribution", "dead-stock", "both"], default="both")
    parser.add_argument("--days", type=int, default=SALES_WINDOW_DAYS)
    parser.add_argument("--dead-days", type=int, default=DEAD_STOCK_DAYS)
    args = parser.parse_args()

    data = get_data(sales_window_days=args.days, dead_stock_days=args.dead_days)

    if args.mode in ("redistribution", "both"):
        print(render_redistribution(data))
    if args.mode in ("dead-stock", "both"):
        print(render_dead_stock(data))


if __name__ == "__main__":
    main()

```

---

## 13. seasonality.py — прогноз сезонного попиту

`scripts/seasonality.py`

Без класів. `_reference_windows()` обчислює дві пари дат: "ті самі 30 днів
торік" і "наступні 30 днів торік" — арифметика на `datetime.date`/`timedelta`
відносно `date.today()`. `_fetch_current_network_stock(conn, product_ids)`
дістає поточну наявність по мережі для фільтрації (сезонний товар, якого вже
немає в наявності, не показується як "замовити"). `fetch_seasonality(conn)`
зводить продажі за обидва вікна через `sales_daily.get_sold_qty_by_product_in_range`
(імпортовано з `sales_daily.py`) і категорії — через `product_categories.get_category_map()`,
рахуючи приріст `next_year_qty / this_year_qty` по категоріях та товарах усередині них.

```python
#!/usr/bin/env python3
"""Сезонність: категорії, що історично мають стартувати сезонний ріст
НАЙБЛИЖЧИМ часом, + топ товари всередині них.

Forward-looking логіка: порівнюємо ТОРІШНІ ті самі 30 днів "зараз" і
ТОРІШНІ НАСТУПНІ 30 днів (обидва вже в минулому, бо це торік) — якщо
тоді продажі категорії зросли, це сигнал "скоро підйом" і цього року
теж (сезонність повторюється рік у рік: застуда/грип восени, алергія
навесні, вітаміни взимку). Це не "поточний тренд", а прогноз на основі
торішнього патерну — саме так можна "підказати, що і коли замовляти"
ДО того, як дефектура вже настала.

Потребує в sales_daily.db історію, що покриває обидва торішні вікна
(мінімум ~13 місяців тому) — інакше секція просто не показується
(data_source=None), без вигаданих цифр.
"""
import functools
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import sales_daily
from opencart_sales import connect, read_env
from product_categories import get_category_map

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"

WINDOW_DAYS = 30
MIN_CATEGORY_QTY = 50  # мінімум продано в категорії за торішнє "поточне" вікно — відсіює шум малих категорій
MIN_GROWTH_PCT = 20  # показувати категорії з очікуваним ростом від цього %
TOP_CATEGORIES = 5
TOP_PRODUCTS_PER_CATEGORY = 5


def _reference_windows():
    today = date.today()
    last_year_current_end = today - timedelta(days=365)
    last_year_current_start = last_year_current_end - timedelta(days=WINDOW_DAYS - 1)
    last_year_next_start = last_year_current_end + timedelta(days=1)
    last_year_next_end = last_year_next_start + timedelta(days=WINDOW_DAYS - 1)
    return {
        "current": (last_year_current_start, last_year_current_end),
        "next": (last_year_next_start, last_year_next_end),
    }


def _fetch_current_network_stock(conn, product_ids):
    if not product_ids:
        return {}
    placeholders = ",".join(["%s"] * len(product_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT product_id, SUM(quantity) AS qty FROM product_warehouse "
            f"WHERE product_id IN ({placeholders}) GROUP BY product_id",
            list(product_ids),
        )
        return {row["product_id"]: row["qty"] or 0 for row in cur.fetchall()}


def fetch_seasonality(conn):
    """Повертає (categories, meta) або (None, None), якщо в sales_daily
    ще нема достатньо історії (обидва торішні вікна мають бути покриті)."""
    windows = _reference_windows()
    cov = sales_daily.get_coverage()
    if cov["min_date"] is None or windows["current"][0].isoformat() < cov["min_date"]:
        return None, None

    current_by_product = sales_daily.get_sold_qty_by_product_in_range(*windows["current"])
    next_by_product = sales_daily.get_sold_qty_by_product_in_range(*windows["next"])

    cat_map = get_category_map()

    cat_current = defaultdict(float)
    cat_next = defaultdict(float)
    cat_products = defaultdict(dict)  # category -> {product_id: {"current": x, "next": y}}

    all_products = set(current_by_product) | set(next_by_product)
    for pid in all_products:
        cat = cat_map.get(pid, "Без категорії")
        cur_qty = current_by_product.get(pid, 0.0)
        next_qty = next_by_product.get(pid, 0.0)
        cat_current[cat] += cur_qty
        cat_next[cat] += next_qty
        cat_products[cat][pid] = {"current": cur_qty, "next": next_qty}

    candidates = []
    for cat, cur_qty in cat_current.items():
        if cur_qty < MIN_CATEGORY_QTY:
            continue
        next_qty = cat_next.get(cat, 0.0)
        growth_pct = (next_qty - cur_qty) / cur_qty * 100
        if growth_pct < MIN_GROWTH_PCT:
            continue
        candidates.append({
            "name": cat,
            "last_year_current_qty": cur_qty,
            "last_year_next_qty": next_qty,
            "growth_pct": growth_pct,
            "product_ids": cat_products[cat],
        })

    candidates.sort(key=lambda c: -c["growth_pct"])
    top_categories = candidates[:TOP_CATEGORIES]

    # деталі по товарах — тільки для топ-категорій, з реальними назвами/моделями/залишком
    product_ids_needed = set()
    for cat in top_categories:
        top_products = sorted(
            cat["product_ids"].items(), key=lambda kv: -kv[1]["next"]
        )[:TOP_PRODUCTS_PER_CATEGORY]
        cat["_top_product_ids"] = [pid for pid, _ in top_products]
        product_ids_needed.update(cat["_top_product_ids"])

    if product_ids_needed:
        placeholders = ",".join(["%s"] * len(product_ids_needed))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT p.product_id, p.model, pd.name AS product_name
                FROM oc_product p
                JOIN oc_product_description pd
                    ON pd.product_id = p.product_id AND pd.language_id = 3
                WHERE p.product_id IN ({placeholders})
                """,
                list(product_ids_needed),
            )
            product_info = {row["product_id"]: row for row in cur.fetchall()}
        stock_by_product = _fetch_current_network_stock(conn, product_ids_needed)
    else:
        product_info = {}
        stock_by_product = {}

    for cat in top_categories:
        products = []
        for pid in cat.pop("_top_product_ids"):
            info = cat["product_ids"][pid]
            meta = product_info.get(pid)
            if meta is None:
                continue
            current_stock = stock_by_product.get(pid, 0.0)
            forecast_daily_rate = info["next"] / WINDOW_DAYS
            days_of_stock = (current_stock / forecast_daily_rate) if forecast_daily_rate > 0 else None
            growth_pct = (
                (info["next"] - info["current"]) / info["current"] * 100
                if info["current"] > 0 else None
            )
            products.append({
                "product_id": pid,
                "model": meta["model"],
                "product_name": meta["product_name"],
                "last_year_current_qty": info["current"],
                "last_year_next_qty": info["next"],
                "growth_pct": growth_pct,
                "current_stock": current_stock,
                "days_of_stock": days_of_stock,
            })
        cat["products"] = products
        del cat["product_ids"]

    meta = {"windows": windows, "window_days": WINDOW_DAYS}
    return top_categories, meta


@functools.lru_cache(maxsize=4)
def get_data():
    env = read_env(ENV_PATH)
    conn = connect(env)
    try:
        categories, meta = fetch_seasonality(conn)
    finally:
        conn.close()
    return {
        "data_source": "daily" if categories is not None else None,
        "categories": categories or [],
        "meta": meta,
    }


def render_section(data=None):
    if data is None:
        data = get_data()

    lines = []
    lines.append("🌦 СЕЗОННІСТЬ (прогноз на основі торішнього періоду)")
    lines.append("")
    if data["data_source"] is None:
        lines.append("⚠️ Недостатньо історії (потрібно ще ~13 міс. накопичених даних)")
        return "\n".join(lines)

    if not data["categories"]:
        lines.append("(категорій з очікуваним сезонним ростом не знайдено)")
        return "\n".join(lines)

    for cat in data["categories"]:
        lines.append(
            f"📈 {cat['name']}: торік за наступні {WINDOW_DAYS} дн. продажі зросли на "
            f"+{cat['growth_pct']:.0f}% ({cat['last_year_current_qty']:g} → {cat['last_year_next_qty']:g} шт)"
        )
        for p in cat["products"]:
            model = p["model"] or f"id{p['product_id']}"
            days_str = f"{p['days_of_stock']:.0f} дн." if p["days_of_stock"] is not None else "н/д"
            lines.append(
                f"   • {p['product_name']} ({model}) — торік попит зріс до "
                f"{p['last_year_next_qty']:g} шт/{WINDOW_DAYS}дн., зараз на складі мережі "
                f"{p['current_stock']:g} шт (~{days_str} при очікуваному темпі)"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    print(render_section())


if __name__ == "__main__":
    main()

```

---

## 14. refusals.py — аналіз відмов покупцям

`scripts/refusals.py`

Без класів. `norm_filial(s)` — своя нормалізація назв філій (окрема від тієї,
що в `sales_daily.py`, бо формат джерела інший). `open_db()` створює SQLite-базу
з власною схемою (без зіставлення з `oc_product` — товар зберігається як сира
назва). `ingest_file`/`match_filial` (вкладена функція) розбирають вхідний
Excel-файл із колонками "Дата, Аптека, Товар, Менеджер, Причина відмови,
Кількість, Ціна зам, Ціна роздр, Ціна прайс" — назви колонок узяті прямо з
докстрінгу опису формату джерела. `get_summary(top_n_products=10,
top_n_pharmacies=8, reason_filter="По наявності")` — аналітична вибірка з
уже накопиченої SQLite-таблиці.

```python
#!/usr/bin/env python3
"""Відмови покупцям — касир фіксує, коли клієнт хотів товар, якого не було
(2026-08-12, дані нарешті отримані від АНР — запит був ще 2026-08-11, див.
opencart/ANR_sales_export_TZ.md).

⚠️ НЕ rolling-джерело як sales_daily.py — це ОДНОРАЗОВИЙ історичний
знімок за весь 2025 рік (01.01–31.12.2025), не оновлюється щодня. Тому
в дайджесті показується як окремий ІСТОРИЧНИЙ розділ з явним періодом,
а не як "останні N днів" (на момент цього коду "останні 60 днів" від
сьогодні — 2026 рік — тут просто немає жодних записів).

Формат джерела: Дата, Аптека, Товар, Менеджер, Причина відмови,
Кількість, Ціна зам, Ціна роздр, Ціна прайс. БЕЗ коду товару (на
відміну від sales_daily.py) — товар зберігається як сира назва з
файлу, без спроби зіставити з oc_product (fuzzy-match за назвою
ненадійний, перевірено раніше на sales_1c.py; для звіту про "що
найчастіше відмовляли" сира назва цілком достатня).

Причини відмови в джерелі: "По наявності" (95% записів — товару не
було), "Замовлення в аптеку" (клієнт погодився чекати замовлення — не
зовсім втрачений продаж), "По ціні", "Дефектура ринку" (нема на ринку
взагалі, не тільки в цій аптеці).
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import openpyxl

from opencart_sales import connect, read_env

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"
DB_PATH = CONNECTORS_DIR / "opencart" / "refusals.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS refusals (
    refusal_date TEXT NOT NULL,
    warehouse_id INTEGER,
    warehouse_title TEXT,
    product_name TEXT NOT NULL,
    manager TEXT,
    reason TEXT,
    qty REAL,
    price_order REAL,
    price_retail REAL,
    price_list REAL
);
CREATE INDEX IF NOT EXISTS idx_refusals_date ON refusals (refusal_date);
CREATE INDEX IF NOT EXISTS idx_refusals_wid ON refusals (warehouse_id);

CREATE TABLE IF NOT EXISTS refusals_ingested_files (
    filename TEXT PRIMARY KEY,
    row_count INTEGER,
    matched_warehouse INTEGER,
    ingested_at TEXT
);
"""


def norm_filial(s):
    s = str(s).lstrip("_").strip()
    s = s.replace("Центральна база", "Центральная база")
    s = re.sub(r"Аптека№(\d)", r"Аптека №\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def open_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def ingest_file(xlsx_path, mysql_conn=None):
    """Парсить xlsx-звіт відмов і ЗАМІНЮЄ вміст таблиці refusals повністю
    (не інкрементально, як sales_daily.py — тут нема надійного природного
    ключа на рядок, а джерело зазвичай приходить одним цілим файлом)."""
    xlsx_path = Path(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["TDSheet"]

    own_conn = mysql_conn is None
    if own_conn:
        env = read_env(ENV_PATH)
        mysql_conn = connect(env)
    try:
        with mysql_conn.cursor() as cur:
            cur.execute("SELECT warehouses_id, title FROM oc_warehouses_description")
            title_to_wid = {r["title"]: r["warehouses_id"] for r in cur.fetchall()}
    finally:
        if own_conn:
            mysql_conn.close()

    titles_sorted_desc = sorted(title_to_wid, key=len, reverse=True)
    wid_to_title = {w: t for t, w in title_to_wid.items()}

    def match_filial(fname):
        for t in titles_sorted_desc:
            if fname == t or fname.startswith(t + " ") or fname.startswith(t + ","):
                return title_to_wid[t]
        return None

    rows_out = []
    total_rows = 0
    matched = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        _, date, aptека, product, manager, reason, qty, price_order, price_retail, price_list = row
        if date is None or product is None:
            continue
        total_rows += 1
        # джерело зберігає дату як текст "ДД.ММ.РРРР ГГ:ХХ:СС" — переводимо
        # в ISO (сортовний рядками), інакше MIN/MAX по тексту дає хибний
        # результат (напр. "12.11.2024" лексикографічно ПІСЛЯ "01.01.2025",
        # хоча хронологічно раніше — реальний баг, знайдений 2026-08-12)
        try:
            iso_date = datetime.strptime(str(date).strip(), "%d.%m.%Y %H:%M:%S").isoformat(sep=" ")
        except ValueError:
            iso_date = str(date)
        wid = None
        title = None
        if aptека:
            fname = norm_filial(aptека)
            wid = match_filial(fname)
            title = wid_to_title[wid] if wid is not None else fname
        if wid is not None:
            matched += 1
        rows_out.append((
            iso_date, wid, title,
            product, manager, reason, qty, price_order, price_retail, price_list,
        ))

    hist = open_db()
    try:
        hist.execute("DELETE FROM refusals")
        hist.executemany(
            "INSERT INTO refusals (refusal_date, warehouse_id, warehouse_title, product_name, "
            "manager, reason, qty, price_order, price_retail, price_list) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows_out,
        )
        hist.execute(
            "INSERT OR REPLACE INTO refusals_ingested_files "
            "(filename, row_count, matched_warehouse, ingested_at) VALUES (?, ?, ?, datetime('now'))",
            (xlsx_path.name, total_rows, matched),
        )
        hist.commit()
    finally:
        hist.close()

    return {"filename": xlsx_path.name, "total_rows": total_rows, "matched_warehouse": matched}


def has_data():
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        n = conn.execute("SELECT COUNT(*) FROM refusals").fetchone()[0]
        return n > 0
    finally:
        conn.close()


def get_coverage():
    conn = sqlite3.connect(DB_PATH)
    try:
        min_d, max_d, total = conn.execute(
            "SELECT MIN(refusal_date), MAX(refusal_date), COUNT(*) FROM refusals"
        ).fetchone()
    finally:
        conn.close()
    return {"min_date": min_d, "max_date": max_d, "total_rows": total}


def get_summary(top_n_products=10, top_n_pharmacies=8, reason_filter="По наявності"):
    """Топ товарів і топ аптек за відмовами (весь наявний період — це
    історичний знімок, не rolling-вікно). reason_filter=None означає всі
    причини разом; за замовчуванням лише 'По наявності' (те, що прямо
    стосується дефектури), 'Дефектура ринку'/'По ціні'/'Замовлення в
    аптеку' — інша природа відмови."""
    conn = sqlite3.connect(DB_PATH)
    try:
        where = ""
        params = []
        if reason_filter:
            where = "WHERE reason = ?"
            params.append(reason_filter)

        total_row = conn.execute(
            f"SELECT COUNT(*), SUM(qty), SUM(qty * COALESCE(price_retail, price_order, price_list, 0)) "
            f"FROM refusals {where}", params,
        ).fetchone()

        products = conn.execute(
            f"SELECT product_name, COUNT(*) as cnt, SUM(qty) as qty, "
            f"SUM(qty * COALESCE(price_retail, price_order, price_list, 0)) as value "
            f"FROM refusals {where} GROUP BY product_name ORDER BY cnt DESC LIMIT ?",
            params + [top_n_products],
        ).fetchall()

        pharmacies = conn.execute(
            f"SELECT COALESCE(warehouse_title, 'Невідома') as label, COUNT(*) as cnt "
            f"FROM refusals {where} GROUP BY label ORDER BY cnt DESC LIMIT ?",
            params + [top_n_pharmacies],
        ).fetchall()

        reason_breakdown = conn.execute(
            "SELECT reason, COUNT(*) FROM refusals GROUP BY reason ORDER BY 2 DESC"
        ).fetchall()
    finally:
        conn.close()

    return {
        "total_count": total_row[0] or 0,
        "total_qty": total_row[1] or 0.0,
        "total_est_value": total_row[2] or 0.0,
        "top_products": [
            {"product_name": p[0], "count": p[1], "qty": p[2], "value": p[3]} for p in products
        ],
        "top_pharmacies": [{"label": p[0], "count": p[1]} for p in pharmacies],
        "reason_breakdown": [{"reason": r[0], "count": r[1]} for r in reason_breakdown],
    }


def main():
    import sys

    if len(sys.argv) < 2:
        print("Використання: refusals.py <файл.xlsx>")
        if has_data():
            cov = get_coverage()
            print(f"Поточні дані: {cov['min_date']} — {cov['max_date']}, {cov['total_rows']} записів")
        sys.exit(0)

    env = read_env(ENV_PATH)
    mysql_conn = connect(env)
    try:
        stats = ingest_file(sys.argv[1], mysql_conn=mysql_conn)
    finally:
        mysql_conn.close()
    print(f"{stats['matched_warehouse']}/{stats['total_rows']} рядків зіставлено з аптекою")

    summary = get_summary()
    print(f"\nВсього відмов 'по наявності': {summary['total_count']}, "
          f"оцінна втрата ~{round(summary['total_est_value']):,} грн".replace(",", " "))


if __name__ == "__main__":
    main()

```

---

## 15. stock_history_status.py — щоденний дайджест по залишках

`scripts/stock_history_status.py`

Без класів (це найбільший файл, 839 рядків, але стиль той самий —
функції + модульні константи). `CHAT_IDS`, `DEFECTURA_PHARMACY_TOP_N`,
`REDISTRIBUTION_TOP_N`, `DEAD_STOCK_TOP_N`, `CATEGORY_TOP_N`, `LOW_STOCK_TOP_N`,
`WORST_PHARMACIES_TOP_N` — константи виводу (скільки рядків показувати в
кожному розділі). Модуль **не обчислює** дефектуру/перерозподіл сам — імпортує
готові `get_data`/`get_data_per_pharmacy` з `defectura.py`, `low_stock_alert.py`,
`redistribution.py`, і лише збирає їх в один HTML (`render_digest_html`, із
вкладеною `trend_html(pct)`) і текстовий (`render_digest`) документ.
`record_and_get_trend(...)` зберігає щоденний знімок підсумкових чисел у власну
SQLite-таблицю, щоб `pct(old, new)` (вкладена функція) могла порахувати
день-до-дня тренд. `send_document(token, chat_id, file_path, caption)` —
прямий виклик Telegram Bot API (`requests.post` до `api.telegram.org`), без
`python-telegram-bot`, бо це односторонній cron-скрипт.

```python
#!/usr/bin/env python3
"""Щоденний дайджест по залишках — трекер + дефектура + перерозподіл.

НЕ LLM — простий детермінований скрипт, шле в Telegram точковому списку
отримувачів (CHAT_IDS нижче, НЕ загальний broadcast @apteka_g24_reports_bot
всім users.json). Шле ЛИШЕ HTML-файл документом — звичайний текстовий
Telegram-меседж нечитабельний для такого обсягу таблиць (2026-08-11).
Запускати раз на день через крон на сервері (adm.tools, SSH crontab на
цьому хостингу не працює, див. project-apteka-g24-defectura).
"""
import html
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import requests

from collections import Counter, defaultdict

from defectura import get_data as get_defectura_data
from defectura import get_data_per_pharmacy as get_defectura_per_pharmacy_data
from low_stock_alert import get_data as get_low_stock_data
from product_categories import get_category_map
from redistribution import get_data as get_redistribution_data
from refusals import get_coverage as get_refusals_coverage
from refusals import get_summary as get_refusals_summary
from refusals import has_data as has_refusals_data
from seasonality import get_data as get_seasonality_data

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
DB_PATH = CONNECTORS_DIR / "opencart" / "stock_history.db"
BOT_ENV_PATH = CONNECTORS_DIR / "telegram-bot" / ".env"
REPORTS_DIR = CONNECTORS_DIR / "reports"

CHAT_IDS = [
    "132440298",  # Павло Каспрук
    "666476016",  # Галина Мельник (2026-08-11, за проханням Павла)
    "7195613532",  # Євгеній @excalibur_sword89 (2026-08-26, за проханням Павла)
]

DEFECTURA_PHARMACY_TOP_N = 6
DEFECTURA_ITEMS_PER_PHARMACY = 5
REDISTRIBUTION_TOP_N = 15
DEAD_STOCK_TOP_N = 10
CATEGORY_TOP_N = 8
LOW_STOCK_TOP_N = 10
WORST_PHARMACIES_TOP_N = 5

# Той самий стиль, що й в daily_report.py — картки/таблиці, без графіків
# (не дублюю через import, щоб не тягнути важкі Google API залежності лише
# заради CSS-рядка).
HTML_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 32px 16px 64px;
    background: #f5f5f7;
    color: #1c1c1e;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    line-height: 1.45;
}
.container { max-width: 700px; margin: 0 auto; }
h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 24px;
}
h2 {
    font-size: 19px;
    font-weight: 600;
    margin: 40px 0 14px;
    color: #1c1c1e;
}
h2:first-of-type { margin-top: 0; }
.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 8px;
}
.card {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 16px;
}
.card .value {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
}
.card .label {
    font-size: 12px;
    color: #6e6e73;
    margin-top: 4px;
}
.card .delta {
    font-size: 12px;
    font-weight: 600;
    margin-top: 6px;
    display: inline-block;
}
.pct-up { color: #1a8a3e; }
.pct-down { color: #d1332f; }
.pct-flat { color: #8a8a8e; }
.trend-bad { color: #d1332f; }
.trend-good { color: #1a8a3e; }
.trend-flat { color: #8a8a8e; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; }
table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    overflow: hidden;
    font-size: 13px;
}
th, td {
    text-align: left;
    padding: 8px 6px;
    border-bottom: 1px solid #eeeef0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
th {
    background: #fafafa;
    font-weight: 600;
    color: #3a3a3c;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) { background: #fafafa; }
td:first-child, th:first-child { white-space: normal; overflow-wrap: break-word; width: 46%; }
td.num, th.num { text-align: right; }
td.wrap-cell { white-space: normal; overflow-wrap: break-word; text-overflow: clip; }
.section { margin-bottom: 8px; }
.group-block { margin-bottom: 20px; }
.group-title {
    font-size: 14px;
    font-weight: 600;
    margin: 0 0 8px;
}
.group-title .growth { color: #1a8a3e; }
.note {
    font-size: 12px;
    color: #9a9a9e;
    margin: 8px 0 0;
}
.footer-notes {
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid #e5e5ea;
    font-size: 11px;
    color: #aeaeb2;
}
.footer-notes p { margin: 4px 0; }
"""


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def dead_stock_value_by_pharmacy(dead_stock_rows, limit=WORST_PHARMACIES_TOP_N):
    """Рейтинг аптек за грн-вартістю заморожену в неліквіді (не за сирим
    обсягом руху, як був старий блок 'Активність аптек') — директору цікаво,
    де найбільше грошей лежить мертвим вантажем, а не яка аптека просто
    найбільша/найжвавіша."""
    totals = defaultdict(lambda: {"value": 0.0, "positions": 0})
    for row in dead_stock_rows:
        label = row["warehouse_title"] or f"Склад {row['warehouse_id']}"
        totals[label]["value"] += row.get("value", 0.0)
        totals[label]["positions"] += 1
    ranked = sorted(
        ({"label": label, **v} for label, v in totals.items()),
        key=lambda x: -x["value"],
    )
    return ranked[:limit]


def record_and_get_trend(defectura_positions, defectura_daily_loss,
                          dead_stock_positions, dead_stock_value):
    """Записує сьогоднішні мережеві метрики в SQLite (idempotent — INSERT OR
    REPLACE, можна запускати дайджест повторно за той самий день) і рахує
    % зміни день-до-дня-тиждень-тому (WoW). Тиждень тому файлу може не бути
    (перший запуск) — тоді тренд None."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS digest_metrics_history (
            date TEXT PRIMARY KEY,
            defectura_positions INTEGER,
            defectura_daily_loss REAL,
            dead_stock_positions INTEGER,
            dead_stock_value REAL
        )
    """)
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT OR REPLACE INTO digest_metrics_history VALUES (?, ?, ?, ?, ?)",
        (today_str, defectura_positions, defectura_daily_loss, dead_stock_positions, dead_stock_value),
    )
    conn.commit()

    week_ago_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT defectura_positions, defectura_daily_loss, dead_stock_positions, dead_stock_value "
        "FROM digest_metrics_history WHERE date = ?", (week_ago_str,)
    ).fetchone()
    conn.close()

    def pct(old, new):
        if old is None or new is None or old == 0:
            return None
        return (new - old) / old * 100

    if row is None:
        return {
            "defectura_positions_pct": None, "defectura_daily_loss_pct": None,
            "dead_stock_positions_pct": None, "dead_stock_value_pct": None,
        }
    return {
        "defectura_positions_pct": pct(row[0], defectura_positions),
        "defectura_daily_loss_pct": pct(row[1], defectura_daily_loss),
        "dead_stock_positions_pct": pct(row[2], dead_stock_positions),
        "dead_stock_value_pct": pct(row[3], dead_stock_value),
    }


def fmt_money(value):
    if value is None:
        return "н/д"
    return f"{value:,.0f}".replace(",", " ") + " грн"


def fmt_trend(pct):
    if pct is None:
        return ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "→")
    return f" ({arrow}{abs(pct):.0f}% за тиждень)"


def fetch_defectura_by_pharmacy_digest(pharmacy_limit=DEFECTURA_PHARMACY_TOP_N,
                                        items_limit=DEFECTURA_ITEMS_PER_PHARMACY):
    """Розбивка дефектури по аптеках (не мережевий підсумок) — топ-аптеки
    за грн-втратою (daily-рівень) чи за кількістю проданого (fallback-рівні,
    де ціни нема), в кожній — топ-товари. Замінює старий "мережевий
    підсумок", який не показував В ЯКІЙ саме аптеці бракує товару
    (запит користувача 2026-08-11)."""
    data = get_defectura_per_pharmacy_data()
    is_daily = data["data_source"] == "daily"

    pharmacies = []
    for entry in data["pharmacies"].values():
        if not entry["items"]:
            continue
        if is_daily:
            total_loss = sum(item.get("est_daily_loss", 0.0) for item in entry["items"])
            top_items = sorted(entry["items"], key=lambda x: -x.get("est_daily_loss", 0.0))[:items_limit]
            sort_key = total_loss
        else:
            total_loss = None
            top_items = sorted(entry["items"], key=lambda x: -x["sold_qty"])[:items_limit]
            sort_key = sum(item["sold_qty"] for item in entry["items"])
        pharmacies.append({
            "label": entry["label"],
            "total_loss": total_loss,
            "total_items": len(entry["items"]),
            "items": top_items,
            "_sort_key": sort_key,
        })
    pharmacies.sort(key=lambda p: -p["_sort_key"])
    for p in pharmacies:
        del p["_sort_key"]

    return pharmacies[:pharmacy_limit], len(data["pharmacies"]), data["data_source"], data["period"]


def fetch_redistribution_digest(limit=REDISTRIBUTION_TOP_N):
    data = get_redistribution_data()
    seen = set()
    picked = []
    for r in data["redistribution"]:
        if r["product_id"] in seen:
            continue
        seen.add(r["product_id"])
        picked.append(r)
        if len(picked) >= limit:
            break
    return picked, len(data["redistribution"]), data["redistribution_source"], data["redistribution_meta"]


def fetch_dead_stock_digest(limit=DEAD_STOCK_TOP_N):
    data = get_redistribution_data()
    return (
        data["dead_stock"][:limit], len(data["dead_stock"]),
        data["dead_stock_source"], data["dead_stock_meta"],
    )


def fetch_defectura_category_breakdown(limit=CATEGORY_TOP_N):
    """Дефектура по терапевтичних групах (не плоским списком) — рахує
    ПОВНИЙ список по всіх аптеках (не обрізаний топ-N цифрового дайджесту),
    кожна позиція товар×аптека рахується окремо.

    Сортує за % часткою дефектури в каталозі категорії (пропорційно
    гірші перші), НЕ за сирою кількістю — інакше вузькі категорії
    (напр. Ендокринологія: 64 поз. з 116 у каталозі = 55%) губляться за
    великими (Серце: 589 з 1255 = 47%, виглядає гірше лише через розмір
    каталогу, хоча частка менша). Запит користувача 2026-08-12."""
    data = get_defectura_per_pharmacy_data()
    cat_map = get_category_map()
    catalog_totals = Counter(cat_map.values())

    counter = Counter()
    for entry in data["pharmacies"].values():
        for item in entry["items"]:
            cat = cat_map.get(item["product_id"], "Без категорії")
            counter[cat] += 1

    breakdown = []
    for name, cnt in counter.items():
        catalog_size = catalog_totals.get(name, 0)
        pct = (cnt / catalog_size * 100) if catalog_size else None
        breakdown.append({"name": name, "count": cnt, "catalog_size": catalog_size, "pct": pct})
    breakdown.sort(key=lambda b: -(b["pct"] or 0))

    return breakdown[:limit], sum(counter.values())


def fetch_low_stock_digest(limit=LOW_STOCK_TOP_N):
    data = get_low_stock_data()
    return (
        data["alerts"][:limit], len(data["alerts"]),
        data["data_source"], data["meta"], data["days_threshold"],
    )


def source_note(source, meta):
    """Текстова позначка джерела даних — daily / 1С / stock_drops /
    мережевий проксі (спільна для тексту й HTML)."""
    if source == "daily":
        return f"✅ Реальна поденна історія, {meta['period_start']} (дані по {meta['period_end']})"
    if source == "1c":
        return f"✅ Реальні продажі з 1С, період з {meta['period_start']}"
    if source == "stock_drops":
        return f"🟡 Власний трекер падінь залишку (1С не знайдено), з {meta['period_start']}"
    return "⚠️ Ні 1С, ні трекер падінь недоступні — мережевий проксі"


def low_stock_source_note(source, meta):
    """Окремий набір джерел для low_stock_alert.py (recent_1c/unavailable
    не мають прямого відповідника в source_note())."""
    if source == "daily":
        return f"✅ Реальна поденна історія, швидкість за {meta['period_start']} (дані по {meta['period_end']})"
    if source == "recent_1c":
        return f"✅ Свіжа швидкість продажу (1С, дельта за {meta['days_between']} дн.)"
    if source == "1c":
        return (
            f"⚠️ Середнє з {meta['period_start']} — може бути неточним для сезонних товарів"
        )
    if source == "stock_drops":
        return f"🟡 Власний трекер падінь залишку (1С не знайдено), з {meta['period_start']}"
    return "⚠️ Недостатньо даних для прогнозу"


def render_digest(network, defectura_pharmacies, defectura_pharmacy_count, defectura_source, defectura_meta,
                   redistribution_items, redistribution_total, redistribution_source, redistribution_meta,
                   dead_stock_items, dead_stock_total, dead_stock_source, dead_stock_meta,
                   category_breakdown, category_total,
                   low_stock_items, low_stock_total, low_stock_source, low_stock_meta, low_stock_days):
    lines = []
    lines.append(f"📦 ЩОДЕННИЙ ЗВІТ ПО ЗАЛИШКАХ — {datetime.now().strftime('%d.%m.%Y')}")
    lines.append("")

    trend = network["trend"]
    lines.append("── 🎯 Мережа в цілому ──")
    lines.append(
        f"📦 Дефектура: {network['defectura_positions']} поз., "
        f"~{fmt_money(network['defectura_daily_loss'])}/день недоотриманого продажу"
        f"{fmt_trend(trend['defectura_daily_loss_pct'])}"
    )
    lines.append(
        f"🧊 Неліквід: {network['dead_stock_positions']} поз., "
        f"~{fmt_money(network['dead_stock_value'])} заморожено"
        f"{fmt_trend(trend['dead_stock_value_pct'])}"
    )
    if network["defectura_daily_loss"] is None or network["dead_stock_value"] is None:
        lines.append("(грн-оцінка доступна лише коли джерело даних — реальна поденна історія)")
    lines.append("")
    if network["worst_pharmacies"]:
        lines.append("Найбільше неліквіду заморожено:")
        for wp in network["worst_pharmacies"]:
            lines.append(f"  {wp['label']}: {fmt_money(wp['value'])} ({wp['positions']} поз.)")
    lines.append("")

    lines.append(
        f"── 📦 Дефектура по аптеках (топ-{len(defectura_pharmacies)} "
        f"з {defectura_pharmacy_count} аптек за втратами) ──"
    )
    lines.append(source_note(defectura_source, defectura_meta))
    rate_days = defectura_meta.get("rate_window_days", 30) if defectura_meta else 30
    for ph in defectura_pharmacies:
        if ph["total_loss"] is not None:
            lines.append(f"🏪 {ph['label']} — ~{fmt_money(ph['total_loss'])}/день ({ph['total_items']} поз.)")
        else:
            lines.append(f"🏪 {ph['label']} — {ph['total_items']} поз.")
        for item in ph["items"]:
            model = item["model"] or f"id{item['product_id']}"
            if defectura_source == "daily":
                lines.append(
                    f"   • {item['product_name']} ({model}) — "
                    f"~{fmt_money(item['est_daily_loss'])}/день "
                    f"(продано {item['recent_sold_qty']:g} шт за {rate_days} дн.)"
                )
            else:
                lines.append(f"   • {item['product_name']} ({model}) — продано {item['sold_qty']:g} шт")
        lines.append("")
    lines.append("")

    lines.append(f"── 📊 Дефектура по категоріях (з {category_total} позицій, % від каталогу) ──")
    for c in category_breakdown:
        pct_str = f"{c['pct']:.0f}%" if c["pct"] is not None else "н/д"
        lines.append(f"  {c['name']}: {c['count']} з {c['catalog_size']} ({pct_str})")
    lines.append("")

    lines.append(f"── 🔄 Перерозподіл (топ-{len(redistribution_items)} з {redistribution_total}) ──")
    lines.append(source_note(redistribution_source, redistribution_meta))
    for r in redistribution_items:
        model = r["model"] or f"id{r['product_id']}"
        top_donor = r["donors"][0]
        stability = r.get("demand_stability")
        stability_note = f" ({stability}/6 міс. стабільно)" if stability is not None else ""
        lines.append(f"• {r['product_name']} ({model}){stability_note}")
        lines.append(f"   Немає в {r['needs_at']} → взяти з {top_donor['label']} (надлишок {top_donor['quantity']:g} шт)")
    lines.append("")

    lines.append(f"── 🧊 Неліквіди (топ-{len(dead_stock_items)} з {dead_stock_total}) ──")
    lines.append(source_note(dead_stock_source, dead_stock_meta))
    for row in dead_stock_items:
        model = row["model"] or f"id{row['product_id']}"
        label = row["warehouse_title"] or f"Склад {row['warehouse_id']}"
        lines.append(f"• {row['product_name']} ({model}) — {label}: {row['quantity']:g} шт")
    lines.append("")

    lines.append(
        f"── ⏳ Скоро закінчаться, <{low_stock_days} дн. запасу "
        f"(топ-{len(low_stock_items)} з {low_stock_total}) ──"
    )
    lines.append(low_stock_source_note(low_stock_source, low_stock_meta))
    for a in low_stock_items:
        model = a["model"] or f"id{a['product_id']}"
        seasonal_note = " 🌦" if a.get("seasonal_adjusted") else ""
        lines.append(
            f"• {a['product_name']} ({model}) — {a['warehouse_title']}: "
            f"залишок {a['quantity']:g} шт, лишилось ~{a['days_left']:.1f} дн.{seasonal_note}"
        )

    return "\n".join(lines)


def render_digest_html(network, defectura_pharmacies, defectura_pharmacy_count, defectura_source, defectura_meta,
                        redistribution_items, redistribution_total, redistribution_source, redistribution_meta,
                        dead_stock_items, dead_stock_total, dead_stock_source, dead_stock_meta,
                        category_breakdown, category_total,
                        low_stock_items, low_stock_total, low_stock_source, low_stock_meta, low_stock_days,
                        seasonality_data, refusals_data):
    e = html.escape
    today_str = datetime.now().strftime("%d.%m.%Y")

    def trend_html(pct):
        if pct is None:
            return ""
        cls = "trend-flat" if pct == 0 else ("trend-bad" if pct > 0 else "trend-good")
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "→")
        return f"<div class='delta {cls}'>{arrow}{abs(pct):.0f}% за тиждень</div>"

    trend = network["trend"]
    network_cards = f"""
    <div class="cards">
        <div class="card">
            <div class="value">{e(fmt_money(network['dead_stock_value']))}</div>
            <div class="label">Неліквід заморожено ({network['dead_stock_positions']} поз.)</div>
            {trend_html(trend['dead_stock_value_pct'])}
        </div>
        <div class="card">
            <div class="value">{e(fmt_money(network['defectura_daily_loss']))}/день</div>
            <div class="label">Недоотриманий продаж ({network['defectura_positions']} поз. дефектури)</div>
            {trend_html(trend['defectura_daily_loss_pct'])}
        </div>
    </div>
    """

    if network["worst_pharmacies"]:
        worst_rows = "".join(
            f"<tr><td>{e(wp['label'])}</td><td class='num'>{e(fmt_money(wp['value']))}</td>"
            f"<td class='num'>{wp['positions']}</td></tr>"
            for wp in network["worst_pharmacies"]
        )
        worst_table = (
            "<div class='table-wrap'><table><thead><tr><th>Аптека</th>"
            "<th class='num'>Заморожено</th><th class='num'>Поз.</th></tr></thead>"
            f"<tbody>{worst_rows}</tbody></table></div>"
        )
    else:
        worst_table = "<p class='note'>Немає даних</p>"

    defectura_col_header = "Втрата/день" if defectura_source == "daily" else "Продано"
    if defectura_pharmacies:
        defectura_blocks = []
        for ph in defectura_pharmacies:
            row_parts = []
            for item in ph["items"]:
                model = item["model"] or f"id{item['product_id']}"
                cell = (
                    f"{e(fmt_money(item['est_daily_loss']))}/день"
                    if defectura_source == "daily" else f"{item['sold_qty']:g} шт"
                )
                row_parts.append(
                    f"<tr><td>{e(item['product_name'])} <span class='note'>({e(model)})</span></td>"
                    f"<td class='num'>{cell}</td></tr>"
                )
            rows = "".join(row_parts)
            header = f"🏪 {e(ph['label'])}"
            header += (
                f" — ~{e(fmt_money(ph['total_loss']))}/день ({ph['total_items']} поз.)"
                if ph["total_loss"] is not None else f" — {ph['total_items']} поз."
            )
            defectura_blocks.append(f"""
            <div class="group-block">
                <p class="group-title">{header}</p>
                <div class="table-wrap"><table><thead><tr>
                    <th>Товар</th><th class="num">{defectura_col_header}</th>
                </tr></thead><tbody>{rows}</tbody></table></div>
            </div>
            """)
        defectura_table = "".join(defectura_blocks)
    else:
        defectura_table = "<p class='note'>(дефектури немає)</p>"
    defectura_note = source_note(defectura_source, defectura_meta)

    category_row_parts = []
    for c in category_breakdown:
        pct_str = f"{c['pct']:.0f}%" if c["pct"] is not None else "н/д"
        category_row_parts.append(
            f"<tr><td>{e(c['name'])}</td><td class='num'>{c['count']} з {c['catalog_size']}</td>"
            f"<td class='num'>{pct_str}</td></tr>"
        )
    category_rows = "".join(category_row_parts)
    category_table = (
        "<div class='table-wrap'><table><thead><tr><th>Категорія</th>"
        "<th class='num'>Позицій</th><th class='num'>% каталогу</th></tr></thead>"
        f"<tbody>{category_rows}</tbody></table></div>"
    )

    redistribution_row_parts = []
    for r in redistribution_items:
        model = r["model"] or f"id{r['product_id']}"
        donor = r["donors"][0]
        stability = r.get("demand_stability")
        stability_note = f" <span class='note'>({stability}/6 міс.)</span>" if stability is not None else ""
        redistribution_row_parts.append(
            f"<tr><td>{e(r['product_name'])}{stability_note} <span class='note'>({e(model)})</span></td>"
            f"<td class='wrap-cell'>Немає в <strong>{e(r['needs_at'])}</strong>"
            f"<br>→ взяти з {e(donor['label'])} (надлишок {donor['quantity']:g} шт)</td></tr>"
        )
    redistribution_rows = "".join(redistribution_row_parts)
    redistribution_table = (
        "<div class='table-wrap redistribution-table'><table><thead><tr>"
        "<th>Товар</th><th>Де взяти</th></tr></thead>"
        f"<tbody>{redistribution_rows}</tbody></table></div>"
    )
    redistribution_note = source_note(redistribution_source, redistribution_meta)

    dead_stock_row_parts = []
    for row in dead_stock_items:
        model = row["model"] or f"id{row['product_id']}"
        label = row["warehouse_title"] or f"Склад {row['warehouse_id']}"
        dead_stock_row_parts.append(
            f"<tr><td>{e(row['product_name'])} <span class='note'>({e(model)})</span></td>"
            f"<td>{e(label)}</td><td class='num'>{row['quantity']:g} шт</td></tr>"
        )
    dead_stock_rows = "".join(dead_stock_row_parts)
    dead_stock_table = (
        "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
        "<th>Аптека</th><th class='num'>Залишок</th></tr></thead>"
        f"<tbody>{dead_stock_rows}</tbody></table></div>"
    )
    dead_stock_note = source_note(dead_stock_source, dead_stock_meta)

    low_stock_row_parts = []
    for a in low_stock_items:
        model = a["model"] or f"id{a['product_id']}"
        seasonal_note = " 🌦" if a.get("seasonal_adjusted") else ""
        low_stock_row_parts.append(
            f"<tr><td>{e(a['product_name'])} <span class='note'>({e(model)})</span></td>"
            f"<td>{e(a['warehouse_title'])}</td><td class='num'>{a['quantity']:g} шт</td>"
            f"<td class='num'>~{a['days_left']:.1f} дн.{seasonal_note}</td></tr>"
        )
    low_stock_rows = "".join(low_stock_row_parts)
    low_stock_table = (
        "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
        "<th>Аптека</th><th class='num'>Залишок</th><th class='num'>Днів</th></tr></thead>"
        f"<tbody>{low_stock_rows}</tbody></table></div>"
    )
    low_stock_note = low_stock_source_note(low_stock_source, low_stock_meta)

    if seasonality_data["data_source"] is None:
        seasonality_html = "<p class='note'>Недостатньо історії (потрібно ще ~13 міс. накопичених даних)</p>"
    elif not seasonality_data["categories"]:
        seasonality_html = "<p class='note'>Категорій з очікуваним сезонним ростом не знайдено</p>"
    else:
        window_days_label = seasonality_data["meta"]["window_days"]
        blocks = []
        for cat in seasonality_data["categories"]:
            row_parts = []
            for p in cat["products"]:
                model = p["model"] or f"id{p['product_id']}"
                days_str = f"{p['days_of_stock']:.0f} дн." if p["days_of_stock"] is not None else "н/д"
                row_parts.append(
                    f"<tr><td>{e(p['product_name'])} <span class='note'>({e(model)})</span></td>"
                    f"<td class='num'>{p['last_year_next_qty']:g} шт</td>"
                    f"<td class='num'>{p['current_stock']:g} шт</td>"
                    f"<td class='num'>{days_str}</td></tr>"
                )
            rows = "".join(row_parts)
            blocks.append(f"""
            <div class="group-block">
                <p class="group-title">📈 {e(cat['name'])} — торік попит зріс на
                    <span class="growth">+{cat['growth_pct']:.0f}%</span> за наступні {window_days_label} дн.</p>
                <div class="table-wrap"><table><thead><tr>
                    <th>Товар</th><th class="num">Торік/{window_days_label}дн.</th>
                    <th class="num">Залишок</th><th class="num">Днів запасу</th>
                </tr></thead><tbody>{rows}</tbody></table></div>
            </div>
            """)
        seasonality_html = "".join(blocks)

    if refusals_data is None:
        refusals_html = "<p class='note'>Дані про відмови ще не завантажені.</p>"
        refusals_note = ""
    else:
        cov = refusals_data["coverage"]
        summary = refusals_data["summary"]
        refusals_note = (
            f"⚠️ Знімок за {cov['min_date'][:10]} — {cov['max_date'][:10]} (АНР), "
            f"НЕ оновлюється автоматично щодня — потрібен новий файл від користувача, "
            f"щоб дані стали свіжішими за цю дату. "
            f"Лише причина 'По наявності' ({summary['total_count']} з {sum(r['count'] for r in summary['reason_breakdown'])})."
        )
        product_rows = "".join(
            f"<tr><td>{e(p['product_name'])}</td><td class='num'>{p['count']}</td>"
            f"<td class='num'>{e(fmt_money(p['value']))}</td></tr>"
            for p in summary["top_products"]
        )
        products_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th class='num'>Відмов</th><th class='num'>Оцінна втрата</th></tr></thead>"
            f"<tbody>{product_rows}</tbody></table></div>"
        )
        pharmacy_rows = "".join(
            f"<tr><td>{e(ph['label'])}</td><td class='num'>{ph['count']}</td></tr>"
            for ph in summary["top_pharmacies"]
        )
        pharmacies_table = (
            "<div class='table-wrap'><table><thead><tr><th>Аптека</th>"
            "<th class='num'>Відмов</th></tr></thead>"
            f"<tbody>{pharmacy_rows}</tbody></table></div>"
        )
        refusals_html = f"""
        <div class="cards">
            <div class="card">
                <div class="value">{summary['total_count']}</div>
                <div class="label">Відмов "по наявності" за весь період</div>
            </div>
            <div class="card">
                <div class="value">{e(fmt_money(summary['total_est_value']))}</div>
                <div class="label">Оцінна втрачена виручка</div>
            </div>
        </div>
        <p class="group-title" style="margin-top:20px;">Топ товарів за кількістю відмов</p>
        {products_table}
        <p class="group-title" style="margin-top:20px;">Топ аптек за кількістю відмов</p>
        {pharmacies_table}
        """

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Звіт по залишках — {today_str}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<div class="container">
    <h1>📦 Звіт по залишках — {today_str}</h1>

    <h2>🎯 Мережа в цілому</h2>
    <div class="section">
        {network_cards}
        <p class="note">Найбільше неліквіду заморожено:</p>
        {worst_table}
    </div>

    <h2>📦 Дефектура по аптеках (топ-{len(defectura_pharmacies)} з {defectura_pharmacy_count} аптек за втратами)</h2>
    <div class="section">
        {defectura_table}
        <p class="note">{defectura_note}</p>
    </div>

    <h2>📊 Дефектура по категоріях (з {category_total} позицій)</h2>
    <div class="section">
        {category_table}
    </div>

    <h2>🔄 Перерозподіл (топ-{len(redistribution_items)} з {redistribution_total})</h2>
    <div class="section">
        {redistribution_table}
        <p class="note">{redistribution_note}</p>
    </div>

    <h2>🧊 Неліквіди (топ-{len(dead_stock_items)} з {dead_stock_total})</h2>
    <div class="section">
        {dead_stock_table}
        <p class="note">{dead_stock_note}</p>
    </div>

    <h2>⏳ Скоро закінчаться, &lt;{low_stock_days} дн. запасу (топ-{len(low_stock_items)} з {low_stock_total})</h2>
    <div class="section">
        {low_stock_table}
        <p class="note">{low_stock_note}</p>
    </div>

    <h2>🌦 Сезонність — прогноз на основі торішнього періоду</h2>
    <div class="section">
        {seasonality_html}
    </div>

    <h2>🚫 Відмови покупцям (історичний звіт АНР)</h2>
    <div class="section">
        {refusals_html}
        <p class="note">{refusals_note}</p>
    </div>

    <div class="footer-notes">
        <p>Автоматичний щоденний дайджест, генерується без участі LLM.</p>
        <p>🌦 біля "скоро закінчиться" — швидкість продажу скоригована на очікуваний сезонний ріст (торішній період), не лише останні 30 днів.</p>
    </div>
</div>
</body>
</html>
"""


def send_document(token, chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        return requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"document": f},
            timeout=60,
        )


def main():
    defectura_pharmacies, defectura_pharmacy_count, defectura_source, defectura_meta = fetch_defectura_by_pharmacy_digest()
    redistribution_items, redistribution_total, redistribution_source, redistribution_meta = fetch_redistribution_digest()
    dead_stock_items, dead_stock_total, dead_stock_source, dead_stock_meta = fetch_dead_stock_digest()
    category_breakdown, category_total = fetch_defectura_category_breakdown()
    low_stock_items, low_stock_total, low_stock_source, low_stock_meta, low_stock_days = fetch_low_stock_digest()
    seasonality_data = get_seasonality_data()
    refusals_data = None
    if has_refusals_data():
        refusals_data = {"coverage": get_refusals_coverage(), "summary": get_refusals_summary()}

    defectura_full = get_defectura_data()
    redistribution_full = get_redistribution_data()
    worst_pharmacies = dead_stock_value_by_pharmacy(redistribution_full["dead_stock"])
    trend = record_and_get_trend(
        defectura_full["count"], defectura_full.get("total_est_daily_loss"),
        len(redistribution_full["dead_stock"]), redistribution_full.get("dead_stock_total_value"),
    )
    network = {
        "defectura_positions": defectura_full["count"],
        "defectura_daily_loss": defectura_full.get("total_est_daily_loss"),
        "dead_stock_positions": len(redistribution_full["dead_stock"]),
        "dead_stock_value": redistribution_full.get("dead_stock_total_value"),
        "trend": trend,
        "worst_pharmacies": worst_pharmacies,
    }

    message = render_digest(
        network,
        defectura_pharmacies, defectura_pharmacy_count, defectura_source, defectura_meta,
        redistribution_items, redistribution_total, redistribution_source, redistribution_meta,
        dead_stock_items, dead_stock_total, dead_stock_source, dead_stock_meta,
        category_breakdown, category_total,
        low_stock_items, low_stock_total, low_stock_source, low_stock_meta, low_stock_days,
    )
    print(message)

    html_report = render_digest_html(
        network,
        defectura_pharmacies, defectura_pharmacy_count, defectura_source, defectura_meta,
        redistribution_items, redistribution_total, redistribution_source, redistribution_meta,
        dead_stock_items, dead_stock_total, dead_stock_source, dead_stock_meta,
        category_breakdown, category_total,
        low_stock_items, low_stock_total, low_stock_source, low_stock_meta, low_stock_days,
        seasonality_data, refusals_data,
    )
    REPORTS_DIR.mkdir(exist_ok=True)
    html_path = REPORTS_DIR / f"Залишки {datetime.now().strftime('%d.%m.%Y')}.html"
    html_path.write_text(html_report, encoding="utf-8")

    env = read_env(BOT_ENV_PATH)
    token = env["TELEGRAM_BOT_TOKEN"]
    caption = f"📦 Звіт по залишках — {datetime.now().strftime('%d.%m.%Y')}"
    for chat_id in CHAT_IDS:
        doc_resp = send_document(token, chat_id, html_path, caption)
        print(f"Telegram document send status ({chat_id}): {doc_resp.status_code}")


if __name__ == "__main__":
    main()

```

---

## 16. transfer_pages.py — статичні HTML-сторінки на сайті

`scripts/transfer_pages.py`

Без класів. `OUTPUT_DIR` — шлях у docroot сайту (`.../transfers/`).
`slugify_title(title)` перетворює назву аптеки в безпечне ім'я файлу — навмисно
не використовує сирий `warehouses_id` (задокументована пастка зі зсувом +4 між
БД-id і номером у назві). `fetch_warehouse_names()` читає назви складів з
MySQL. `build_pharmacy_data()` — центральна функція, що для кожної аптеки
зводить докупи п'ять джерел (перерозподіл, дефектура без донора, low-stock,
мертвий вантаж) через імпорти з `redistribution.py`/`defectura.py`/
`low_stock_alert.py`. `_suggest_order_qty(recent_sold_qty)` — чиста функція
оцінки, скільки замовити постачальнику, на основі нещодавнього темпу продажу.
`render_pharmacy_page`/`render_index_page` — генерація HTML прямим складанням
рядків (без Jinja2).

```python
#!/usr/bin/env python3
"""Щоденні сторінки перенесень — одна статична HTML-сторінка на кожну аптеку,
опублікована прямо на живому сайті (не в Telegram). Повна картина для
завідуючої (2026-08-12, за прямим запитом користувача — раніше сторінка
показувала ЛИШЕ перерозподіл):
  1. 📥 Привезти сюди — перерозподіл з іншої аптеки.
  2. 🛒 Замовити постачальнику — дефектура, для якої НЕМА донора в мережі
     (перенести нізвідки, лишається тільки замовлення).
  3. ⏳ Скоро закінчиться — quantity>0, але спрогнозовано на 0 найближчим
     часом при поточному темпі.
  4. 🧊 Мертвий вантаж — лежить, реально не продається САМЕ ТУТ.
  5. 📤 Забрати звідси — донорська сторона перерозподілу.

Публікується в docroot сайту apteka.g24.ua (не чіпає жодних існуючих файлів
сайту, тільки нова підпапка transfers/) — тому доступно як звичайний
статичний файл, наприклад https://apteka.g24.ua/transfers/apteka-8.html.
Перевірено вручну: сайтовий .htaccess віддає реальні файли напряму, не
перенаправляє їх через OpenCart-роутинг (RewriteCond !-f).

УВАГА, пастка: `warehouses_id` (числовий id у БД) НЕ збігається з номером у
назві "Аптека №N" — є зсув +4 (наприклад warehouses_id=12 це "Аптека №8",
warehouses_id=16 це "Аптека №12"). Файли НІКОЛИ не називати по сирому id
(так один раз зроблено й одразу впіймано — 12.html показував Аптеку №8) —
завжди через slugify_title(), яка читає реальний title.

Не LLM — детермінований скрипт, той самий стиль/дані, що й
stock_history_status.py. Запускати раз на день на сервері (та сама причина,
чому там не можна ставити крон по SSH — див. project-apteka-g24-defectura).
"""
import html
import math
import re
from datetime import datetime
from pathlib import Path

from defectura import get_data_per_pharmacy as get_defectura_per_pharmacy_data
from low_stock_alert import DAYS_THRESHOLD, MIN_SOLD_TOTAL
from low_stock_alert import get_data as get_low_stock_data
from opencart_sales import connect as mysql_connect
from opencart_sales import read_env as mysql_read_env
from redistribution import DEAD_STOCK_DAYS, MIN_DONOR_RESERVE_DAYS
from redistribution import get_data as get_redistribution_data
from seasonality import get_data as get_seasonality_data
from stock_history_status import HTML_STYLE, fmt_money

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
OPENCART_ENV_PATH = CONNECTORS_DIR / "opencart" / ".env"

# Тільки на сервері — публічний docroot сайту. Локально цього шляху немає,
# скрипт призначений для запуску через SSH на fz453955.
TRANSFERS_DIR = Path("/home/fz453955/g24.ua/apteka/transfers")

BASE_URL = "https://apteka.g24.ua/transfers"

# Власний стиль сторінок перенесень (2026-08-26, той самий вигляд, що й
# ad-hoc "Порада для Аптеки №13" — довелось узгодити всю мережу з ним,
# за проханням користувача). НЕ ділиться з HTML_STYLE (stock_history_status.py
# / Telegram-дайджест) навмисно — це окрема, публічна сторінка на сайті.
TRANSFER_PAGE_STYLE = """
:root {
  --bg: #F6F3EC; --surface: #FFFFFF; --surface-alt: #EFEAE0;
  --ink: #1D2623; --ink-soft: #5B655F;
  --teal: #2C6E68; --teal-deep: #1B4744; --teal-tint: #E4EEEC;
  --gold: #B9832C; --gold-tint: #FBF0DB;
  --red: #B23A34; --red-tint: #FBE6E4;
  --border: #DEDACE;
  --shadow: 0 1px 2px rgba(29,38,35,0.06), 0 8px 24px rgba(29,38,35,0.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #121C19; --surface: #182420; --surface-alt: #1F2C27;
    --ink: #EAE7DD; --ink-soft: #9FAAA3;
    --teal: #64B3AA; --teal-deep: #3D847C; --teal-tint: #1E332F;
    --gold: #E0A94F; --gold-tint: #2E2416;
    --red: #E2726B; --red-tint: #33201E;
    --border: #2B3A35;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
  }
}
:root[data-theme="dark"] {
  --bg: #121C19; --surface: #182420; --surface-alt: #1F2C27;
  --ink: #EAE7DD; --ink-soft: #9FAAA3;
  --teal: #64B3AA; --teal-deep: #3D847C; --teal-tint: #1E332F;
  --gold: #E0A94F; --gold-tint: #2E2416;
  --red: #E2726B; --red-tint: #33201E;
  --border: #2B3A35;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.35);
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: 'Golos Text', -apple-system, sans-serif; line-height: 1.5;
}
.mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.wrap { max-width: 1000px; margin: 0 auto; padding: 28px 18px 72px; }
.masthead { display: flex; flex-direction: column; gap: 6px; padding-bottom: 20px; margin-bottom: 24px; border-bottom: 2px solid var(--teal); }
.masthead .eyebrow { font-family: 'JetBrains Mono', monospace; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--teal); font-weight: 600; }
.masthead h1 { font-size: clamp(24px,4vw,32px); margin: 2px 0 4px; font-weight: 800; }
.masthead .sub { color: var(--ink-soft); font-size: 14.5px; max-width: 70ch; }
.masthead a { color: var(--teal-deep); }
.statrow { display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 12px; margin: 20px 0 32px; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 13px 15px; box-shadow: var(--shadow); }
.stat .n { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 20px; color: var(--teal-deep); }
.stat .l { font-size: 12px; color: var(--ink-soft); margin-top: 2px; }
section, .section-block { margin-bottom: 34px; }
.sec-head { margin-bottom: 10px; }
.sec-head h2 { font-size: 18px; font-weight: 700; margin: 0 0 4px; }
.sec-head .note, p.note { font-size: 12.5px; color: var(--ink-soft); margin: 0 0 10px; }
.table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); box-shadow: var(--shadow); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 9px 11px; background: var(--surface-alt); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-soft); border-bottom: 1px solid var(--border); white-space: nowrap; }
td { padding: 8px 11px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
td.num { text-align: right; font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.wrap-cell { min-width: 220px; }
.strong-cell { font-weight: 700; color: var(--teal-deep); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 600; white-space: nowrap; }
.badge-urgent { background: var(--red-tint); color: var(--red); }
.badge-warn { background: var(--gold-tint); color: var(--gold); }
.badge-season { background: var(--teal-tint); color: var(--teal-deep); }
.pct-down { color: var(--red); font-weight: 600; }
h3 { font-size: 14.5px; margin: 18px 0 8px; }
.footer-notes { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--border); font-size: 11.5px; color: var(--ink-soft); }
.footer-notes p { margin: 4px 0; }
"""

# Кожна сторінка сама тягне шрифти з Google Fonts (той самий підхід, що й
# ad-hoc HTML-звіт) - працює на живому сайті, не залежить від інших сторінок.
FONT_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700;800&'
    'family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">'
)

# Товар повинен продаватись хоча б стільки за останні 30 дн., щоб потрапити
# в "привезти"/"замовити" на сторінці аптеки (запит користувача 2026-08-12:
# тягнути коробку заради 1 продажу на квартал — не варта витрачених
# зусиль персоналу). Застосовується лише на daily-рівні (де є recent_sold_qty).
MIN_RECENT_SOLD_QTY = 2


def _passes_velocity_filter(item, data_source):
    if data_source != "daily":
        return True
    return (item.get("recent_sold_qty") or 0) >= MIN_RECENT_SOLD_QTY


def slugify_title(title):
    t = title.strip()

    m = re.match(r"^Аптека\s*№\s*(\d+)$", t)
    if m:
        return f"apteka-{m.group(1)}"

    m = re.match(r"^АПункт[_\s]*№?\s*(\d+)\s*А№?\s*(\d+)$", t)
    if m:
        return f"apunkt-{m.group(1)}-a{m.group(2)}"

    slug = re.sub(r"[^0-9a-zA-Zа-яА-ЯіІїЇєЄ]+", "-", t).strip("-").lower()
    return slug or "warehouse"


def fetch_warehouse_names():
    env = mysql_read_env(OPENCART_ENV_PATH)
    conn = mysql_connect(env)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT warehouses_id, title FROM oc_warehouses_description")
            rows = cur.fetchall()
    finally:
        conn.close()
    id_by_title = {r["title"]: r["warehouses_id"] for r in rows}
    title_by_id = {r["warehouses_id"]: r["title"] for r in rows}
    return id_by_title, title_by_id


def build_pharmacy_data():
    """Групує сирі дані (перерозподіл, дефектура без донора, скоро
    закінчиться, мертвий вантаж) у словники за warehouse_id — повна
    картина для завідуючої по її аптеці (2026-08-12).

    Одна й та сама аптека-донор часто виявляється найкращим донором для
    ОДНОГО й того ж товару відразу для кількох аптек з дефіцитом — але
    фізичний запас (product_warehouse.quantity) у неї один, а не окремий
    на кожен запит. Без об'єднання це виглядало б так, ніби донор може
    віддати повний обсяг кожній аптеці окремо (напр. "у вас є 2 шт" тричі
    поспіль трьом різним аптекам) — тому нижче такі випадки схлопуються в
    один рядок зі списком усіх, хто просить, і явним попередженням, якщо
    прохачів більше, ніж є одиниць товару.

    MIN_RECENT_SOLD_QTY фільтрує і "привезти", і "замовити постачальнику"
    — товар, проданий 1 раз за квартал, не вартий витрат персоналу на
    фізичне перенесення чи окреме замовлення (запит користувача 2026-08-12).
    """
    id_by_title, title_by_id = fetch_warehouse_names()
    redistribution_data = get_redistribution_data()
    defectura_data = get_defectura_per_pharmacy_data()
    low_stock_data = get_low_stock_data()

    redistribution_source = redistribution_data["redistribution_source"]
    filtered_redistribution = [
        r for r in redistribution_data["redistribution"]
        if _passes_velocity_filter(r, redistribution_source)
    ]

    needs = {}
    outgoing_map = {}  # (donor_wid, product_id) -> merged entry

    for r in filtered_redistribution:
        needs_wid = r["warehouse_id"]
        needs.setdefault(needs_wid, []).append(r)

        # Тільки рекомендований (найбільший запас) донор реально має
        # комусь щось віддавати — решта донорів у списку лише запасні
        # варіанти для показу на сторінці аптеки, що потребує товар.
        top_donor = r["donors"][0]
        donor_wid = id_by_title.get(top_donor["label"])
        if donor_wid is None:
            continue

        key = (donor_wid, r["product_id"])
        entry = outgoing_map.setdefault(key, {
            "product_name": r["product_name"],
            "model": r["model"],
            "quantity": top_donor["quantity"],
            "needed_by": [],
        })
        entry["needed_by"].append(r["needs_at"])

    outgoing = {}
    for (donor_wid, _product_id), entry in outgoing_map.items():
        outgoing.setdefault(donor_wid, []).append(entry)

    # Найбільший запас у цієї аптеки — найвищий пріоритет віддати (найбільше
    # "зайвого" й найпростіше виділити на передачу).
    for items in outgoing.values():
        items.sort(key=lambda o: o["quantity"], reverse=True)

    # Дефектура БЕЗ донора — товар, якого взагалі ніде нема в мережі, тільки
    # замовляти у постачальника. Повний дефектура-список цієї аптеки мінус
    # ті, що вже отримали донора (needs), і той самий фільтр швидкості.
    no_donor = {}
    for wid, entry in defectura_data["pharmacies"].items():
        have_donor_ids = {r["product_id"] for r in needs.get(wid, [])}
        remaining = [
            item for item in entry["items"]
            if item["product_id"] not in have_donor_ids
            and _passes_velocity_filter(item, defectura_data["data_source"])
        ]
        for item in remaining:
            item["suggest_order"] = _suggest_order_qty(item.get("recent_sold_qty"))
        if remaining:
            no_donor[wid] = remaining

    # Мертвий вантаж САМЕ В ЦІЙ аптеці — сортуємо за грн-вартістю, якщо є
    # (daily-рівень), інакше за кількістю (fallback-рівні без ціни).
    dead_stock_by_wid = {}
    for row in redistribution_data["dead_stock"]:
        dead_stock_by_wid.setdefault(row["warehouse_id"], []).append(row)
    for rows in dead_stock_by_wid.values():
        if redistribution_data["dead_stock_source"] == "daily":
            rows.sort(key=lambda r: -r.get("value", 0.0))
        else:
            rows.sort(key=lambda r: -r["quantity"])

    # Скоро закінчиться САМЕ В ЦІЙ аптеці — вже відсортовано глобально за
    # days_left (найтерміновіше перше), групування зберігає порядок.
    low_stock_by_wid = {}
    for a in low_stock_data["alerts"]:
        a["suggest_order"] = _suggest_order_qty(a.get("sold_qty"))
        low_stock_by_wid.setdefault(a["warehouse_id"], []).append(a)

    seasonality_by_wid = _build_seasonality_by_warehouse(title_by_id.keys())

    return {
        "needs": needs,
        "outgoing": outgoing,
        "no_donor": no_donor,
        "dead_stock": dead_stock_by_wid,
        "low_stock": low_stock_by_wid,
        "seasonality": seasonality_by_wid,
        "title_by_id": title_by_id,
        "redistribution_source": redistribution_source,
        "defectura_source": defectura_data["data_source"],
        "dead_stock_source": redistribution_data["dead_stock_source"],
    }


def _suggest_order_qty(recent_sold_qty):
    """Орієнтовна кількість для замовлення — скільки продано за останній
    місяць (розділ "Продано/30дн" дефектури чи "sold_qty" alerts), округлено
    ВГОРУ до цілої упаковки (правило користувача 2026-08-25). Свідомо НЕ
    повна SafetyStock-формула з ABC/XYZ-проєкту (SafetyStock, ROP тощо) —
    та лишається ілюстративною/неприйнятою, тут проста практична підказка
    на основі реального темпу продажу."""
    if not recent_sold_qty:
        return None
    return math.ceil(recent_sold_qty)


def _build_seasonality_by_warehouse(warehouse_ids):
    """Мережевий прогноз сезонності (seasonality.py) + залишок САМЕ В ЦІЙ
    аптеці для кожного товару з топ-категорій (той самий підхід, що й
    ad-hoc звіт для Аптеки №13, 2026-08-26)."""
    data = get_seasonality_data()
    categories = data.get("categories") or []
    if not categories:
        return {}

    product_ids = [p["product_id"] for c in categories for p in c["products"]]
    stock_by_pw = {}
    if product_ids:
        env = mysql_read_env(OPENCART_ENV_PATH)
        conn = mysql_connect(env)
        try:
            with conn.cursor() as cur:
                fmt = ",".join(["%s"] * len(product_ids))
                cur.execute(
                    f"SELECT product_id, warehouse_id, quantity FROM product_warehouse "
                    f"WHERE product_id IN ({fmt})",
                    product_ids,
                )
                for row in cur.fetchall():
                    stock_by_pw[(row["product_id"], row["warehouse_id"])] = float(row["quantity"])
        finally:
            conn.close()

    by_wid = {}
    for wid in warehouse_ids:
        wid_categories = []
        for c in categories:
            products = [
                {**p, "stock_here": stock_by_pw.get((p["product_id"], wid), 0.0)}
                for p in c["products"]
            ]
            wid_categories.append({**c, "products": products})
        by_wid[wid] = wid_categories
    return by_wid


def render_pharmacy_page(label, needs_items, outgoing_items, no_donor_items, dead_stock_items,
                          low_stock_items, defectura_source, dead_stock_source, updated_at,
                          seasonality_categories=None):
    e = html.escape

    if needs_items:
        rows = []
        for r in needs_items:
            model = r["model"] or f"id{r['product_id']}"
            donor = r["donors"][0]
            stability = r.get("demand_stability")
            stability_note = f" <span class='note'>({stability}/6 міс. стабільно)</span>" if stability is not None else ""
            rows.append(
                f"<tr><td>{e(r['product_name'])}{stability_note} <span class='note'>({e(model)})</span></td>"
                f"<td class='wrap-cell'>Взяти з <strong>{e(donor['label'])}</strong> "
                f"(надлишок {donor['quantity']:g} шт)</td></tr>"
            )
        needs_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th>Звідки привезти</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        needs_table = "<p class='note'>Сьогодні привозити нічого не треба.</p>"

    if no_donor_items:
        rows = []
        for item in no_donor_items:
            model = item["model"] or f"id{item['product_id']}"
            if defectura_source == "daily":
                cell = f"~{fmt_money(item['est_daily_loss'])}/день недоотримано"
            else:
                cell = f"продано {item['sold_qty']:g} шт"
            order_cell = f"{item['suggest_order']:g} шт" if item.get("suggest_order") else "—"
            rows.append(
                f"<tr><td>{e(item['product_name'])} <span class='note'>({e(model)})</span></td>"
                f"<td class='wrap-cell'>{e(cell)}</td>"
                f"<td class='num strong-cell'>{e(order_cell)}</td></tr>"
            )
        no_donor_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th>Втрата</th><th class='num'>Замовити</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        no_donor_table = "<p class='note'>Нема товарів, які треба замовляти окремо — все або є, або можна перенести.</p>"

    if low_stock_items:
        rows = []
        for a in low_stock_items:
            model = a["model"] or f"id{a['product_id']}"
            seasonal_note = " 🌦" if a.get("seasonal_adjusted") else ""
            order_cell = f"{a['suggest_order']:g} шт" if a.get("suggest_order") else "—"
            rows.append(
                f"<tr><td>{e(a['product_name'])} <span class='note'>({e(model)})</span></td>"
                f"<td class='num'>{a['quantity']:g} шт</td>"
                f"<td class='num'>~{a['days_left']:.1f} дн.{seasonal_note}</td>"
                f"<td class='num strong-cell'>{e(order_cell)}</td></tr>"
            )
        low_stock_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th class='num'>Залишок</th><th class='num'>Днів</th><th class='num'>Замовити</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        low_stock_table = "<p class='note'>Нічого не закінчується найближчим часом.</p>"

    # --- Зведене "Замовити зараз" — дефектура + скоро закінчиться разом,
    # найважливіше нагору (грошова втрата, потім терміновість), той самий
    # підхід, що й ad-hoc звіт "Порада для Аптеки №13" (2026-08-26).
    order_now = []
    for item in no_donor_items:
        if not item.get("suggest_order"):
            continue
        order_now.append({
            "name": item["product_name"], "model": item["model"] or f"id{item['product_id']}",
            "badge": "<span class='badge badge-urgent'>0 на складі</span>",
            "qty": item["suggest_order"], "money": item.get("est_daily_loss", 0) * 30, "urgency": 0,
        })
    for a in low_stock_items:
        if not a.get("suggest_order"):
            continue
        season_badge = " <span class='badge badge-season'>🌦 сезон</span>" if a.get("seasonal_adjusted") else ""
        order_now.append({
            "name": a["product_name"], "model": a["model"] or f"id{a['product_id']}",
            "badge": f"<span class='badge badge-warn'>{a['days_left']:.1f} дн.</span>{season_badge}",
            "qty": a["suggest_order"], "money": None, "urgency": a["days_left"],
        })
    order_now.sort(key=lambda x: (0 if x["money"] is None else -x["money"], x["urgency"]))

    if order_now:
        rows = [
            f"<tr><td>{e(it['name'])} <span class='note'>({e(it['model'])})</span></td>"
            f"<td>{it['badge']}</td>"
            f"<td class='num strong-cell'>{it['qty']:g} шт</td></tr>"
            for it in order_now
        ]
        order_now_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th>Статус</th><th class='num'>Скільки</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        order_now_table = "<p class='note'>Сьогодні нічого термінового замовляти не треба.</p>"

    if seasonality_categories:
        blocks = []
        for c in seasonality_categories:
            prod_rows = []
            for p in c["products"]:
                model = p["model"] or f"id{p['product_id']}"
                low_flag = " <span class='pct-down'>мало!</span>" if p["stock_here"] <= 2 else ""
                prod_rows.append(
                    f"<tr><td>{e(p['product_name'])} <span class='note'>({e(model)})</span></td>"
                    f"<td class='num'>+{p['growth_pct']:.0f}%</td>"
                    f"<td class='num'>{p['stock_here']:g} шт{low_flag}</td></tr>"
                )
            blocks.append(
                f"<h3>{e(c['name'])} <span class='note'>(торік цей період +{c['growth_pct']:.0f}%)</span></h3>"
                "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
                "<th class='num'>Ріст торік</th><th class='num'>Залишок тут</th></tr></thead>"
                f"<tbody>{''.join(prod_rows)}</tbody></table></div>"
            )
        seasonality_html = "".join(blocks)
    else:
        seasonality_html = "<p class='note'>Немає даних про сезонні категорії, що зростають найближчим часом.</p>"

    if dead_stock_items:
        rows = []
        total_value = 0.0
        for row in dead_stock_items:
            model = row["model"] or f"id{row['product_id']}"
            value_cell = f"{fmt_money(row['value'])}" if dead_stock_source == "daily" else ""
            if dead_stock_source == "daily":
                total_value += row.get("value", 0.0)
            rows.append(
                f"<tr><td>{e(row['product_name'])} <span class='note'>({e(model)})</span></td>"
                f"<td class='num'>{row['quantity']:g} шт</td>"
                f"<td class='num'>{e(value_cell)}</td></tr>"
            )
        dead_stock_summary = (
            f"<p><strong>Разом: {len(dead_stock_items)} поз."
            + (f", {e(fmt_money(total_value))}" if dead_stock_source == "daily" else "")
            + "</strong></p>"
        )
        dead_stock_table = dead_stock_summary + (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th class='num'>Залишок</th><th class='num'>Вартість</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        dead_stock_table = "<p class='note'>Мертвого вантажу не знайдено.</p>"

    if outgoing_items:
        rows = []
        for o in outgoing_items:
            model = o["model"] or ""
            model_html = f" <span class='note'>({e(model)})</span>" if model else ""
            requesters = o["needed_by"]
            requesters_html = ", ".join(f"<strong>{e(label)}</strong>" for label in requesters)
            if len(requesters) > 1:
                warning = (
                    f" <span class='pct-down'>⚠️ {len(requesters)} аптеки просять, "
                    f"а надлишку лише {o['quantity']:g} шт — на всіх не вистачить, "
                    f"вирішіть самі кому й скільки</span>"
                )
            else:
                warning = ""
            rows.append(
                f"<tr><td>{e(o['product_name'])}{model_html}</td>"
                f"<td class='wrap-cell'>Потрібно в {requesters_html}"
                f" — надлишок {o['quantity']:g} шт (понад ваш власний запас){warning}</td></tr>"
            )
        outgoing_table = (
            "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
            "<th>Кому віддати</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        outgoing_table = "<p class='note'>Сьогодні у вас нічого не просять.</p>"

    defectura_month_loss = sum(
        item.get("est_daily_loss", 0) for item in no_donor_items
    ) * 30 if defectura_source == "daily" else None
    dead_stock_total_value = sum(
        row.get("value", 0.0) for row in dead_stock_items
    ) if dead_stock_source == "daily" else None

    stat_cards = [
        f"<div class='stat'><div class='n'>{len(no_donor_items)}</div><div class='l'>позицій дефектури (0 на складі)</div></div>",
    ]
    if defectura_month_loss is not None:
        stat_cards.append(f"<div class='stat'><div class='n'>{e(fmt_money(defectura_month_loss))}</div><div class='l'>недоотримано за місяць</div></div>")
    stat_cards.append(f"<div class='stat'><div class='n'>{len(dead_stock_items)}</div><div class='l'>позицій неліквіду</div></div>")
    if dead_stock_total_value is not None:
        stat_cards.append(f"<div class='stat'><div class='n'>{e(fmt_money(dead_stock_total_value))}</div><div class='l'>заморожено в неліквіді</div></div>")
    statrow_html = "<div class='statrow'>" + "".join(stat_cards) + "</div>"

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(label)} — що зробити</title>
{FONT_LINKS}
<style>{TRANSFER_PAGE_STYLE}</style>
</head>
<body>
<div class="wrap">
    <div class="masthead">
        <span class="eyebrow">{e(label)} · {updated_at}</span>
        <h1>Що зробити сьогодні</h1>
        <div class="sub">Дефектура, неліквіди, товар, що скоро закінчиться, перенесення між аптеками й сезонні сигнали — на основі реальних продажів. <a href="./index.html">← усі аптеки</a></div>
    </div>

    {statrow_html}

    <section>
        <div class="sec-head"><h2>🛒 Замовити зараз</h2>
        <p class="note">Найтерміновіше — дефектура (0 на складі) і те, що скоро закінчиться, разом. Кількість — орієнтовна, округлена вгору, за реальними продажами тут за останній місяць.</p></div>
        {order_now_table}
    </section>

    <section>
        <div class="sec-head"><h2>📥 Привезти сюди</h2>
        <p class="note">Товару тут 0, але в іншій аптеці є надлишок (донор лишає собі запас на {MIN_DONOR_RESERVE_DAYS} дн. власного споживання — показано лише те, що понад цей запас). Береться до уваги, лише якщо товар продавався тут ≥{MIN_RECENT_SOLD_QTY} шт за останні 30 дн. Відсортовано за стабільністю попиту САМЕ ТУТ (X/6 — у скількох з останніх 6 місяців товар справді продавався).</p></div>
        {needs_table}
    </section>

    <section>
        <div class="sec-head"><h2>🛒 Дефектура (ніде взяти)</h2>
        <p class="note">Товару тут 0, продавався тут хоч раз за останні 90 дн., але ніде в мережі немає надлишку для перенесення — лишається тільки замовити постачальнику. "Втрата" = ціна тут × середня швидкість продажу тут за останні 30 дн.</p></div>
        {no_donor_table}
    </section>

    <section>
        <div class="sec-head"><h2>⏳ Скоро закінчиться</h2>
        <p class="note">Залишок &gt;0, але закінчиться менш ніж за {DAYS_THRESHOLD} дн. при середній швидкості продажу тут за останні 30 дн. (мінімум {MIN_SOLD_TOTAL} шт за цей час, інакше не показується). 🌦 — швидкість скоригована на очікуваний сезонний ріст (торішній період).</p></div>
        {low_stock_table}
    </section>

    <section>
        <div class="sec-head"><h2>🧊 Неліквіди</h2>
        <p class="note">Залишок ≥1 шт, але 0 продажів САМЕ ТУТ за останні {DEAD_STOCK_DAYS} дн. (rolling-вікно, зсувається на день з кожним новим запуском). Краще перерозподілити чи знизити ціну, ніж замовляти ще.</p></div>
        {dead_stock_table}
    </section>

    <section>
        <div class="sec-head"><h2>📤 Забрати звідси</h2>
        <p class="note">Тут є надлишок цього товару (понад {MIN_DONOR_RESERVE_DAYS}-денний власний запас), і він потрібен в іншій аптеці з дефектурою.</p></div>
        {outgoing_table}
    </section>

    <section>
        <div class="sec-head"><h2>🌦 Сезонність</h2>
        <p class="note">Категорії, що торік у цей самий час найближчим часом входили в сезонний ріст — тому варто очікувати підвищений попит і на них цього року. "мало!" — залишок тут ≤2 шт напередодні очікуваного росту.</p></div>
        {seasonality_html}
    </section>

    <div class="footer-notes">
        <p>Автоматична сторінка, генерується без участі LLM, оновлюється щодня. "Продається" — реальні продажі саме в цій аптеці.</p>
        <p>"Замовити" — орієнтовна кількість, округлена вгору до цілої упаковки, на основі реальних продажів тут за останній місяць. Не є остаточним замовленням постачальнику.</p>
    </div>
</div>
</body>
</html>
"""


def render_index_page(pharmacy_ids, title_by_id, updated_at, no_donor=None, low_stock=None):
    e = html.escape
    no_donor = no_donor or {}
    low_stock = low_stock or {}
    cards = []
    for wid in sorted(pharmacy_ids, key=lambda w: title_by_id.get(w, str(w))):
        label = title_by_id.get(wid, f"Склад {wid}")
        slug = slugify_title(label)
        order_count = len([x for x in no_donor.get(wid, []) if x.get("suggest_order")]) + \
            len([x for x in low_stock.get(wid, []) if x.get("suggest_order")])
        badge = f"<span class='badge badge-urgent'>{order_count} замовити</span>" if order_count else ""
        cards.append(
            f"<a class='pharmacy-card' href='{slug}.html'>"
            f"<span class='pharmacy-name'>{e(label)}</span>{badge}</a>"
        )
    grid_html = "<div class='pharmacy-grid'>" + "".join(cards) + "</div>"

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Перенесення по аптеках</title>
{FONT_LINKS}
<style>{TRANSFER_PAGE_STYLE}
.pharmacy-grid {{ display: grid; grid-template-columns: repeat(auto-fill,minmax(200px,1fr)); gap: 10px; }}
.pharmacy-card {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; box-shadow: var(--shadow); text-decoration: none; color: var(--ink); font-weight: 600; }}
.pharmacy-card:hover {{ border-color: var(--teal); }}
</style>
</head>
<body>
<div class="wrap">
    <div class="masthead">
        <span class="eyebrow">Гармонія 2000 · {updated_at}</span>
        <h1>Перенесення по аптеках</h1>
        <div class="sub">Обери свою аптеку — дефектура, неліквіди, скоро закінчиться, сезонність і що замовити.</div>
    </div>
    {grid_html}
</div>
</body>
</html>
"""


def main():
    data = build_pharmacy_data()
    needs, outgoing = data["needs"], data["outgoing"]
    no_donor, dead_stock, low_stock = data["no_donor"], data["dead_stock"], data["low_stock"]
    seasonality = data["seasonality"]
    title_by_id = data["title_by_id"]
    updated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    TRANSFERS_DIR.mkdir(exist_ok=True)

    all_ids = set(needs) | set(outgoing) | set(no_donor) | set(dead_stock) | set(low_stock)
    for wid in all_ids:
        label = title_by_id.get(wid, f"Склад {wid}")
        page = render_pharmacy_page(
            label, needs.get(wid, []), outgoing.get(wid, []),
            no_donor.get(wid, []), dead_stock.get(wid, []), low_stock.get(wid, []),
            data["defectura_source"], data["dead_stock_source"], updated_at,
            seasonality.get(wid, []),
        )
        path = TRANSFERS_DIR / f"{slugify_title(label)}.html"
        path.write_text(page, encoding="utf-8")
        print(
            f"wrote {path} ({len(needs.get(wid, []))} needs, {len(outgoing.get(wid, []))} outgoing, "
            f"{len(no_donor.get(wid, []))} no_donor, {len(dead_stock.get(wid, []))} dead_stock, "
            f"{len(low_stock.get(wid, []))} low_stock)"
        )

    index_page = render_index_page(all_ids, title_by_id, updated_at, no_donor, low_stock)
    (TRANSFERS_DIR / "index.html").write_text(index_page, encoding="utf-8")
    print(f"wrote {TRANSFERS_DIR / 'index.html'} ({len(all_ids)} pharmacies)")
    print(f"Base URL: {BASE_URL}/")


if __name__ == "__main__":
    main()

```

---

## 17. blog_seo_check.py — разовий SEO-звіт

`scripts/blog_seo_check.py`

Без класів. `CHANGE_DATE`, `ARTICLES` (словник з ключами `match`/`published`)
— константи, що описують конкретні дві статті блогу й дату зміни title;
значення взяті вручну з реального кейсу, не обчислюються. `gsc_client(env)`
— той самий патерн авторизації Search Console, що й у `daily_report.py`, але
локальний (модуль ніде не імпортується іншими файлами — це одноразовий скрипт).
`totals`/`top_queries` викликають `svc.searchanalytics().query(...)` з різними
`startDate`/`endDate`, обчисленими відносно `CHANGE_DATE`, щоб порівняти "до"
і "після" зміни заголовка.

```python
#!/usr/bin/env python3
"""Blog SEO before/after check for apteka.g24.ua.

Compares Search Console performance for the two blog articles whose meta titles
were rewritten on 2026-08-18, so we can see whether CTR actually improved.

  id 54  melatonin      — title changed 18.08 (published 28.07)
  id 59  dexpanthenol   — published 18.08 with the new-style title

Usage:  python3 blog_seo_check.py
"""
import os
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CHANGE_DATE = date(2026, 8, 18)          # day the titles were rewritten
ARTICLES = {
    "МЕЛАТОНІН (заголовок змінено 18.08)": {
        "match": "melatonin-shchonochi",
        "published": date(2026, 7, 28),
    },
    "ДЕКСПАНТЕНОЛ (опубліковано 18.08)": {
        "match": "dekspantenol-nauka",
        "published": date(2026, 8, 18),
    },
}


def load_env():
    env = {}
    for line in Path(os.path.expanduser("~/connectors/google-ads/.env")).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def gsc_client(env):
    creds = Credentials(
        None,
        refresh_token=env["GOOGLE_SEARCH_CONSOLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=env["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def totals(svc, site, match, start, end):
    """Impressions/clicks/position for one page over a date range."""
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "dimensionFilterGroups": [
            {"filters": [{"dimension": "page", "operator": "contains", "expression": match}]}
        ],
        "rowLimit": 25,
    }
    rows = svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
    imp = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    # impression-weighted average position
    pos = sum(r["position"] * r["impressions"] for r in rows) / imp if imp else 0.0
    days = (end - start).days + 1
    return {"imp": imp, "clicks": clicks, "ctr": clicks / imp * 100 if imp else 0.0,
            "pos": pos, "days": days, "imp_day": imp / days if days else 0.0}


def top_queries(svc, site, match, start, end, limit=8):
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "dimensionFilterGroups": [
            {"filters": [{"dimension": "page", "operator": "contains", "expression": match}]}
        ],
        "rowLimit": 200,
    }
    rows = svc.searchanalytics().query(siteUrl=site, body=body).execute().get("rows", [])
    rows.sort(key=lambda r: -r["impressions"])
    return rows[:limit]


def fmt(label, t):
    return (f"  {label:<8} покази={t['imp']:>6.0f} ({t['imp_day']:>5.1f}/день)  "
            f"кліки={t['clicks']:>4.0f}  CTR={t['ctr']:>5.2f}%  поз={t['pos']:>4.1f}  [{t['days']} дн]")


def main():
    env = load_env()
    svc = gsc_client(env)
    site = env["GOOGLE_SEARCH_CONSOLE_SITE_URL"]
    # GSC lags 2-3 days; use the freshest day that plausibly has data
    end = date.today() - timedelta(days=2)

    print("=" * 78)
    print(f"BLOG SEO: до/після зміни заголовків (18.08).  Дані GSC по {end.isoformat()}")
    print("=" * 78)

    for name, cfg in ARTICLES.items():
        print(f"\n### {name}")
        before_start = cfg["published"]
        before_end = CHANGE_DATE - timedelta(days=1)
        after_start = CHANGE_DATE + timedelta(days=1)

        if before_end >= before_start:
            b = totals(svc, site, cfg["match"], before_start, before_end)
            print(fmt("ДО:", b))
        else:
            b = None
            print("  ДО:      (стаття опублікована в день зміни — бази для порівняння немає)")

        if end >= after_start:
            a = totals(svc, site, cfg["match"], after_start, end)
            print(fmt("ПІСЛЯ:", a))
            if b and b["imp"] and a["imp"]:
                d_ctr = a["ctr"] - b["ctr"]
                d_day = (a["imp_day"] - b["imp_day"]) / b["imp_day"] * 100 if b["imp_day"] else 0
                arrow = "▲" if d_ctr > 0 else ("▼" if d_ctr < 0 else "=")
                print(f"  ЗМІНА:   CTR {arrow} {d_ctr:+.2f} п.п.   показів/день {d_day:+.0f}%")
        else:
            print("  ПІСЛЯ:   даних ще немає (GSC відстає на 2-3 дні)")

        q = top_queries(svc, site, cfg["match"], after_start if end >= after_start else before_start, end)
        if q:
            print("  топ-запити:")
            for r in q:
                print(f"     {r['keys'][0][:42]:44} покази={r['impressions']:5.0f} "
                      f"кліки={r['clicks']:3.0f} поз={r['position']:5.1f}")
        else:
            print("  топ-запити: (немає)")

    print("\nПримітка: лічильник переглядів у БД сайту рахує ботів — орієнтуйся на GSC/GA4.")


if __name__ == "__main__":
    main()

```

---

## 18. daily_report.py — оркестратор щоденного звіту

`scripts/daily_report.py`

Без класів. Тут же, у топі файлу, робиться `sys.path.insert(0, str(SCRIPT_DIR))`
і прямий `import opencart_sales`/`meta_ads`/`google_ads`/`anr_sales`/
`pharma_news`/`report_text_formatter` — тобто це не пакет із `__init__.py`, а
плоска тека скриптів, і саме тому шлях до неї доводиться додавати вручну в
`sys.path`, щоб імпорти між сусідніми файлами взагалі спрацювали.
`_safe_fetch(label, fallback, fn, *args, **kwargs)` — це загальна обгортка
"виклич і не впади", яку кожен блок `generate_report` використовує для кожного
зовнішнього джерела; сам `fallback` (наприклад, порожній список чи
`"available": False`) підбирається окремо під кожне джерело в місці виклику.
`_apteky_data`/`_site_data`/`_analytics_data`/`_gsc_data`/`_pharma_news_data` —
приватні адаптери "сирі дані джерела → форма для рендера", кожен зі своєю
конкретною бізнес-логікою (наприклад, `_site_data` навмисно тримає обидва числа
й "сайтове", і "підтверджене АНР", а не замінює одне іншим). `render_report_html`
(~260 рядків) — увесь HTML/CSS звіту прямим f-string/конкатенацією, без
шаблонізатора; кольори дельт (`pct-up`/`pct-down`/`pct-flat`) визначаються
функцією `pct_change_value`, винесеною окремо, щоб той самий поріг ±5% не
дублювався по коду. `generate_report`/`main` — вхідні точки для запуску
вручну (`python3 daily_report.py`) і для виклику з бота (`bot.py` імпортує
`daily_report` як модуль і викликає `generate_report()` напряму).

```python
#!/usr/bin/env python3
"""Generate a daily Markdown report from GA4, Search Console, Facebook Marketing,
Google Ads, and the OpenCart sales database.

Read-only: makes no changes anywhere, only fetches data and writes a report
to connectors/reports/<date>.md.

Run with the venv that already has the required packages installed:
    cd connectors/google-ads && source .venv/bin/activate && cd -
    python3 connectors/scripts/daily_report.py
"""
import html
import re
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
import opencart_sales  # noqa: E402
import meta_ads  # noqa: E402
import google_ads  # noqa: E402
import anr_sales  # noqa: E402
import pharma_news  # noqa: E402
import report_text_formatter  # noqa: E402
ENV_PATH = CONNECTORS_DIR / "google-ads" / ".env"
REPORTS_DIR = CONNECTORS_DIR / "reports"

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _safe_fetch(label, fallback, fn, *args, **kwargs):
    """Runs fn(*args, **kwargs); on any exception, logs it to stderr (so it
    still shows up in the cron output) and returns fallback instead of
    propagating — so one flaky source (a transient API 400/500, a timeout)
    doesn't take down the whole report and block delivery of every other
    section along with it."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        print(f"[{label}] fetch failed, using fallback:", file=sys.stderr)
        traceback.print_exc()
        return fallback


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def make_credentials(env, refresh_token_key, scopes):
    return Credentials(
        token=None,
        refresh_token=env[refresh_token_key],
        token_uri=TOKEN_URI,
        client_id=env["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=env["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=scopes,
    )


def fetch_ga4_active_users(env, target_date):
    creds = make_credentials(
        env, "GOOGLE_ANALYTICS_REFRESH_TOKEN",
        ["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    property_id = env["GOOGLE_ANALYTICS_PROPERTY_ID"]

    iso = target_date.isoformat()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=iso, end_date=iso)],
        metrics=[Metric(name="activeUsers")],
    )
    response = client.run_report(request)
    if response.rows:
        return int(response.rows[0].metric_values[0].value)
    return 0


def fetch_search_console_top_queries(env, target_date, limit=10, max_lookback_days=5):
    """Search Console data typically lags 2-3 days behind today. If the
    requested date has no data yet, fall back to the most recent date that
    does, and report which date was actually used.
    """
    creds = make_credentials(
        env, "GOOGLE_SEARCH_CONSOLE_REFRESH_TOKEN",
        ["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)
    site_url = env["GOOGLE_SEARCH_CONSOLE_SITE_URL"]

    for offset in range(max_lookback_days + 1):
        d = target_date - timedelta(days=offset)
        iso = d.isoformat()
        body = {
            "startDate": iso,
            "endDate": iso,
            "dimensions": ["query"],
            "rowLimit": limit,
        }
        response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = response.get("rows", [])
        if rows:
            return rows, d
    return [], target_date


def pct_change_value(old, new):
    """Returns (formatted_text, css_class) for the HTML report.
    css_class is 'pct-up' (green, >=+5%), 'pct-down' (red, <=-5%), or
    'pct-flat' (gray, everything in between / no data).
    """
    if old == 0:
        if new == 0:
            return "н/д", "pct-flat"
        return "+∞%", "pct-up"
    change = (new - old) / old * 100
    sign = "+" if change >= 0 else ""
    text = f"{sign}{change:.1f}%"
    if change >= 5:
        return text, "pct-up"
    if change <= -5:
        return text, "pct-down"
    return text, "pct-flat"


def _apteky_data(anr_data):
    if not anr_data["available"]:
        return {"available": False, "date": anr_data["date"].isoformat()}
    return {
        "available": True,
        "date": anr_data["date"].isoformat(),
        "revenue": anr_data["network_total_sales"],
        "markup": anr_data["network_total_markup"],
        "top5": [
            {"name": b["label"], "revenue": b["total_sales"]}
            for b in anr_data["branches"][:5]
        ],
    }


def _site_data(opencart_data, anr_data):
    if not opencart_data.get("available", True):
        return {
            "available": False,
            "orders_yesterday": 0, "orders_day_before": 0, "sales_amount_yesterday": 0,
            "avg_check_7d": 0, "orders_count_7d": 0,
            "anr_available": anr_data["available"],
            "anr_confirmed_amount": anr_data.get("site_revenue"),
            "anr_confirmed_count": anr_data.get("site_receipts_count"),
            "anr_pickup": anr_data.get("site_pickup_count"),
            "anr_delivery": anr_data.get("site_delivery_count"),
            "top5": [],
        }
    return {
        "available": True,
        "orders_yesterday": opencart_data["orders_yesterday"],
        "orders_day_before": opencart_data["orders_day_before"],
        "sales_amount_yesterday": opencart_data["sales_yesterday"],
        "avg_check_7d": opencart_data["avg_check"],
        "orders_count_7d": opencart_data["orders_7d"],
        "anr_available": anr_data["available"],
        "anr_confirmed_amount": anr_data.get("site_revenue"),
        "anr_confirmed_count": anr_data.get("site_receipts_count"),
        "anr_pickup": anr_data.get("site_pickup_count"),
        "anr_delivery": anr_data.get("site_delivery_count"),
        "top5": [
            {"name": p["name"], "qty": p["quantity"], "amount": p["revenue"]}
            for p in opencart_data["top_products"][:5]
        ],
    }


def _analytics_data(ga4):
    return {
        "available": ga4.get("available", True),
        "users_yesterday": ga4["yesterday"],
        "users_day_before": ga4["day_before"],
    }


def _gsc_data(gsc_rows, gsc_date, yesterday, available=True):
    note = None
    if not available:
        note = "Технічна примітка: Search Console API тимчасово недоступний."
    elif gsc_date != yesterday:
        note = (
            f"Технічна примітка: Search Console API має типову затримку 2-3 дні — дані за "
            f"вчора ({yesterday.isoformat()}) ще недоступні, показано останню доступну дату "
            f"({gsc_date.isoformat()})."
        )
    return {
        "date": gsc_date.isoformat(),
        "rows": [
            {
                "query": row["keys"][0],
                "clicks": row["clicks"],
                "impressions": row["impressions"],
                "ctr": row["ctr"],
                "position": row["position"],
            }
            for row in gsc_rows
        ],
        "note": note,
    }


def _pharma_news_data(report_date):
    """apteka.ua is a third-party site — a network hiccup there shouldn't
    break the whole report, so failures degrade to an empty section."""
    try:
        data = pharma_news.get_data(report_date)
    except Exception:
        print("Failed to fetch pharma news:", file=sys.stderr)
        traceback.print_exc()
        return {"date": (report_date - timedelta(days=1)).isoformat(), "items": []}
    return {"date": data["date"].isoformat(), "items": data["items"]}


HTML_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 32px 16px 64px;
    background: #f5f5f7;
    color: #1c1c1e;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    line-height: 1.45;
}
.container { max-width: 700px; margin: 0 auto; }
h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 24px;
}
h2 {
    font-size: 19px;
    font-weight: 600;
    margin: 40px 0 14px;
    color: #1c1c1e;
}
h2:first-of-type { margin-top: 0; }
.cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 8px;
}
.card {
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    padding: 16px;
}
.card .value {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
}
.card .label {
    font-size: 12px;
    color: #6e6e73;
    margin-top: 4px;
}
.card .delta {
    font-size: 12px;
    font-weight: 600;
    margin-top: 6px;
    display: inline-block;
}
.pct-up { color: #1a8a3e; }
.pct-down { color: #d1332f; }
.pct-flat { color: #8a8a8e; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; }
table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 12px;
    overflow: hidden;
    font-size: 13px;
}
th, td {
    text-align: left;
    padding: 8px 6px;
    border-bottom: 1px solid #eeeef0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
th {
    background: #fafafa;
    font-weight: 600;
    color: #3a3a3c;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) { background: #fafafa; }
td:first-child, th:first-child { white-space: normal; overflow-wrap: break-word; width: 46%; }
td.num, th.num { text-align: right; }
.section { margin-bottom: 8px; }
.note {
    font-size: 12px;
    color: #9a9a9e;
    margin: 8px 0 0;
}
.footer-notes {
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid #e5e5ea;
    font-size: 11px;
    color: #aeaeb2;
}
.footer-notes p { margin: 4px 0; }
"""


def render_report_html(
    report_date, ga4, gsc_rows, gsc_date, opencart_data, anr_data, meta_data, google_data,
    pharma_news_data,
):
    yesterday = report_date - timedelta(days=1)
    day_before = report_date - timedelta(days=2)
    e = html.escape

    orders_delta_text, orders_delta_class = pct_change_value(
        opencart_data["orders_day_before"], opencart_data["orders_yesterday"]
    )
    ga4_delta_text, ga4_delta_class = pct_change_value(ga4["day_before"], ga4["yesterday"])

    anr_confirmed_card = ""
    if anr_data["available"]:
        anr_confirmed_card = f"""
        <div class="card">
            <div class="value">{anr_data['site_revenue']:,.0f}</div>
            <div class="label">Підтверджено АНР, грн</div>
            <div class="delta">{anr_data['site_receipts_count']} реальних чеків</div>
        </div>
        """

    if not opencart_data.get("available", True):
        sales_cards = "<p class='note'>Дані OpenCart тимчасово недоступні.</p>"
    else:
        sales_cards = f"""
        <div class="cards">
            <div class="card">
                <div class="value">{opencart_data['orders_yesterday']}</div>
                <div class="label">Замовлень вчора</div>
                <div class="delta {orders_delta_class}">{orders_delta_text}</div>
            </div>
            <div class="card">
                <div class="value">{opencart_data['sales_yesterday']:,.0f}</div>
                <div class="label">Оформлено на сайті, грн</div>
            </div>
            {anr_confirmed_card}
            <div class="card">
                <div class="value">{opencart_data['avg_check']:,.0f}</div>
                <div class="label">Середній чек, 7 днів</div>
            </div>
        </div>
        """.replace(",", " ")

    if anr_data["available"]:
        anr_cards = f"""
    <div class="cards">
        <div class="card">
            <div class="value">{anr_data['network_total_sales']:,.0f}</div>
            <div class="label">Виручка по мережі, грн</div>
        </div>
        <div class="card">
            <div class="value">{anr_data['network_total_markup']:,.0f}</div>
            <div class="label">Націнка по мережі, грн</div>
        </div>
        <div class="card">
            <div class="value">{anr_data['site_receipts_count']}</div>
            <div class="label">Чеків з сайту (реальних)</div>
        </div>
    </div>
        """.replace(",", " ")
        anr_branch_rows = "".join(
            f"<tr><td>{e(b['label'])}</td><td class='num'>{b['total_sales']:,.0f}</td>"
            f"<td class='num'>{b['total_markup']:,.0f}</td></tr>".replace(",", " ")
            for b in anr_data["branches"]
        )
        anr_branches_table = (
            "<div class='table-wrap'><table><thead><tr><th>Аптека</th>"
            "<th class='num'>Виручка, грн</th><th class='num'>Націнка, грн</th></tr></thead>"
            f"<tbody>{anr_branch_rows}</tbody></table></div>"
        )
    else:
        anr_cards = ""
        anr_branches_table = "<p class='note'>Даних від АНР за цю дату ще немає.</p>"

    if not ga4.get("available", True):
        ga4_cards = "<p class='note'>Дані GA4 тимчасово недоступні.</p>"
    else:
        ga4_cards = f"""
        <div class="cards">
            <div class="card">
                <div class="value">{ga4['yesterday']}</div>
                <div class="label">Активні користувачі</div>
                <div class="delta {ga4_delta_class}">{ga4_delta_text}</div>
            </div>
        </div>
        """.replace(",", " ")

    top_products_rows = "".join(
        f"<tr><td>{e(p['name'])}</td><td class='num'>{p['quantity']}</td>"
        f"<td class='num'>{p['revenue']:,.2f}</td></tr>".replace(",", " ")
        for p in opencart_data["top_products"]
    )
    top_products_table = (
        "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
        "<th class='num'>Кількість</th><th class='num'>Сума, грн</th></tr></thead>"
        f"<tbody>{top_products_rows}</tbody></table></div>"
        if opencart_data["top_products"]
        else "<p class='note'>Даних немає</p>"
    )

    if not meta_data.get("available", True):
        meta_cards = "<p class='note'>Дані Facebook Ads тимчасово недоступні.</p>"
        meta_campaigns_table = ""
    else:
        meta_cards = f"""
        <div class="cards">
            <div class="card">
                <div class="value">${meta_data['spend_yesterday']:.2f}</div>
                <div class="label">Витрати вчора</div>
            </div>
            <div class="card">
                <div class="value">{meta_data['impressions_yesterday']:,}</div>
                <div class="label">Покази вчора</div>
            </div>
        </div>
        """.replace(",", " ")

        meta_campaign_rows = "".join(
            f"<tr><td>{e(c['name'])}</td><td class='num'>${c['spend']:.2f}</td>"
            f"<td class='num'>{c['impressions']:,}</td></tr>".replace(",", " ")
            for c in meta_data["campaigns"]
        )
        meta_campaigns_table = (
            "<div class='table-wrap'><table><thead><tr><th>Кампанія</th>"
            "<th class='num'>Витрати</th><th class='num'>Покази</th></tr></thead>"
            f"<tbody>{meta_campaign_rows}</tbody></table></div>"
            if meta_data["campaigns"]
            else "<p class='note'>Вчора жодна кампанія не мала витрат.</p>"
        )

    if not google_data.get("available", True):
        google_cards = "<p class='note'>Дані Google Ads тимчасово недоступні.</p>"
        google_campaigns_table = ""
    else:
        google_cards = f"""
        <div class="cards">
            <div class="card">
                <div class="value">{google_data['spend_yesterday']:.2f} грн</div>
                <div class="label">Витрати вчора</div>
            </div>
            <div class="card">
                <div class="value">{google_data['impressions_yesterday']:,}</div>
                <div class="label">Покази вчора</div>
            </div>
        </div>
        """.replace(",", " ")

        google_campaign_rows = "".join(
            f"<tr><td>{e(c['name'])}</td><td class='num'>{c['spend']:.2f} грн</td>"
            f"<td class='num'>{c['impressions']:,}</td></tr>".replace(",", " ")
            for c in google_data["campaigns"]
        )
        google_campaigns_table = (
            "<div class='table-wrap'><table><thead><tr><th>Кампанія</th>"
            "<th class='num'>Витрати</th><th class='num'>Покази</th></tr></thead>"
            f"<tbody>{google_campaign_rows}</tbody></table></div>"
            if google_data["campaigns"]
            else "<p class='note'>Вчора жодна кампанія не мала витрат.</p>"
        )

    if pharma_news_data["items"]:
        pharma_news_html = "<ul>" + "".join(
            f"<li><a href='{e(item['link'])}'>{e(item['title'])}</a></li>"
            for item in pharma_news_data["items"]
        ) + "</ul>"
    else:
        pharma_news_html = "<p class='note'>Новин не знайдено.</p>"

    gsc_note = ""
    if gsc_date != yesterday:
        gsc_note = (
            f"<p class='note'>Дані за вчора ({yesterday.isoformat()}) ще недоступні в Search "
            f"Console API (типова затримка 2-3 дні) — показано останню доступну дату "
            f"({gsc_date.isoformat()}).</p>"
        )

    if gsc_rows:
        gsc_rows_html = "".join(
            f"<tr><td>{e(row['keys'][0])}</td>"
            f"<td class='num'>{row['clicks']}</td>"
            f"<td class='num'>{row['impressions']}</td>"
            f"<td class='num'>{row['ctr'] * 100:.2f}%</td>"
            f"<td class='num'>{row['position']:.1f}</td></tr>"
            for row in gsc_rows
        )
        gsc_table = (
            "<div class='table-wrap'><table><thead><tr><th>Запит</th>"
            "<th class='num'>Кліки</th><th class='num'>Покази</th>"
            "<th class='num'>CTR</th><th class='num'>Позиція</th></tr></thead>"
            f"<tbody>{gsc_rows_html}</tbody></table></div>"
        )
    else:
        gsc_table = "<p class='note'>Даних немає</p>"

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Щоденний звіт — {report_date.isoformat()}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<div class="container">
    <h1>Щоденний звіт — {report_date.isoformat()}</h1>

    <h2>🏪 Реальні продажі по аптеках (АНР)</h2>
    <div class="section">
        {anr_cards}
        {anr_branches_table}
    </div>

    <h2>🛒 Сайт: Продажі</h2>
    <div class="section">
        {sales_cards}
    </div>

    <h2>Топ-10 товарів за кількістю продажів (7 днів)</h2>
    <div class="section">
        {top_products_table}
    </div>

    <h2>📈 Аналітика сайту (GA4)</h2>
    <div class="section">
        {ga4_cards}
    </div>

    <h2>📣 Facebook Marketing</h2>
    <div class="section">
        {meta_cards}
        {meta_campaigns_table}
    </div>

    <h2>🔎 Google Ads</h2>
    <div class="section">
        {google_cards}
        {google_campaigns_table}
    </div>

    <h2>🔍 Search Console: топ-10 запитів</h2>
    <div class="section">
        {gsc_table}
    </div>

    <h2>💊 Новини фармації ({pharma_news_data['date']})</h2>
    <div class="section">
        {pharma_news_html}
    </div>

    <div class="footer-notes">
        {gsc_note}
    </div>
</div>
</body>
</html>
"""


def generate_report(report_date=None):
    """Fetch all sources and write both the Markdown and HTML reports.

    Returns (report_text, compact_text, md_path, html_path). report_text is
    the full version (also saved to the .md file) — compact_text is the
    same but without the Search Console section (used for the Telegram chat
    message; the full HTML is still attached separately).
    """
    if report_date is None:
        report_date = date.today()

    env = read_env(ENV_PATH)
    yesterday = report_date - timedelta(days=1)
    day_before = report_date - timedelta(days=2)

    def _fetch_ga4():
        return {
            "yesterday": fetch_ga4_active_users(env, yesterday),
            "day_before": fetch_ga4_active_users(env, day_before),
            "available": True,
        }

    ga4 = _safe_fetch(
        "GA4", {"yesterday": 0, "day_before": 0, "available": False}, _fetch_ga4
    )

    def _fetch_gsc():
        rows, d = fetch_search_console_top_queries(env, yesterday, limit=10)
        return {"rows": rows, "date": d, "available": True}

    gsc_result = _safe_fetch(
        "SearchConsole", {"rows": [], "date": yesterday, "available": False}, _fetch_gsc
    )
    gsc_rows, gsc_date, gsc_available = gsc_result["rows"], gsc_result["date"], gsc_result["available"]

    opencart_data = _safe_fetch(
        "OpenCart",
        {
            "available": False, "yesterday": yesterday, "day_before": day_before,
            "orders_yesterday": 0, "orders_day_before": 0, "sales_yesterday": 0,
            "top_products": [], "avg_check": 0, "orders_7d": 0,
        },
        opencart_sales.get_data, report_date,
    )
    anr_data = _safe_fetch(
        "ANR", {"available": False, "date": yesterday}, anr_sales.get_data, report_date
    )
    meta_data = _safe_fetch(
        "MetaAds",
        {"yesterday": yesterday, "spend_yesterday": 0, "impressions_yesterday": 0,
         "campaigns": [], "available": False},
        meta_ads.get_data, report_date,
    )
    google_data = _safe_fetch(
        "GoogleAds",
        {"yesterday": yesterday, "spend_yesterday": 0, "impressions_yesterday": 0,
         "campaigns": [], "available": False},
        google_ads.get_data, report_date,
    )

    report_data = {
        "apteky": _apteky_data(anr_data),
        "site": _site_data(opencart_data, anr_data),
        "analytics": _analytics_data(ga4),
        "facebook": meta_data,
        "google_ads": google_data,
    }
    report_date_str = report_date.strftime("%d.%m.%Y")
    gsc_data = _gsc_data(gsc_rows, gsc_date, yesterday, available=gsc_available)
    pharma_news_data = _pharma_news_data(report_date)

    report_text = report_text_formatter.build_report(
        report_data, report_date_str, gsc=gsc_data, pharma_news=pharma_news_data
    )
    compact_text = report_text_formatter.build_report(
        report_data, report_date_str, gsc=None, pharma_news=pharma_news_data, compact=True
    )
    report_html = render_report_html(
        report_date, ga4, gsc_rows, gsc_date, opencart_data, anr_data, meta_data, google_data,
        pharma_news_data,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"{report_date.isoformat()}.md"
    md_path.write_text(report_text, encoding="utf-8")
    html_path = REPORTS_DIR / f"{report_date.isoformat()}.html"
    html_path.write_text(report_html, encoding="utf-8")

    return report_text, compact_text, md_path, html_path


def main():
    report_text, compact_text, md_path, html_path = generate_report()
    print(f"Report written to {md_path}")
    print(f"HTML report written to {html_path}")
    print()
    print(report_text)


if __name__ == "__main__":
    main()

```

---

## 19. monthly_report.py — оркестратор місячного звіту

`scripts/monthly_report.py`

Без класів. Не дублює логіку джерел — імпортує ті самі
`opencart_sales`/`anr_sales`/`meta_ads`/`google_ads`, але викликає їхні
`*_range`/`get_monthly_data` варіанти, і той самий `report_text_formatter`
для узгодженого текстового стилю. `month_bounds(report_date=None)` і
`_prev_month_bounds(first_day, last_day)` — чиста календарна арифметика
(перший/останній день попереднього місяця відносно переданої дати, за
замовчуванням — `date.today()`). `current_month_to_date_bounds(report_date=None)`
— окремий режим "з початку поточного місяця по вчора", для запитів на вимогу.
`get_data(report_date=None, start=None, end=None)` — єдина точка входу для
обох режимів: якщо `start`/`end` не передані, використовується
`month_bounds()`. `render_text`/`render_html`/`generate_report` — той самий
патерн, що й у `daily_report.py`, з людинозрозумілим україномовним іменем
файлу результату.

```python
#!/usr/bin/env python3
"""Monthly rollup report — sent once a month (1st, alongside the daily
report) summarizing the calendar month that just ended: site sales, real
ANR pharmacy revenue, GA4 users, Facebook + Google Ads spend, each with a
month-over-month delta, top-10 lists, and (HTML only) a daily-dynamics chart
per source.

Reuses the same per-source modules as the daily report (opencart_sales,
anr_sales, meta_ads, google_ads) via their *_monthly / *_range functions,
and report_text_formatter's plain-text formatting helpers for a consistent
look with the daily Telegram report.
"""
import html
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
REPORTS_DIR = CONNECTORS_DIR / "reports"
GA4_ENV_PATH = CONNECTORS_DIR / "google-ads" / ".env"

sys.path.insert(0, str(SCRIPT_DIR))
import opencart_sales  # noqa: E402
import anr_sales  # noqa: E402
import meta_ads  # noqa: E402
import google_ads  # noqa: E402
import report_text_formatter as fmt  # noqa: E402

UKRAINIAN_MONTHS = [
    "", "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def month_bounds(report_date=None):
    """Returns (first_day, last_day) of the calendar month *before*
    report_date's month — i.e. "the month that just ended", robust to
    whichever day this actually happens to run on."""
    if report_date is None:
        report_date = date.today()
    last_day_prev = report_date.replace(day=1) - timedelta(days=1)
    first_day_prev = last_day_prev.replace(day=1)
    return first_day_prev, last_day_prev


def current_month_to_date_bounds(report_date=None):
    """Returns (first_day, last_day) for the *current, still in-progress*
    month, up through yesterday — same "vчора" cutoff convention as the
    daily report, so "today" (incomplete) never shows up as a data point."""
    if report_date is None:
        report_date = date.today()
    first_day = report_date.replace(day=1)
    last_day = report_date - timedelta(days=1)
    if last_day < first_day:
        # report_date is the 1st itself — nothing to show yet this month.
        last_day = first_day
    return first_day, last_day


def _prev_month_bounds(first_day, last_day):
    prev_last = first_day - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    return prev_first, prev_last


def fetch_ga4_monthly(start, end):
    env = _read_env(GA4_ENV_PATH)
    creds = Credentials(
        token=None,
        refresh_token=env["GOOGLE_ANALYTICS_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=env["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=env["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    property_id = env["GOOGLE_ANALYTICS_PROPERTY_ID"]

    total_req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        metrics=[Metric(name="activeUsers")],
    )
    total_resp = client.run_report(total_req)
    total_users = int(total_resp.rows[0].metric_values[0].value) if total_resp.rows else 0

    return {"total_users": total_users}


def get_data(report_date=None, start=None, end=None):
    """By default aggregates the previous complete calendar month. Pass an
    explicit (start, end) — e.g. from current_month_to_date_bounds() — to
    aggregate a different range instead (the month-over-month comparison
    still uses the calendar month immediately before `start`)."""
    if start is None or end is None:
        start, end = month_bounds(report_date)
    prev_start, prev_end = _prev_month_bounds(start, end)
    days_in_month = (end - start).days + 1

    # --- Сайт (OpenCart) ---
    oc_env = opencart_sales.read_env(opencart_sales.ENV_PATH)
    oc_conn = opencart_sales.connect(oc_env)
    try:
        orders_total = opencart_sales.fetch_order_count_range(oc_conn, start, end)
        orders_prev = opencart_sales.fetch_order_count_range(oc_conn, prev_start, prev_end)
        sales_total = opencart_sales.fetch_total_sales_range(oc_conn, start, end)
        sales_prev = opencart_sales.fetch_total_sales_range(oc_conn, prev_start, prev_end)
        top10_products = opencart_sales.fetch_top_products_range(oc_conn, start, end, limit=10)
    finally:
        oc_conn.close()

    site = {
        "orders_total": orders_total,
        "orders_prev": orders_prev,
        "sales_total": sales_total,
        "sales_prev": sales_prev,
        "top10_products": [
            {"name": r["product_name"], "quantity": int(r["total_quantity"]), "revenue": float(r["total_revenue"])}
            for r in top10_products
        ],
    }

    # --- Аптеки (АНР) ---
    anr = anr_sales.get_monthly_data(start, end)

    # --- GA4 ---
    ga4 = fetch_ga4_monthly(start, end)
    ga4_prev = fetch_ga4_monthly(prev_start, prev_end)
    ga4["total_users_prev"] = ga4_prev["total_users"]

    # --- Facebook ---
    facebook = meta_ads.get_monthly_data(start, end)
    facebook_prev = meta_ads.get_monthly_data(prev_start, prev_end)
    facebook["spend_prev"] = facebook_prev["spend_total"]

    # --- Google Ads ---
    google = google_ads.get_monthly_data(start, end)
    google_prev = google_ads.get_monthly_data(prev_start, prev_end)
    google["spend_prev"] = google_prev["spend_total"]

    calendar_last_day = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    is_partial = end < calendar_last_day
    month_label = f"{UKRAINIAN_MONTHS[start.month]} {start.year}"
    if is_partial:
        month_label += f" (станом на {end.day:02d}.{end.month:02d})"

    return {
        "month_label": month_label,
        "is_partial": is_partial,
        "start": start,
        "end": end,
        "days_in_month": days_in_month,
        "site": site,
        "anr": anr,
        "ga4": ga4,
        "facebook": facebook,
        "google_ads": google,
    }


# ------------------------------------------------------------------
# Текстовий рендер (для Telegram) — та сама стилістика, що й у
# report_text_formatter.py (щоденний звіт)
# ------------------------------------------------------------------

def render_text(data):
    lines = []
    lines.append(f"📊 ГАРМОНІЯ 2000 — ПІДСУМКИ МІСЯЦЯ: {data['month_label'].upper()}")
    lines.append(fmt.bar())
    lines.append("")

    anr = data["anr"]
    lines.append("🏪 ПРОДАЖІ ПО АПТЕКАХ (АНР)")
    lines.append(fmt.divider())
    if anr["available"]:
        lines.append(f"Виручка за місяць   {fmt.fmt_currency(anr['network_total_sales'])}")
        lines.append(f"Націнка за місяць   {fmt.fmt_currency(anr['network_total_markup'])}")
        lines.append(f"Дані є за {anr['days_available']} з {anr['days_in_range']} днів місяця")
        lines.append("")
        lines.append("Топ-10 аптек за виручкою:")
        for i, b in enumerate(anr["branches"][:10], start=1):
            lines.append(f" {i}. {b['label']:<38} {fmt.fmt_currency(b['total_sales']):>12}")
    else:
        lines.append("(даних від АНР за цей місяць немає)")
    lines.append("")

    site = data["site"]
    lines.append("🛒 САЙТ: ПРОДАЖІ")
    lines.append(fmt.divider())
    lines.append(
        f"Замовлень за місяць  {site['orders_total']:<5} "
        f"{fmt.delta_arrow(site['orders_total'], site['orders_prev'], period_label='попередній місяць')}"
    )
    lines.append(
        f"Оформлено на сайті   {fmt.fmt_currency(site['sales_total'])}  "
        f"{fmt.delta_arrow(site['sales_total'], site['sales_prev'], period_label='попередній місяць')}"
    )
    if anr["available"]:
        lines.append(
            f"Підтверджено АНР (реальні чеки)  {fmt.fmt_currency(anr['site_revenue'])} "
            f"— {anr['site_receipts_count']} чеків"
        )
    else:
        lines.append("Підтверджено АНР: дані ще не надійшли")
    lines.append("")
    lines.append("Топ-10 товарів за місяць:")
    for i, p in enumerate(site["top10_products"], start=1):
        name = fmt.truncate(p["name"])
        lines.append(
            f" {i}. {name:<{fmt.PRODUCT_NAME_MAX_LEN}} {p['quantity']:>3} шт · {fmt.fmt_currency(p['revenue']):>9}"
        )
    lines.append("")

    ga4 = data["ga4"]
    lines.append("📈 АНАЛІТИКА САЙТУ (GA4)")
    lines.append(fmt.divider())
    lines.append(
        f"Унікальних користувачів за місяць  {ga4['total_users']:<5} "
        f"{fmt.delta_arrow(ga4['total_users'], ga4['total_users_prev'], period_label='попередній місяць')}"
    )
    lines.append("")

    fb = data["facebook"]
    lines.append("📣 FACEBOOK MARKETING")
    lines.append(fmt.divider())
    lines.append(
        f"Витрати за місяць   {fmt.fmt_usd(fb['spend_total'])}  "
        f"{fmt.delta_arrow(fb['spend_total'], fb['spend_prev'], period_label='попередній місяць')}"
    )
    lines.append(f"Покази за місяць    {fmt.fmt_num(fb['impressions_total'])}")
    lines.append("")
    if fb["campaigns"]:
        lines.append("Топ кампаній за витратами:")
        for c in fb["campaigns"][:5]:
            name = fmt.short_campaign_name(c["name"])
            lines.append(f" • {name:<{fmt.CAMPAIGN_NAME_MAX_LEN}} {fmt.fmt_usd(c['spend']):>8}")
    lines.append("")

    ga = data["google_ads"]
    lines.append("🔎 GOOGLE ADS")
    lines.append(fmt.divider())
    lines.append(
        f"Витрати за місяць   {fmt.fmt_currency(ga['spend_total'], decimals=2)}  "
        f"{fmt.delta_arrow(ga['spend_total'], ga['spend_prev'], period_label='попередній місяць')}"
    )
    lines.append(f"Покази за місяць    {fmt.fmt_num(ga['impressions_total'])}")
    lines.append("")
    if ga["campaigns"]:
        lines.append("Топ кампаній за витратами:")
        for c in ga["campaigns"][:5]:
            name = fmt.short_campaign_name(c["name"], fmt.GOOGLE_ADS_SHORT_NAMES)
            lines.append(f" • {name:<{fmt.CAMPAIGN_NAME_MAX_LEN}} {fmt.fmt_currency(c['spend'], decimals=2):>10}")

    lines.append("")
    lines.append(fmt.bar())
    return "\n".join(lines)


# ------------------------------------------------------------------
# HTML-рендер (inline CSS, без зовнішніх бібліотек)
# ------------------------------------------------------------------

HTML_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    margin: 0; padding: 32px 16px 64px; background: #f5f5f7; color: #1c1c1e;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; line-height: 1.45;
}
.container { max-width: 760px; margin: 0 auto; }
h1 { font-size: 22px; font-weight: 600; margin: 0 0 24px; }
h2 { font-size: 19px; font-weight: 600; margin: 40px 0 14px; }
h2:first-of-type { margin-top: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 8px; }
.card { background: #ffffff; border: 1px solid #e5e5ea; border-radius: 12px; padding: 16px; }
.card .value { font-size: 24px; font-weight: 700; line-height: 1.2; }
.card .label { font-size: 12px; color: #6e6e73; margin-top: 4px; }
.card .delta { font-size: 12px; font-weight: 600; margin-top: 6px; display: inline-block; }
.pct-up { color: #1a8a3e; } .pct-down { color: #d1332f; } .pct-flat { color: #8a8a8e; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 12px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; background: #ffffff; border: 1px solid #e5e5ea; border-radius: 12px; overflow: hidden; font-size: 13px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #eeeef0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
th { background: #fafafa; font-weight: 600; color: #3a3a3c; font-size: 11px; text-transform: uppercase; letter-spacing: 0.02em; }
tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) { background: #fafafa; }
td:first-child, th:first-child { white-space: normal; overflow-wrap: break-word; width: 46%; }
td.num, th.num { text-align: right; }
.section { margin-bottom: 8px; }
.note { font-size: 12px; color: #9a9a9e; margin: 8px 0 0; }
"""


def _pct_change_value(old, new):
    if old == 0:
        return ("н/д", "pct-flat") if new == 0 else ("+∞%", "pct-up")
    change = (new - old) / old * 100
    sign = "+" if change >= 0 else ""
    text = f"{sign}{change:.1f}%"
    if change >= 5:
        return text, "pct-up"
    if change <= -5:
        return text, "pct-down"
    return text, "pct-flat"


def render_html(data):
    e = html.escape
    site, anr, ga4, fb, ga = data["site"], data["anr"], data["ga4"], data["facebook"], data["google_ads"]

    orders_delta, orders_cls = _pct_change_value(site["orders_prev"], site["orders_total"])
    sales_delta, sales_cls = _pct_change_value(site["sales_prev"], site["sales_total"])
    users_delta, users_cls = _pct_change_value(ga4["total_users_prev"], ga4["total_users"])
    fb_delta, fb_cls = _pct_change_value(fb["spend_prev"], fb["spend_total"])
    ga_delta, ga_cls = _pct_change_value(ga["spend_prev"], ga["spend_total"])

    anr_site_confirmed_card = ""
    if anr["available"]:
        anr_site_confirmed_card = f"""
            <div class="card"><div class="value">{anr['site_revenue']:,.0f}</div><div class="label">Підтверджено АНР, грн</div>
            <div class="delta">{anr['site_receipts_count']} реальних чеків</div></div>
        """.replace(",", " ")

    anr_cards = ""
    anr_table = "<p class='note'>Даних від АНР за цей місяць немає.</p>"
    if anr["available"]:
        anr_cards = f"""
        <div class="cards">
            <div class="card"><div class="value">{anr['network_total_sales']:,.0f}</div><div class="label">Виручка за місяць, грн</div></div>
            <div class="card"><div class="value">{anr['network_total_markup']:,.0f}</div><div class="label">Націнка за місяць, грн</div></div>
            <div class="card"><div class="value">{anr['days_available']}/{anr['days_in_range']}</div><div class="label">Днів з даними</div></div>
        </div>
        """.replace(",", " ")
        anr_rows = "".join(
            f"<tr><td>{e(b['label'])}</td><td class='num'>{b['total_sales']:,.0f}</td>"
            f"<td class='num'>{b['total_markup']:,.0f}</td></tr>".replace(",", " ")
            for b in anr["branches"]
        )
        anr_table = (
            "<div class='table-wrap'><table><thead><tr><th>Аптека</th>"
            "<th class='num'>Виручка, грн</th><th class='num'>Націнка, грн</th></tr></thead>"
            f"<tbody>{anr_rows}</tbody></table></div>"
        )

    site_products_rows = "".join(
        f"<tr><td>{e(p['name'])}</td><td class='num'>{p['quantity']}</td><td class='num'>{p['revenue']:,.2f}</td></tr>".replace(",", " ")
        for p in site["top10_products"]
    )
    site_products_table = (
        "<div class='table-wrap'><table><thead><tr><th>Товар</th>"
        "<th class='num'>Кількість</th><th class='num'>Сума, грн</th></tr></thead>"
        f"<tbody>{site_products_rows}</tbody></table></div>"
        if site["top10_products"] else "<p class='note'>Даних немає</p>"
    )

    fb_rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td class='num'>${c['spend']:.2f}</td><td class='num'>{c['impressions']:,}</td></tr>".replace(",", " ")
        for c in fb["campaigns"]
    )
    fb_table = (
        "<div class='table-wrap'><table><thead><tr><th>Кампанія</th>"
        "<th class='num'>Витрати</th><th class='num'>Покази</th></tr></thead>"
        f"<tbody>{fb_rows}</tbody></table></div>"
    ) if fb["campaigns"] else "<p class='note'>Витрат не було.</p>"

    ga_rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td class='num'>{c['spend']:.2f} грн</td><td class='num'>{c['impressions']:,}</td></tr>".replace(",", " ")
        for c in ga["campaigns"]
    )
    ga_table = (
        "<div class='table-wrap'><table><thead><tr><th>Кампанія</th>"
        "<th class='num'>Витрати</th><th class='num'>Покази</th></tr></thead>"
        f"<tbody>{ga_rows}</tbody></table></div>"
    ) if ga["campaigns"] else "<p class='note'>Витрат не було.</p>"

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Місячний звіт — {data['month_label']}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<div class="container">
    <h1>📊 Підсумки місяця — {data['month_label']}</h1>

    <h2>🏪 Продажі по аптеках (АНР)</h2>
    <div class="section">
        {anr_cards}
        {anr_table}
    </div>

    <h2>🛒 Сайт: Продажі</h2>
    <div class="section">
        <div class="cards">
            <div class="card"><div class="value">{site['orders_total']}</div><div class="label">Замовлень за місяць</div><div class="delta {orders_cls}">{orders_delta}</div></div>
            <div class="card"><div class="value">{site['sales_total']:,.0f}</div><div class="label">Оформлено на сайті, грн</div><div class="delta {sales_cls}">{sales_delta}</div></div>
            {anr_site_confirmed_card}
        </div>
    </div>

    <h2>Топ-10 товарів за місяць</h2>
    <div class="section">{site_products_table}</div>

    <h2>📈 Аналітика сайту (GA4)</h2>
    <div class="section">
        <div class="cards">
            <div class="card"><div class="value">{ga4['total_users']:,}</div><div class="label">Унікальних користувачів</div><div class="delta {users_cls}">{users_delta}</div></div>
        </div>
    </div>

    <h2>📣 Facebook Marketing</h2>
    <div class="section">
        <div class="cards">
            <div class="card"><div class="value">${fb['spend_total']:.2f}</div><div class="label">Витрати за місяць</div><div class="delta {fb_cls}">{fb_delta}</div></div>
            <div class="card"><div class="value">{fb['impressions_total']:,}</div><div class="label">Покази за місяць</div></div>
        </div>
        {fb_table}
    </div>

    <h2>🔎 Google Ads</h2>
    <div class="section">
        <div class="cards">
            <div class="card"><div class="value">{ga['spend_total']:,.0f}</div><div class="label">Витрати за місяць, грн</div><div class="delta {ga_cls}">{ga_delta}</div></div>
            <div class="card"><div class="value">{ga['impressions_total']:,}</div><div class="label">Покази за місяць</div></div>
        </div>
        {ga_table}
    </div>
</div>
</body>
</html>
""".replace(",", " ")


def generate_report(report_date=None, start=None, end=None):
    data = get_data(report_date, start=start, end=end)
    text = render_text(data)
    report_html = render_html(data)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    file_stem = f"Звіт за {UKRAINIAN_MONTHS[data['start'].month]} {data['start'].year}"
    if data["is_partial"]:
        file_stem += f" (до {data['end'].day:02d}.{data['end'].month:02d})"
    md_path = REPORTS_DIR / f"{file_stem}.md"
    md_path.write_text(text, encoding="utf-8")
    html_path = REPORTS_DIR / f"{file_stem}.html"
    html_path.write_text(report_html, encoding="utf-8")

    return text, md_path, html_path


def main():
    text, md_path, html_path = generate_report()
    print(f"Report written to {md_path}")
    print(f"HTML report written to {html_path}")
    print()
    print(text)


if __name__ == "__main__":
    main()

```

---

## 20. report_text_formatter.py — текстовий рендер

`scripts/report_text_formatter.py`

Без класів. `WARNING_THRESHOLD_PCT = 30` — єдине джерело істини для порогу
"помітної" зміни, використовується і тут (`is_warning`), і побічно узгоджується
з таким самим порогом в `daily_report.py::pct_change_value` (не імпортується
звідти напряму — значення продубльоване, це видно з того, що обидва файли
задають свою копію константи). `FB_CAMPAIGN_SHORT_NAMES`,
`GOOGLE_CAMPAIGN_SHORT_NAMES` (аналогічний словник нижче в файлі) — вручну
складені мапи "довга назва кампанії → коротка", під конкретні реальні назви
кампаній клієнта. `delta_arrow(current, previous, period_label="позавчора")` —
параметр `period_label` з'явився пізніше (додано заради `monthly_report.py`,
який передає `"попередній місяць""} — видно по тому, що значення за
замовчуванням досі орієнтоване на щоденний звіт. Кожна `build_*_section(d)`
дістає свої значення з переданого словника `d` за конкретними ключами, які
задає відповідний модуль-джерело (`d["yesterday"]`, `d["campaigns"]`, тощо) —
тобто структура вхідних даних цього файлу повністю визначається тим, що
поклали туди `daily_report.py`/`monthly_report.py`.

```python
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

```

---

## 21. telegram-bot/bot.py — інтерактивний бот

`telegram-bot/bot.py`

Без класів (окрім тих, що надає сама бібліотека `python-telegram-bot`:
`Application`, `Update`, `InlineKeyboardMarkup` — це готові класи фреймворка,
у проєкті лише інстанціюються). `UPDATE_BUTTON` — глобальний об'єкт клавіатури,
створюється один раз при імпорті модуля. `TELEGRAM_MAX_MESSAGE_LENGTH = 3900`
— підібраний вручну ліміт (нижче за офіційний ліміт Telegram у 4096 символів,
щоб залишити місце під обгортку code-block). `record_user(update, action)`
дістає `chat.id`/`chat.username`/`chat.first_name` — це поля об'єкта `Update`,
які постачає сама бібліотека `python-telegram-bot` з вхідного вебхука/polling-
відповіді Telegram, а не придумуються в коді. `start`/`update_report` —
асинхронні хендлери (`async def`), зареєстровані в `main()` через
`application.add_handler(...)`; `update_report` викликає синхронний
`daily_report.generate_report` через `asyncio.to_thread(...)`, щоб не
блокувати asyncio-цикл бота.

```python
#!/usr/bin/env python3
"""Telegram bot: "Оновити дані" button that regenerates and sends the daily
report (GA4, Search Console, OpenCart sales).

Open access — anyone with the bot's link can use it (no chat_id allowlist).
Every /start and button press is logged to users.json so it's visible who
has connected. The report contains real sales figures, so keep the bot link
private / don't publish it anywhere public.
"""
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent
ENV_PATH = SCRIPT_DIR / ".env"
USERS_PATH = SCRIPT_DIR / "users.json"
BLOCKED_PATH = SCRIPT_DIR / "blocked_users.json"

sys.path.insert(0, str(CONNECTORS_DIR / "scripts"))
import daily_report  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

UPDATE_BUTTON = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔄 Оновити дані", callback_data="update_report")]]
)

TELEGRAM_MAX_MESSAGE_LENGTH = 3900  # leaves room for the ``` code-block wrapper


def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env


def split_for_telegram(text, limit=TELEGRAM_MAX_MESSAGE_LENGTH):
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks


def load_users():
    if USERS_PATH.exists():
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))
    return {}


def is_blocked(chat_id):
    if not BLOCKED_PATH.exists():
        return False
    blocked = json.loads(BLOCKED_PATH.read_text(encoding="utf-8"))
    return str(chat_id) in blocked


def save_users(users):
    USERS_PATH.write_text(
        json.dumps(users, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def record_user(update: Update, action: str):
    """Log every /start and button press to users.json (chat_id -> profile)."""
    chat = update.effective_chat
    chat_id = str(chat.id)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    users = load_users()
    entry = users.get(chat_id, {"first_seen": now, "requests": 0})
    entry["username"] = chat.username
    entry["first_name"] = chat.first_name
    entry["last_name"] = chat.last_name
    entry["last_seen"] = now
    if action == "update":
        entry["requests"] = entry.get("requests", 0) + 1
    users[chat_id] = entry
    save_users(users)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_blocked(update.effective_chat.id):
        await update.message.reply_text("Доступ до цього бота обмежено.")
        return

    record_user(update, action="start")
    await update.message.reply_text(
        "Привіт! Це бот щоденного звіту apteka.g24.ua (GA4, Search Console, OpenCart).",
        reply_markup=UPDATE_BUTTON,
    )


async def update_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if is_blocked(update.effective_chat.id):
        await query.answer("Доступ обмежено", show_alert=True)
        return

    record_user(update, action="update")

    await query.answer("Генерую звіт...")
    await query.message.reply_text("⏳ Збираю дані з GA4 / Search Console / OpenCart...")

    try:
        report_text, compact_text, md_path, html_path = await asyncio.to_thread(
            daily_report.generate_report
        )
    except Exception as e:
        logger.exception("Failed to generate report")
        await query.message.reply_text(f"❌ Помилка при генерації звіту: {e}")
        return

    for chunk in split_for_telegram(compact_text):
        safe_chunk = chunk.replace("```", "'''")  # code block can't contain its own fence
        await query.message.reply_text(
            f"```\n{safe_chunk}\n```", parse_mode=ParseMode.MARKDOWN
        )

    with open(html_path, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=html_path.name,
            caption="📄 Повна HTML-версія звіту (з Search Console, відкрити в браузері)",
        )

    await query.message.reply_text("Готово ✅", reply_markup=UPDATE_BUTTON)


def main():
    env = read_env(ENV_PATH)
    token = env["TELEGRAM_BOT_TOKEN"]

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(update_report, pattern="^update_report$"))

    logger.info("Bot starting (open access, logging users to %s)", USERS_PATH)
    application.run_polling()


if __name__ == "__main__":
    main()

```

---

## 22. telegram-bot/send_daily_report.py — cron-розсилка щоденного звіту

`telegram-bot/send_daily_report.py`

Без класів. Не використовує `python-telegram-bot` (не потрібен повноцінний
бот-цикл для одноразового запуску) — `send_message`/`send_document` це прямі
`requests.post` до `https://api.telegram.org/bot<TOKEN>/sendMessage` і
`.../sendDocument`. `main()` читає `users.json` (список отримувачів, той самий
файл, що веде `bot.py`) і `blocked_users.json` (виключає заблокованих),
приймає опціональний `sys.argv` для кастомного вступного повідомлення.

```python
#!/usr/bin/env python3
"""Cron entrypoint: generates the daily report and pushes it to every user
who has ever /start-ed the bot (users.json), without needing a button press.

Run via the hosting panel's cron scheduler at 08:00 daily:
    /usr/bin/python3.10 /home/fz453955/reports_bot/telegram-bot/send_daily_report.py

Uses plain HTTP calls to the Telegram Bot API (no running Application needed,
so it works as a one-shot cron job independent of the polling bot process).
"""
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(CONNECTORS_DIR / "scripts"))
import bot as bot_module  # noqa: E402 — reuse read_env/split_for_telegram/load_users
import daily_report  # noqa: E402


def send_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return requests.post(
        url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=30
    )


def send_document(token, chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        return requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"document": f},
            timeout=60,
        )


def main():
    intro = sys.argv[1] if len(sys.argv) > 1 else "📊 Автоматичний щоденний звіт"

    env = bot_module.read_env(bot_module.ENV_PATH)
    token = env["TELEGRAM_BOT_TOKEN"]

    users = bot_module.load_users()
    if not users:
        print("No users registered yet (users.json empty) — nothing to send.")
        return

    report_text, compact_text, md_path, html_path = daily_report.generate_report()

    for chat_id in users:
        if bot_module.is_blocked(chat_id):
            print(f"[{chat_id}] skipped (blocked)")
            continue
        try:
            r = send_message(token, chat_id, intro)
            if not r.ok:
                print(f"[{chat_id}] intro sendMessage failed: {r.text}")

            for chunk in bot_module.split_for_telegram(compact_text):
                safe_chunk = chunk.replace("```", "'''")
                r = send_message(token, chat_id, f"```\n{safe_chunk}\n```")
                if not r.ok:
                    print(f"[{chat_id}] sendMessage failed: {r.text}")

            r = send_document(
                token, chat_id, html_path,
                "📄 Повна HTML-версія звіту (з Search Console, відкрити в браузері)",
            )
            if not r.ok:
                print(f"[{chat_id}] sendDocument failed: {r.text}")
            else:
                print(f"[{chat_id}] sent OK")
        except Exception as e:
            print(f"[{chat_id}] error: {e}")


if __name__ == "__main__":
    main()

```

---

## 23. telegram-bot/send_monthly_report.py — cron-розсилка місячного звіту

`telegram-bot/send_monthly_report.py`

Без класів, структура ідентична `send_daily_report.py`, але викликає
`monthly_report.generate_report()` замість `daily_report.generate_report()`.

```python
#!/usr/bin/env python3
"""Cron entrypoint: generates the monthly rollup report and pushes it to
every registered (non-blocked) user, once a month.

Run via the hosting panel's cron scheduler on the 1st at 08:00, alongside
the daily report:
    /usr/bin/python3.10 /home/fz453955/reports_bot/telegram-bot/send_monthly_report.py

Same one-shot plain-HTTP pattern as send_daily_report.py — no running
Application needed.
"""
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CONNECTORS_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(CONNECTORS_DIR / "scripts"))
import bot as bot_module  # noqa: E402 — reuse read_env/split_for_telegram/load_users/is_blocked
import monthly_report  # noqa: E402


def send_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return requests.post(
        url, data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=30
    )


def send_document(token, chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(file_path, "rb") as f:
        return requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"document": f},
            timeout=60,
        )


def main():
    env = bot_module.read_env(bot_module.ENV_PATH)
    token = env["TELEGRAM_BOT_TOKEN"]

    users = bot_module.load_users()
    if not users:
        print("No users registered yet (users.json empty) — nothing to send.")
        return

    text, md_path, html_path = monthly_report.generate_report()
    start, _ = monthly_report.month_bounds()
    month_label = f"{monthly_report.UKRAINIAN_MONTHS[start.month]} {start.year}"
    intro = f"📊 Місячний звіт готовий: {month_label}"

    for chat_id in users:
        if bot_module.is_blocked(chat_id):
            print(f"[{chat_id}] skipped (blocked)")
            continue
        try:
            r = send_message(token, chat_id, intro)
            if not r.ok:
                print(f"[{chat_id}] intro sendMessage failed: {r.text}")

            for chunk in bot_module.split_for_telegram(text):
                safe_chunk = chunk.replace("```", "'''")
                r = send_message(token, chat_id, f"```\n{safe_chunk}\n```")
                if not r.ok:
                    print(f"[{chat_id}] sendMessage failed: {r.text}")

            r = send_document(
                token, chat_id, html_path,
                "📄 Повна HTML-версія місячного звіту (з графіками, відкрити в браузері)",
            )
            if not r.ok:
                print(f"[{chat_id}] sendDocument failed: {r.text}")
            else:
                print(f"[{chat_id}] sent OK")
        except Exception as e:
            print(f"[{chat_id}] error: {e}")


if __name__ == "__main__":
    main()

```

---

## 24. run_daily_report.sh — bash-обгортка для локального запуску

`scripts/run_daily_report.sh`

Не Python, а `bash`; додано для повноти — це скрипт, який раніше запускав
`launchd` на Mac розробника (локальний бекап-запуск, зайвий після переїзду на
сервер, але залишений). `set -euo pipefail` — стандартна дисципліна bash
(падати на першій помилці, на невизначеній змінній, на помилці в конвеєрі).
Активує venv (`source .../venv/bin/activate`) і запускає `daily_report.py`,
перенаправляючи весь вивід у лог-файл.

```bash
#!/bin/bash
# Wrapper for launchd: activates the venv and runs daily_report.py, logging output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONNECTORS_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$CONNECTORS_DIR/reports/logs"
mkdir -p "$LOG_DIR"

source "$CONNECTORS_DIR/google-ads/.venv/bin/activate"
python3 "$SCRIPT_DIR/daily_report.py" >> "$LOG_DIR/daily_report.log" 2>&1

```

---

