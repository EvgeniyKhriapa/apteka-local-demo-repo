# -*- coding: utf-8 -*-
"""
daily_report.py — локальний аналог daily_report.py з оригінального проєкту.

На відміну від demo-версії з попереднього кроку, тут:
  - текстовий звіт (і повний, і компактний) будується не власним, спрощеним
    форматуванням, а СПРАВЖНІМ, незміненим report_text_formatter.py з
    оригінального репозиторію — той самий build_report(), ті самі секції,
    ті самі формати чисел;
  - єдине джерело даних — локальна SQLite-база demo (scripts/pharmacy_demo.db,
    створена seed_db.py), яка відтворює структуру OpenCart+АНР (товар / філія /
    замовлення);
  - секції, для яких у демо-проєкті немає джерела (GA4-аналітика, Facebook Ads,
    Google Ads), позначаються як "available": False — точнісінько так само,
    як це робить _safe_fetch в оригінальному daily_report.py, коли реальне
    зовнішнє API недоступне. Це не помилка, а чесне відображення того, що
    в цьому локальному демо немає ні рекламних кабінетів, ні GA4-акаунту.
  - Telegram відсутній повністю: замість відправки боту компактна версія
    просто друкується в консоль, а обидва файли (.md і .html) зберігаються
    в reports/.

Запуск:
    python scripts/seed_db.py       # один раз — створити демо-дані
    python scripts/daily_report.py  # генерація звіту (можна запускати щоразу)
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))  # той самий прийом, що й в оригіналі daily_report.py

import report_text_formatter  # справжній, незмінений файл з оригінального проєкту

DB_PATH = SCRIPT_DIR / "pharmacy_demo.db"
REPORTS_DIR = SCRIPT_DIR.parent / "reports"

# Демо-база не моделює собівартість товару, тому справжньої націнки в ній
# нема (на відміну від реального фіду АНР, де markup рахується з собівартості
# постачальника). Для секції "Продажі по аптеках" беремо умовний коефіцієнт,
# щоб секція apteky_section із report_text_formatter.py відображалась
# коректно, без вигадування фейкових грошей — це чесно позначено в назві
# константи і в коментарі.
DEMO_MARKUP_RATE = 0.22


# ------------------------------------------------------------------
# Читання даних з локальної SQLite-бази (аналог opencart_sales.py)
# ------------------------------------------------------------------

def connect():
    if not DB_PATH.exists():
        raise SystemExit(
            f"Базу {DB_PATH} не знайдено. Спершу запустіть: python scripts/seed_db.py"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_order_count(conn, target_date: date) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE order_date = ? AND status = 'paid'",
        (target_date.isoformat(),),
    ).fetchone()
    return row["c"]


def fetch_total_sales(conn, target_date: date) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(oi.quantity * oi.price), 0) AS total
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        WHERE o.order_date = ? AND o.status = 'paid'
        """,
        (target_date.isoformat(),),
    ).fetchone()
    return row["total"]


def fetch_average_check(conn, since_date: date):
    row = conn.execute(
        """
        SELECT AVG(order_total) AS avg_check, COUNT(*) AS orders_count FROM (
            SELECT o.id, SUM(oi.quantity * oi.price) AS order_total
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            WHERE o.order_date >= ? AND o.status = 'paid'
            GROUP BY o.id
        )
        """,
        (since_date.isoformat(),),
    ).fetchone()
    return row["avg_check"] or 0.0, row["orders_count"] or 0


def fetch_top_products(conn, since_date: date, limit: int = 5):
    rows = conn.execute(
        """
        SELECT p.name AS name, SUM(oi.quantity) AS qty,
               SUM(oi.quantity * oi.price) AS amount
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.order_date >= ? AND o.status = 'paid'
        GROUP BY p.id
        ORDER BY qty DESC
        LIMIT ?
        """,
        (since_date.isoformat(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_pharmacy_revenue(conn, target_date: date, limit: int = 5):
    rows = conn.execute(
        """
        SELECT ph.name AS name,
               COALESCE(SUM(oi.quantity * oi.price), 0) AS revenue
        FROM pharmacies ph
        LEFT JOIN orders o ON o.pharmacy_id = ph.id
                           AND o.order_date = ? AND o.status = 'paid'
        LEFT JOIN order_items oi ON oi.order_id = o.id
        GROUP BY ph.id
        ORDER BY revenue DESC
        LIMIT ?
        """,
        (target_date.isoformat(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Побудова data-словника у форматі, який очікує report_text_formatter.build_report
# ------------------------------------------------------------------

def build_apteky_data(conn, report_date: date) -> dict:
    top5 = fetch_pharmacy_revenue(conn, report_date, limit=5)
    total_revenue = sum(p["revenue"] for p in top5)
    return {
        "available": True,
        "date": report_date.isoformat(),
        "revenue": total_revenue,
        "markup": total_revenue * DEMO_MARKUP_RATE,
        "top5": top5,
    }


def build_site_data(conn, report_date: date) -> dict:
    day_before = report_date - timedelta(days=1)
    week_ago = report_date - timedelta(days=7)

    orders_yesterday = fetch_order_count(conn, report_date)
    orders_day_before = fetch_order_count(conn, day_before)
    sales_yesterday = fetch_total_sales(conn, report_date)
    avg_check_7d, orders_count_7d = fetch_average_check(conn, week_ago)
    top5 = fetch_top_products(conn, week_ago, limit=5)

    # У демо є лише одне джерело даних (локальна SQLite-база), тому немає
    # окремого "підтвердження від АНР" на відміну від реального проєкту, де
    # сайтові замовлення (OpenCart) звіряються з реальними закритими чеками
    # (АНР) — тут ці цифри за конструкцією збігаються із замовленнями вчора.
    return {
        "available": True,
        "orders_yesterday": orders_yesterday,
        "orders_day_before": orders_day_before,
        "sales_amount_yesterday": sales_yesterday,
        "avg_check_7d": avg_check_7d,
        "orders_count_7d": orders_count_7d,
        "anr_available": True,
        "anr_confirmed_amount": sales_yesterday,
        "anr_confirmed_count": orders_yesterday,
        "anr_pickup": orders_yesterday,
        "anr_delivery": 0,
        "top5": top5,
    }


def build_report_data(report_date: date) -> dict:
    conn = connect()
    try:
        return {
            "apteky": build_apteky_data(conn, report_date),
            "site": build_site_data(conn, report_date),
            # Немає реального джерела для цих трьох секцій у локальному
            # демо (немає ні GA4-акаунту, ні рекламних кабінетів) — так само,
            # як у справжньому daily_report.py, коли _safe_fetch ловить
            # виняток від зовнішнього API, секція просто позначається
            # недоступною, а решта звіту все одно генерується.
            "analytics": {"available": False},
            "facebook": {"available": False},
            "google_ads": {"available": False},
        }
    finally:
        conn.close()


# ------------------------------------------------------------------
# HTML-рендер: офісний, "не закручений" стиль — тільки стандартний CSS,
# без JS, без зовнішніх бібліотек/CDN, без градієнтів/тіней/округлень.
# Аналог render_report_html() з оригінального daily_report.py, але з іншим,
# навмисно стриманим оформленням (класична ділова таблична верстка).
# ------------------------------------------------------------------

def _fmt(value, decimals=0):
    return report_text_formatter.fmt_num(value, decimals)


def _currency(value, decimals=0):
    return report_text_formatter.fmt_currency(value, decimals=decimals)


def _delta_html(current, previous):
    """Той самий розрахунок, що й delta_arrow(), але як прості ASCII-стрілки
    для офісного HTML (без емодзі — вони не завжди коректно друкуються з
    офісних принтерів/у PDF, тому в HTML-версії свідомо використано текстові
    позначки замість емодзі)."""
    if previous is None or previous == 0:
        return "н/д"
    pct = (current - previous) / previous * 100
    arrow = "▲" if pct > 0.05 else ("▼" if pct < -0.05 else "—")
    sign = "+" if pct > 0 else ""
    return f"{arrow} {sign}{pct:.1f}%"


def render_report_html(data: dict, report_date: date) -> str:
    apteky = data["apteky"]
    site = data["site"]

    apteky_rows = "".join(
        f"<tr><td>{i}</td><td>{row['name']}</td><td class=\"num\">{_currency(row['revenue'])}</td></tr>"
        for i, row in enumerate(apteky["top5"], start=1)
    )

    top_products_rows = "".join(
        f"<tr><td>{i}</td><td>{item['name']}</td>"
        f"<td class=\"num\">{item['qty']}</td>"
        f"<td class=\"num\">{_currency(item['amount'])}</td></tr>"
        for i, item in enumerate(site["top5"], start=1)
    )

    def unavailable_block(title: str) -> str:
        return (
            f'<h2>{title}</h2>'
            f'<p class="muted">Дані недоступні (у локальному демо немає цього джерела).</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<title>Звіт "Гармонія 2000" — {report_date.strftime('%d.%m.%Y')}</title>
<style>
  /* Навмисно стандартний, "офісний" стиль: системні шрифти, чорний текст,
     тонкі лінії таблиць, без кольорових акцентів, тіней чи заокруглень —
     як звичайний друкований діловий звіт. */
  body {{
    font-family: "Calibri", "Segoe UI", Arial, sans-serif;
    color: #000000;
    background: #ffffff;
    max-width: 820px;
    margin: 30px auto;
    padding: 0 20px;
    font-size: 13pt;
    line-height: 1.4;
  }}
  h1 {{
    font-size: 16pt;
    border-bottom: 2px solid #000000;
    padding-bottom: 6px;
    margin-bottom: 4px;
  }}
  .subtitle {{
    font-size: 10pt;
    color: #444444;
    margin-bottom: 20px;
  }}
  h2 {{
    font-size: 13pt;
    margin-top: 26px;
    margin-bottom: 6px;
    border-bottom: 1px solid #999999;
    padding-bottom: 3px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 4px 0;
    font-size: 11pt;
  }}
  th {{
    background: #f0f0f0;
    border: 1px solid #999999;
    padding: 5px 8px;
    text-align: left;
    font-weight: bold;
  }}
  td {{
    border: 1px solid #cccccc;
    padding: 5px 8px;
  }}
  td.num, th.num {{ text-align: right; }}
  .kpi-table td:first-child {{ width: 55%; color: #333333; }}
  .kpi-table td.value {{ font-weight: bold; text-align: right; }}
  .muted {{ color: #666666; font-style: italic; }}
  .footer {{
    margin-top: 30px;
    padding-top: 8px;
    border-top: 1px solid #999999;
    font-size: 9pt;
    color: #666666;
  }}
</style>
</head>
<body>
  <h1>ГАРМОНІЯ 2000 — щоденний звіт</h1>
  <div class="subtitle">За {report_date.strftime('%d.%m.%Y')} · локальний демонстраційний запуск, без Telegram</div>

  <h2>Продажі по аптеках</h2>
  <table class="kpi-table">
    <tr><td>Виручка по мережі</td><td class="value">{_currency(apteky['revenue'])}</td></tr>
    <tr><td>Націнка по мережі (умовно, {DEMO_MARKUP_RATE*100:.0f}%)</td><td class="value">{_currency(apteky['markup'])}</td></tr>
  </table>
  <table>
    <tr><th>#</th><th>Аптека</th><th class="num">Виручка</th></tr>
    {apteky_rows}
  </table>

  <h2>Сайт: продажі</h2>
  <table class="kpi-table">
    <tr><td>Замовлень вчора (позавчора {site['orders_day_before']})</td>
        <td class="value">{site['orders_yesterday']} &nbsp; {_delta_html(site['orders_yesterday'], site['orders_day_before'])}</td></tr>
    <tr><td>Сума продажів вчора</td><td class="value">{_currency(site['sales_amount_yesterday'])}</td></tr>
    <tr><td>Середній чек, 7 днів ({site['orders_count_7d']} замовлень)</td>
        <td class="value">{_currency(site['avg_check_7d'])}</td></tr>
  </table>
  <h2>Топ-5 препаратів (7 днів)</h2>
  <table>
    <tr><th>#</th><th>Препарат</th><th class="num">К-сть</th><th class="num">Сума</th></tr>
    {top_products_rows}
  </table>

  {unavailable_block("Аналітика сайту (GA4)")}
  {unavailable_block("Facebook Marketing")}
  {unavailable_block("Google Ads")}

  <div class="footer">
    Згенеровано локально скриптом scripts/daily_report.py на основі
    scripts/pharmacy_demo.db. Текстова версія звіту побудована оригінальним
    файлом report_text_formatter.py без змін.
  </div>
</body>
</html>"""


# ------------------------------------------------------------------
# Точка входу
# ------------------------------------------------------------------

def generate_report(report_date: date | None = None):
    report_date = report_date or (date.today() - timedelta(days=1))
    data = build_report_data(report_date)

    date_str = report_date.strftime("%d.%m.%Y")
    full_text = report_text_formatter.build_report(data, date_str, compact=False)
    compact_text = report_text_formatter.build_report(data, date_str, compact=True)
    html = render_report_html(data, report_date)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"{report_date.isoformat()}.md"
    html_path = REPORTS_DIR / f"{report_date.isoformat()}.html"
    md_path.write_text(full_text, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    return full_text, compact_text, md_path, html_path


def main():
    full_text, compact_text, md_path, html_path = generate_report()

    print("=" * 60)
    print("КОМПАКТНА ВЕРСІЯ (те, що в оригіналі йшло б у Telegram-чат)")
    print("=" * 60)
    print(compact_text)
    print()
    print(f"Повний текстовий звіт збережено: {md_path}")
    print(f"HTML-звіт збережено:              {html_path}")


if __name__ == "__main__":
    main()
