# apteka.g24.ua reporting system — технічна документація проєкту

Документ описує, **як побудований** проєкт автоматичної звітності для аптечної мережі
«Гармонія 2000» (apteka.g24.ua, OpenCart): якою мовою й модулями написаний, з яких
етапів складався, звідки береться кожен шматок даних і які функції/класи за що
відповідають. Документ складено на основі аналізу вихідного коду репозиторію
(`apteka-g24-reports`, гілка `main`) та супровідного файлу `HANDOFF.md`, у якому
автор проєкту фіксував рішення та причини змін по ходу розробки.

---

## 1. Що це за проєкт і навіщо

Система щодня о 8:00 автоматично:

1. збирає дані з п'яти джерел — бази даних OpenCart, Google Analytics 4, Google
   Search Console, Facebook (Meta) Ads, Google Ads, а також фід реальних продажів
   від стороннього постачальника «АНР»;
2. формує з них два звіти — компактний текстовий (для Telegram) і повний HTML;
3. розсилає їх через Telegram-бота всім користувачам, які підписались.

Окрім щоденного звіту, у репозиторії розвинувся другий, більший блок — **аналітика
залишків**: дефектура (товар закінчився), «скоро закінчиться», перерозподіл між
аптеками, мертвий вантаж (неліквід), сезонність і статичні HTML-сторінки
перенесень для завідуючих аптеками. Це окрема підсистема, що виросла з тієї ж
кодової бази й ділить з нею інфраструктуру (доступ до OpenCart DB, той самий
Telegram-бот, той самий сервер).

Проєкт **не є фреймворком чи вебзастосунком** — це набір самостійних Python-скриптів
(«conectors»/«scripts»), кожен з яких відповідає за одне джерело даних або один
різновид звіту, плюс orchestration-скрипти, що їх викликають і збирають разом.

---

## 2. Технологічний стек

| Складова | Технологія | Навіщо |
|---|---|---|
| Мова | Python 3.10+ (продакшн — `/usr/bin/python3.10` на хостингу) | вся логіка |
| Робота з MySQL (OpenCart) | `pymysql` | читання таблиць `oc_order`, `oc_order_product`, `oc_product`, `oc_warehouses_description`, `product_warehouse` |
| Локальна історія | `sqlite3` (стандартна бібліотека) | власні бази `sales_daily.db`, `stock_history.db`, `stock_drops.db` — накопичена історія, якої немає в жодному зовнішньому джерелі |
| Google API | `google-api-python-client`, `google.analytics.data_v1beta` (GA4 Data API), OAuth2 через `google.oauth2.credentials.Credentials` | GA4, Search Console |
| Google Ads | «сирі» HTTP-запити через `requests` до REST-ендпойнта `googleAds:search` | офіційний `google-ads` SDK свідомо не використаний — досить прямого REST-виклику з `developer-token` |
| Facebook/Meta Ads | `requests` до Graph API (`/insights`) | звіти по кампаніям |
| Excel/1С-вигрузки | `openpyxl` | розбір `.xlsx`-файлів, які вручну вивантажує користувач з 1С |
| XML (АНР-фід) | `xml.etree.ElementTree` (стандартна бібліотека) | розбір щоденних `sales_YYYY-MM-DD.xml` |
| RSS | `xml.etree.ElementTree` + `requests` | новини фармгалузі з `apteka.ua/rss` |
| Telegram-бот | `python-telegram-bot` (`Application`, `CallbackQueryHandler`) | доставка звітів, кнопка «Оновити дані» |
| Формат чисел/таблиць | Python `f-string`-и вручну (без Jinja2/шаблонізаторів) | і текстовий, і HTML-рендеринг звіту зібрані прямим конкатенуванням рядків |

`requirements.txt`:

```
google_api_python_client==2.199.0
openpyxl==3.1.5
protobuf==7.36.0
pymysql==1.2.0
python-telegram-bot==22.8
Requests==2.34.2
```

Помітно, що явного `google-analytics-data` в списку немає окремим рядком — він
тягнеться як залежність `google_api_python_client`/суміжних пакетів; сам виклик
GA4 Data API йде через окремий підпакет `google.analytics.data_v1beta`.

---

## 3. Структура репозиторію

```
apteka-g24-reports/
├── HANDOFF.md                  — журнал рішень проєкту (не код, але ключовий документ)
├── requirements.txt
├── .gitignore                  — .env, *.db/*.sqlite, users.json, reports/ виключені
├── scripts/                    — уся бізнес-логіка, кожен файл = одне джерело/звіт
│   ├── daily_report.py         — оркестратор щоденного звіту (Markdown + HTML)
│   ├── monthly_report.py       — оркестратор місячного звіту
│   ├── report_text_formatter.py— рендер текстової (Telegram) версії щоденного звіту
│   ├── opencart_sales.py       — читання продажів з MySQL OpenCart
│   ├── anr_sales.py            — розбір XML-фіду реальних чеків від АНР
│   ├── meta_ads.py             — Facebook/Meta Ads Graph API
│   ├── google_ads.py           — Google Ads REST API
│   ├── pharma_news.py          — RSS-новини apteka.ua
│   ├── product_categories.py   — категорії товарів OpenCart (для розбивки звітів)
│   ├── sales_1c.py             — разовий знімок продажів з 1С (Excel)
│   ├── sales_daily.py          — поденна історія продажів з 1С (SQLite-накопичувач)
│   ├── stock_snapshot.py       — власний трекер падінь залишків (SQLite)
│   ├── defectura.py            — товар з нульовим залишком там, де зазвичай продається
│   ├── low_stock_alert.py      — товар, що скоро закінчиться (прогноз за темпом продажу)
│   ├── redistribution.py       — перерозподіл між аптеками + мертвий вантаж
│   ├── seasonality.py          — прогноз сезонного попиту за торішнім патерном
│   ├── refusals.py             — аналіз відмов покупцям (SQLite, разовий історичний зріз)
│   ├── stock_history_status.py — щоденний дайджест по залишках (HTML → окремий чат)
│   ├── transfer_pages.py       — статичні HTML-сторінки перенесень на сайті
│   ├── blog_seo_check.py       — разовий SEO-звіт по двох блог-статтях
│   └── run_daily_report.sh     — bash-обгортка для локального launchd-запуску
└── telegram-bot/
    ├── bot.py                  — сам бот (long-polling, кнопка «Оновити дані»)
    ├── send_daily_report.py    — cron-точка входу: розсилка щоденного звіту всім
    └── send_monthly_report.py  — cron-точка входу: розсилка місячного звіту всім
```

Кожен модуль джерела даних (`opencart_sales.py`, `anr_sales.py`, `meta_ads.py`,
`google_ads.py`, `pharma_news.py`) навмисно побудований за єдиним контрактом:

- `read_env(path)` / підключення — власна авторизація;
- `get_data(report_date)` — повертає словник із даними за «вчора» (і часто «позавчора»)
  плюс прапорець `available`;
- `get_monthly_data(start, end)` / `*_range(...)` — те саме, але за діапазон дат
  (для місячного звіту);
- `render_section(...)` — власний текстовий фрагмент (у частини модулів; в інших
  рендеринг централізовано в `report_text_formatter.py`).

Це не оформлено як формальний Python-інтерфейс (`abc.ABC`/протокол) — просто
однакова конвенція іменування функцій, витримана вручну в кожному файлі.

---

## 4. Конфігурація та секрети

Жодних значень credentials немає в коді. Кожне джерело даних читає власний
`.env`-файл (простий `KEY=value`, без бібліотеки `python-dotenv` — парсинг
написаний вручну):

```python
def read_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2)
    return env
```

Ця сама функція (`read_env`) буквально продубльована в `daily_report.py`,
`opencart_sales.py`, `google_ads.py`, `meta_ads.py`, `bot.py`, `monthly_report.py`
(`_read_env`) — між модулями немає спільного `utils.py`, кожен файл самодостатній.

`.gitignore` явно виключає з git усе, що не має туди потрапляти:

```
.env
*/.env
**/.env
*.db / *.sqlite / *.sqlite3
opencart-site/
reports/
users.json
blocked_users.json
```

Шляхи до `.env` будуються відносно розташування самого скрипту через
`Path(__file__).resolve().parent`, а не через жорстко прописаний абсолютний шлях —
завдяки цьому один і той самий код працює і локально, і на сервері, де дерево
папок дзеркальне (`~/connectors/...` локально ↔ `/home/fz453955/reports_bot/...`
на хостингу).

---

## 5. Джерела даних — по одному

### 5.1. OpenCart (MySQL) — `opencart_sales.py`

Пряме, **тільки для читання** підключення до бойової бази магазину:

```python
def connect(env):
    conn = pymysql.connect(
        host=env["DB_HOSTNAME"], user=env["DB_USERNAME"],
        password=env["DB_PASSWORD"], database=env["DB_DATABASE"],
        connect_timeout=10, cursorclass=pymysql.cursors.DictCursor,
    )
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
    return conn
```

`SET SESSION TRANSACTION READ ONLY` — це не просто дисципліна коду (тільки
`SELECT`-и), а захист на рівні самого MySQL: навіть помилковий `UPDATE`/`INSERT`
буде відхилений сервером. Основні функції:

- `fetch_order_count(conn, target_date)`, `fetch_total_sales(conn, target_date)` —
  кількість і сума замовлень за день;
- `fetch_top_products(conn, since_date, limit=10)` — топ товарів за кількістю,
  `JOIN oc_order_product ↔ oc_order`;
- `*_range(conn, start_date, end_date)` — ті самі метрики за період (для
  місячного звіту);
- `fetch_average_check(conn, since_date)` — середній чек за 7 днів;
- `pct_change_emoji(old, new)` — допоміжна функція форматування дельти;
- `get_data(report_date)` — «фасад», що викликає всі попередні функції й
  повертає готовий словник для звіту.

Ключове бізнес-правило зафіксоване константою `VALID_ORDER_FILTER = "order_status_id > 0"`
— статус `0` в OpenCart означає покинутий кошик/непідтверджене оформлення і
виключається з усіх запитів. Таблиці перед першим використанням перевірялись
вручну через `DESCRIBE`/`SHOW TABLES` (задокументовано в `HANDOFF.md` як
загальне правило «ніколи не вгадувати схему»).

### 5.2. АНР — реальні чеки по аптеках — `anr_sales.py`

АНР — стороння система, що щодня кладе XML-файл `sales_YYYY-MM-DD.xml` у
файлову систему сервера (той самий хостинг-акаунт, що й сайт — читання без
мережевого стрибка). Формат — набір тегів `<Sale OrderId=".." Branch=".."
Total=".." Status="paid|refunded" DeliveryType="pickup|delivery" .../>` плюс
блок `<Branches><Branch Name="код" TotalSales=".." TotalMarkup=".."/>...`.

Розбір іде через стандартний `xml.etree.ElementTree`:

```python
def _parse_file(path):
    root = ET.parse(path).getroot()
    sales = [...]          # список чеків
    branches = [...]       # підсумки по кожній аптеці
    paid = [s for s in sales if s["status"] == "paid"]
    refunded = [s for s in sales if s["status"] == "refunded"]
    site_revenue = sum(s["total"] for s in paid) - sum(s["total"] for s in refunded)
    return {...}
```

Особливості, з якими довелось розбиратись під час інтеграції (є в `HANDOFF.md`):

- суми в XML використовують **кому** як десятковий роздільник, а не крапку —
  тому є окрема `_parse_amount(value)`, що замінює `,` на `.` перед `float()`;
- файли мають BOM (byte-order mark) на початку — `ElementTree` парсить це без
  додаткової обробки;
- `Branch` у файлі — це числовий код складу (наприклад `"54160"`), а не назва —
  словник `BRANCH_NAMES` мапить 20 відомих кодів на людські назви
  («Аптека №1 — вул. Руська, 17» тощо), з fallback `"Філія {code}"` для
  невідомого коду замість падіння;
- `DeliveryType` у фіді завжди `"pickup"` — підтверджено користувачем, що це не
  баг, а особливість джерела (АНР не розрізняє доставку).

`get_data(report_date)` бере файл за «вчора»; `get_monthly_data(start, end)`
підсумовує всі наявні файли в діапазоні, пропускаючи відсутні дні без падіння —
і повертає `days_available` окремо від `days_in_range`, щоб виклик міг оцінити
повноту даних.

### 5.3. Google Analytics 4 та Search Console — усередині `daily_report.py`

Обидва джерела автентифікуються через один спільний OAuth-клієнт (`GOOGLE_OAUTH_CLIENT_ID/SECRET`)
з різними refresh-токенами й scope на кожен API:

```python
def make_credentials(env, refresh_token_key, scopes):
    return Credentials(
        token=None, refresh_token=env[refresh_token_key],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=env["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=scopes,
    )
```

- `fetch_ga4_active_users(env, target_date)` — офіційний Python-клієнт
  `BetaAnalyticsDataClient` з пакета `google-analytics-data`, запит
  `RunReportRequest` з метрикою `activeUsers` і діапазоном в один день;
- `fetch_search_console_top_queries(env, target_date, limit=10, max_lookback_days=5)`
  — сервіс `searchconsole v1` через `googleapiclient.discovery.build`. Дані
  Search Console публікуються із затримкою 2–3 дні, тому функція йде назад по
  днях (`for offset in range(max_lookback_days + 1)`), доки не знайде день з
  непорожнім `rows`, і повертає саме ту дату разом з даними — у звіті потім
  явно вказується, за яке число реально показано цифри.

### 5.4. Google Ads — `google_ads.py`

Google Ads тут навмисно **без офіційного `google-ads` SDK** — прямий REST-виклик:

```python
def get_access_token(env):
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env["GOOGLE_OAUTH_CLIENT_ID"],
        "client_secret": env["GOOGLE_OAUTH_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def _search(env, access_token, query):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "login-customer-id": env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
    }
    url = f"https://googleads.googleapis.com/{API_VERSION}/customers/{CLIENT_CUSTOMER_ID}/googleAds:search"
    return requests.post(url, headers=headers, json={"query": query}, timeout=30).json()["results"]
```

Запити пишуться на GAQL (Google Ads Query Language) прямими рядками:
`SELECT metrics.cost_micros, metrics.impressions FROM customer WHERE segments.date = '...'`.
Обліковий запис `login_customer_id` — це manager-акаунт (MCC) «Гармонія 2000»
(`3933012815`), а реальні витрати рахуються по прив'язаному клієнтському
акаунту `CLIENT_CUSTOMER_ID = "5559398809"`. Задокументована пастка: фільтр
`WHERE segments.date DURING YESTERDAY` резолвиться у **таймзоні акаунта Google
Ads**, яка не збігалась з python-обчисленим «вчора» — вирішено переходом на
явний `segments.date = 'YYYY-MM-DD'`.

### 5.5. Facebook/Meta Ads — `meta_ads.py`

Graph API Insights через `requests`, авторизація постійним System User
access token (право `ads_read`, свідомо без `ads_management` — щоб мінімізувати
збиток у разі витоку токена). Основні функції:

- `_insights_request(token, account_id, target_date, fields, level=None)` /
  `_insights_request_range(...)` — низькорівневий виклик `/insights`;
- `_fetch_campaign_rows(token, account_id, since, until)` — розбивка по кампаніях;
- `_excluded_totals(campaign_rows)` / `_display_campaigns(campaign_rows)` —
  тестові кампанії (список `EXCLUDED_...`) виключаються з підсумків, щоб не
  спотворювати цифри реальних рекламних витрат;
- `fetch_account_summary`, `get_data`, `get_monthly_data`, `render_section`.

### 5.6. Новини фармгалузі — `pharma_news.py`

RSS-фід `https://www.apteka.ua/rss`, розбір тим самим `xml.etree.ElementTree`.
Джерело змішує реальні новини з чисто адміністративними записами («Розпорядження
від 10.07.2026 р. № 328-...») — вони відфільтровуються регуляркою
`ADMIN_NOTICE_RE`. Функція `get_data(report_date, limit=3, max_lookback_days=5)`
повторює той самий патерн «крокуй назад по днях», що й Search Console — сайт
не публікує новини у вихідні.

### 5.7. Дані з 1С (Excel-вигрузки) — `sales_1c.py` та `sales_daily.py`

Це не API, а файли `.xlsx`, які користувач вручну вивантажує з 1С через RDP і
кладе на сервер. Два різні формати з різною глибиною деталізації:

- `sales_1c.py` — **разовий знімок**: один рядок «Товар × Філія × Кількість
  витрат» за весь період вигрузки, без розбивки по днях. Читається через
  `openpyxl.load_workbook(..., read_only=True, data_only=True)`. Товар
  зіставляється з `oc_product` **за назвою** (в цьому звіті 1С немає артикулу),
  через `norm_product_name`/`norm_filial_name` — нормалізацію тексту (прибрати
  зайві пробіли, уніфікувати регістр тощо) і подальший точний матч;
  незіставлені рядки просто відкидаються.
- `sales_daily.py` — новіше й точніше джерело: **справжня поденна історія**
  (Філія → Місяць → День → Товар.Код), яка накопичується в SQLite-базі
  `sales_daily.db`. Ключова функція `ingest_file(xlsx_path, mysql_conn=None)`:
  парсить один xlsx-файл, зіставляє товари за кодом (`model` в `oc_product`,
  а не за назвою — надійніше за `sales_1c.py`), і виконує ідемпотентний upsert:

  ```python
  hist.executemany(
      "INSERT INTO daily_sales (product_id, warehouse_id, sale_date, qty, revenue) "
      "VALUES (?, ?, ?, ?, ?) "
      "ON CONFLICT(product_id, warehouse_id, sale_date) DO UPDATE SET "
      "qty = excluded.qty, revenue = excluded.revenue",
      [...],
  )
  ```

  Той самий файл, залитий повторно, не створює дублів — конфлікт по складеному
  первинному ключу `(product_id, warehouse_id, sale_date)` перезаписує рядок.
  У докстрінгу файлу задокументована непроста пастка з полями дат у самому
  звіті 1С («Реалізація товару»): поле «День» без «Місяця» схлопує однакові
  числа різних місяців в один рядок, а «Період рік.День года» насправді завжди
  прив'язане до кінця періоду — правильна робоча комбінація полів була знайдена
  експериментально і зафіксована в коментарі як застереження на майбутнє.

  Функції для читання накопиченого: `get_sold_qty_since(days_back=None,
  since_date=None, min_sold=0)`, `get_sold_qty_since_blended(...)` (комбінує
  кілька джерел), `get_sold_qty_by_product_in_range(...)`,
  `get_sold_qty_by_pw_in_range(...)`, плюс `has_data()`/`get_coverage()` для
  перевірки, чи є взагалі дані за потрібний період.

### 5.8. Власний трекер падінь залишків — `stock_snapshot.py`

Джерело даних, яке проєкт **сам собі створює**, поки немає точнішого фіду:
періодично (рекомендовано кожні 15 хв, тим самим cron, що оновлює залишки на
сайті) знімає поточний стан `product_warehouse` з MySQL і порівнює з попереднім
знімком, зберігаючи в окрему SQLite-базу **тільки зменшення** кількості
(`run_snapshot()`). Зменшення інтерпретується як proxy для «продано» — воно
однаково реагує і на сайтові замовлення, і на продажі наживо в аптеці, на
відміну від `oc_order`, який бачить лише сайт. У саму бойову базу OpenCart
нічого не пишеться — тільки читання.

### 5.9. Відмови покупцям — `refusals.py`

Одноразовий історичний імпорт (весь 2025 рік одним файлом, не щоденний
drip-feed) з power-джерела, в якому касир фіксує «клієнт хотів товар, якого не
було». Зберігається в SQLite; зіставлення товару з `oc_product` тут навмисно
**не** робиться (на відміну від `sales_daily.py`) — для звіту «що найчастіше
відмовляли» достатньо сирої назви з файлу, а фаззі-матчинг за назвою вже був
визнаний ненадійним на прикладі `sales_1c.py`.

---

## 6. Оркестрація щоденного звіту — `daily_report.py`

Це «диригент», що зшиває всі джерела в один результат. Головна функція —
`generate_report(report_date=None)`.

### 6.1. Стійкість до відмов окремого джерела

Кожен виклик до зовнішнього API обгорнутий у `_safe_fetch`:

```python
def _safe_fetch(label, fallback, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        print(f"[{label}] fetch failed, using fallback:", file=sys.stderr)
        traceback.print_exc()
        return fallback
```

Ідея: якщо, наприклад, Google Ads тимчасово повернув 500 або протух OAuth-токен,
це не має зривати генерацію й доставку решти звіту — секція просто піде з
позначкою «дані недоступні», а помилка потрапить у stderr (і, відповідно, у
cron-лог) для діагностики.

### 6.2. Побудова даних для кожної секції

`generate_report` викликає джерела (`opencart_sales.get_data`, `anr_sales.get_data`,
`meta_ads.get_data`, `google_ads.get_data`, `fetch_ga4_active_users`,
`fetch_search_console_top_queries`) кожне через `_safe_fetch`, а потім невеликі
приватні функції-адаптери приводять сирі відповіді до форми, яку далі очікує
рендерер:

- `_apteky_data(anr_data)` — секція «Продажі по аптеках»;
- `_site_data(opencart_data, anr_data)` — навмисно показує **обидва** числа:
  «Оформлено на сайті» (сирий OpenCart-order-sum, включно з непідтвердженими
  самовивозами) і «Підтверджено АНР» (реальна закрита виручка) — і в
  `HANDOFF.md` окремо пояснено, чому ці два числа мають розходитись і це не
  помилка;
- `_analytics_data(ga4)`, `_gsc_data(...)`, `_pharma_news_data(report_date)`.

`pct_change_value(old, new)` — спільна функція форматування відсоткової зміни
для HTML-версії: повертає кортеж `(текст, css_class)`, де клас — `pct-up`
(зелений, ≥+5%), `pct-down` (червоний, ≤−5%) або `pct-flat` (сірий).

### 6.3. Дві версії тексту й одна HTML

```python
report_text = report_text_formatter.build_report(report_data, report_date_str,
                                                   gsc=gsc_data, pharma_news=pharma_news_data)
compact_text = report_text_formatter.build_report(report_data, report_date_str,
                                                    gsc=None, pharma_news=pharma_news_data, compact=True)
report_html = render_report_html(report_date, ga4, gsc_rows, gsc_date, opencart_data,
                                  anr_data, meta_data, google_data, pharma_news_data)
```

`report_text` (повний, з Search Console) зберігається у файл `.md`;
`compact_text` (без Search Console — свідомо прибрано з чат-повідомлення, щоб
не роздувати Telegram-меседж) іде в саме тіло чат-повідомлення; `report_html`
— повністю окремий, самостійно стилізований рендер (лежить прямо в
`daily_report.py::render_report_html()`, ~260 рядків inline-HTML/CSS з нуля,
без Jinja2) і завжди йде як HTML-файл-документ. У `HANDOFF.md` явно
зазначено, що ці два рендери (текстовий і html) **не синхронізуються
автоматично** — нову метрику, додану в одному, треба вручну продублювати і в
другому.

### 6.4. Результат

```python
md_path = REPORTS_DIR / f"{report_date.isoformat()}.md"
md_path.write_text(report_text, encoding="utf-8")
html_path = REPORTS_DIR / f"{report_date.isoformat()}.html"
html_path.write_text(report_html, encoding="utf-8")
return report_text, compact_text, md_path, html_path
```

---

## 7. Форматування тексту — `report_text_formatter.py`

Файл позначений у `HANDOFF.md` як «user-authored» (написаний самим клієнтом і
лише інтегрований), тому має трохи інший стиль, ніж решта коду. Тут зібрані
всі текстові прийоми фінального звіту:

- `fmt_num`, `fmt_currency` (₴, а не «грн» — свідома відмінність від HTML-версії),
  `fmt_usd`;
- `delta_arrow(current, previous, period_label="позавчора")` — стрілка
  зростання/падіння з підписом періоду; параметр `period_label` пізніше
  розширено, щоб місячний звіт міг підставити `"попередній місяць"` замість
  «позавчора», яке для місячного порівняння звучало б безглуздо;
- `is_warning(current, previous, threshold=WARNING_THRESHOLD_PCT)` — чи
  перевищено поріг у 30%, який триггерить ⚠️ у звіті;
- `short_campaign_name(...)` — довгі назви рекламних кампаній Facebook/Google
  скорочуються за словником `FB_CAMPAIGN_SHORT_NAMES`/аналогічним для Google,
  щоб не ламали моноширинне форматування;
- `truncate`, `divider`, `bar` — суто косметичні хелпери для рамок/роздільників;
- по одній функції `build_*_section(d)` на кожну секцію звіту (аптеки, сайт,
  аналітика, Facebook, Google Ads, фарм-новини, Search Console);
- `build_report(data, report_date, gsc=None, pharma_news=None, compact=False)`
  — головна точка входу, що збирає всі секції в одне текстове повідомлення в
  заданому порядку.

Формат навмисно моноширинний («псевдо-Markdown», не справжній Markdown) — під
Telegram-обгортку в потрійні зворотні лапки. У числах спеціально
використовується нерозривний пробіл (`\xa0`) для розділення тисяч — щоб
Telegram не переносив число посередині при рендерингу code-block.

---

## 8. Місячний звіт — `monthly_report.py`

Не окрема система, а **надбудова над тими самими модулями**: замість `get_data`
використовує `*_range`/`get_monthly_data` функції тих самих
`opencart_sales`/`anr_sales`/`meta_ads`/`google_ads`, і той самий
`report_text_formatter` для форматування (щоб текстовий стиль збігався з
щоденним звітом).

- `month_bounds(report_date=None)` — межі попереднього повного календарного
  місяця;
- `current_month_to_date_bounds(report_date=None)` — межі поточного місяця «до
  вчора» (для звітів на вимогу «надішли мені зараз», де сьогоднішній
  неповний день не повинен потрапити у звіт);
- `get_data(report_date=None, start=None, end=None)` — обидва режими через
  одну функцію: без аргументів — попередній місяць (те, що шле cron 1-го
  числа), з `start=`/`end=` — довільний або поточний діапазон;
- `render_text(data)` / `render_html(data)` — текстова й HTML версії, аналогічно
  щоденному звіту;
- `generate_report(...)` — записує файл із людинозрозумілою україномовною
  назвою: `"Звіт за Червень 2026.html"` або `"Звіт за Липень 2026 (до 19.07).html"`
  — саме ця назва потім показується в Telegram як ім'я файлу вкладення.

У `HANDOFF.md` зафіксовано, що вбудований у HTML SVG-графік динаміки був
збудований, задеплоєний і того самого дня прибраний за прямим фідбеком
користувача («не читабельний») — місячний звіт зараз містить лише картки й
таблиці (топ-10 товарів, топ-10 аптек), без графіків.

---

## 9. Аналітика залишків — друга підсистема проєкту

Ця частина не пов'язана напряму зі щоденним/місячним звітом (крім спільного
доступу до OpenCart DB і спільного Telegram-бота) і росла окремо, вирішуючи
задачу «показати завідуючим аптеками, що і звідки перевезти».

### 9.1. Категорії товарів — `product_categories.py`

`fetch_mid_tier_category_map(conn)` читає дерево категорій OpenCart (~670
категорій, 2–3 рівні) і для кожного товару обирає «середній» рівень (категорія,
чий `parent_id` сам є коренем `parent_id=0`) — саме він відповідає терапевтичній
групі («Для серця та судин», «Вітаміни та мінерали»). Допоміжна вкладена функція
`reaches_root(category_id)` перевіряє належність до дерева. `get_category_map()`
— кешована обгортка для повторного використання в інших модулях.

### 9.2. Дефектура — `defectura.py`

«Товар, що зазвичай продається в конкретній аптеці, але зараз має там нульовий
залишок» рахується через **чотириступеневий fallback**, від найточнішого
джерела до найгрубішого — кожна функція `fetch_defectura_per_pharmacy_from_*`
відповідає одному рівню:

1. `fetch_defectura_per_pharmacy_from_daily` — на основі `sales_daily.py`
   (найточніше: справжня поденна історія, «продається» рахується в
   rolling-вікні `DEFECTURA_WINDOW_DAYS` днів від сьогодні — товар, що
   продавався пів року тому й затих, більше не вважається дефектурою);
2. `fetch_defectura_per_pharmacy_from_1c` — грубе середнє за весь період
   вигрузки 1С;
3. `fetch_defectura_per_pharmacy_from_stock_drops` — власний трекер падінь
   (`stock_snapshot.py`);
4. `fetch_defectura_per_pharmacy_network_proxy` — найслабше джерело: мережевий
   `oc_order`-проксі (бачить лише сайтові замовлення).

`fetch_defectura_per_pharmacy(conn, ...)` пробує джерела по черзі й повертає
перше, де є дані, разом з міткою, яке саме джерело використано (це потім
показується користувачу як застереження про точність). `get_data(...)` і
`get_data_per_pharmacy(...)` — публічні точки входу; `render_section(...)` /
`render_section_per_pharmacy(...)` — текстовий рендер.

### 9.3. Скоро закінчиться — `low_stock_alert.py`

Логіка «поточний залишок / темп продажу в день = днів до нуля», з
**п'ятиступеневим** fallback (`daily → recent_1c → 1c → stock_drops →
unavailable`), реалізованим так само набором функцій `fetch_low_stock_from_*`.
Окремо зазначено (докстрінг + `HANDOFF.md`), що рівень `1c` (грубе середнє за
весь період) неточний для сезонних товарів — і в рендері така оцінка
позначається не тим самим 🟡/✅, а явним ⚠️ «може бути неточним». Функція
`_seasonal_multiplier_by_product()` намагається коригувати прогноз з
урахуванням сезонності.

### 9.4. Перерозподіл і мертвий вантаж — `redistribution.py`

Дві незалежні задачі в одному файлі:

- **Перерозподіл**: товар з нульовим залишком в одній аптеці (з `defectura.py`),
  який є на складі в іншій — `fetch_redistribution(conn, sales_window_days=...)`.
  Логістика/відстань між аптеками не враховується — лише факт «десь є, десь
  нема»; `_demand_stability_map(needs)` оцінює, наскільки стабільний попит
  для пріоритизації;
- **Мертвий вантаж**: товар лежить (`quantity >= MIN_DEAD_QUANTITY`), але
  реально не продавався саме тут за `DEAD_STOCK_DAYS` днів (наразі 60, було
  30 — зміна прямо відображає бізнес-правило користувача «неліквід = 0 продажів
  за 60 днів»). Той самий чотириступеневий fallback-патерн, що й у
  `defectura.py` (`fetch_dead_stock_from_daily/_1c/_stock_drops/network_proxy`).
  `_exclude_medical_supplies(conn, rows)` прибирає з «мертвого вантажу»
  витратні матеріали (шприци, рукавички) — вони системно й хибно потрапляли
  туди, бо ніколи не проходять через сайтове замовлення.

### 9.5. Сезонність — `seasonality.py`

Forward-looking логіка: порівнюються ті самі 30 днів «зараз» торік і наступні
30 днів торік — якщо тоді категорія зростала, це сигнал «скоро підйом» і цього
року (застуда восени, алергія навесні тощо). `_reference_windows()` рахує
потрібні дати; `fetch_seasonality(conn)` — основна функція; вимагає в
`sales_daily.db` історію щонайменше ~13 місяців — інакше секція просто не
показується (`data_source=None`), без вигаданих чисел.

### 9.6. Щоденний дайджест по залишках — `stock_history_status.py`

Окремий (839 рядків — найбільший файл у `scripts/`) HTML-дайджест, що
об'єднує дефектуру, перерозподіл і low-stock в одну сторінку й шле її **не**
в загальний Telegram-бот-розсилку, а точковому списку отримувачів
(`CHAT_IDS`), тільки як HTML-документ (звичайний текстовий Telegram-меседж
визнаний нечитабельним для такого обсягу таблиць). `record_and_get_trend(...)`
рахує тренд день-до-дня для показників дефектури. `send_document(token,
chat_id, file_path, caption)` — прямий виклик Telegram Bot API через
`requests` (без `python-telegram-bot`, бо це односторонній cron-скрипт без
потреби в повноцінному боті).

### 9.7. Сторінки перенесень на сайті — `transfer_pages.py`

Публікує **статичні HTML-файли прямо в docroot сайту** (нову підпапку
`transfers/`, не чіпаючи наявних файлів) — по одній сторінці на аптеку, з
п'ятьма розділами (привезти сюди / замовити постачальнику / скоро закінчиться /
мертвий вантаж / забрати звідси). `slugify_title(title)` перетворює назву
аптеки в ім'я файлу — навмисно **не** за сирим `warehouses_id`, бо він не
збігається з номером у назві «Аптека №N» (задокументована пастка зі зсувом
+4). `render_pharmacy_page(...)` і `render_index_page(...)` генерують HTML
без будь-якого шаблонізатора — прямим складанням рядків.

### 9.8. Разовий SEO-звіт — `blog_seo_check.py`

Найменший і найспецифічніший скрипт: порівнює Search Console до/після для
двох конкретних блог-статей, у яких змінили title 18.08 — щоб побачити, чи
виріс CTR. `gsc_client(env)` — той самий патерн авторизації через
`Credentials`, що й у `daily_report.py`, але окремо, бо скрипт одноразовий і
не інтегрований в оркестратор.

---

## 10. Telegram-бот — `telegram-bot/`

### 10.1. `bot.py` — інтерактивна частина

Побудований на `python-telegram-bot` (`Application.builder().token(token).build()`,
`run_polling()` — long-polling, без вебхука). Дві точки входу:

- `start(update, context)` — обробник `/start`, показує кнопку
  `InlineKeyboardButton("🔄 Оновити дані", callback_data="update_report")`;
- `update_report(update, context)` — обробник натискання кнопки: генерує звіт
  «наживо» через `asyncio.to_thread(daily_report.generate_report)` (винесено
  в окремий потік, бо `generate_report` — синхронний, блокуючий I/O-код, а
  бот працює на asyncio-циклі), ділить компактний текст на частини під ліміт
  Telegram (`split_for_telegram`, ліміт `TELEGRAM_MAX_MESSAGE_LENGTH = 3900`)
  і шле кожен шматок у моноширинному code-block, а повний HTML — окремим
  файлом-документом.

Перед будь-якою дією обидва хендлери перевіряють `is_blocked(chat_id)` —
чорний список у `blocked_users.json` (chat_id → ім'я/username/дата
блокування). Кожен `/start` і натискання кнопки логуються в `users.json`
(`record_user`) — це і є єдиний спосіб дізнатись, хто підписаний (немає
жодної окремої «бази користувачів», крім цього JSON-файлу на диску сервера).

### 10.2. `send_daily_report.py` / `send_monthly_report.py` — cron-точки входу

Односторонні скрипти без `python-telegram-bot` — пряме звернення до Telegram
Bot HTTP API через `requests`:

```python
def send_message(token, chat_id, text): ...
def send_document(token, chat_id, file_path, caption): ...
def main():
    # генерує звіт, читає users.json, розсилає всім не заблокованим
```

Запускаються сервером через cron (`0 8 * * *` для щоденного,
`0 8 1 * *` для місячного) — на відміну від `bot.py`, це не довгоживучий
процес, а разовий запуск раз на добу/місяць.

---

## 11. Інфраструктура та деплой

Взято з розділу «Production deployment» у `HANDOFF.md`, як довідка про те,
де і як код фактично виконується (це вже не код, а операційна конфігурація,
але без неї картина проєкту неповна):

- Хостинг: спільний shared-хостинг (`ukraine.com.ua`, панель `adm.tools`);
  дерево тек на сервері дзеркальне до локального (`/home/fz453955/reports_bot/{google-ads,opencart,meta-ads,scripts,telegram-bot,reports}/`), завдяки чому увесь код, побудований на відносних
  `Path(__file__).resolve().parent.parent`-шляхах, працює без змін в обох
  середовищах;
- Деплой — вручну, `scp` кожного зміненого файлу; синхронізації немає;
- Python на сервері — явно `/usr/bin/python3.10` (системний `python3` —
  застарілий 3.6.8), пакети через `python3.10 -m pip install --user`;
- Бот-процес керується вбудованим у панель хостингу Supervisor-модулем;
  перезапуск після деплою — вбити PID процесу, Supervisor підніме заново
  протягом ~5 секунд (важливо: `bot.py` тримає імпортований код у пам'яті,
  тож самого `scp` недостатньо, потрібен рестарт);
- Розклад (cron) — через власний UI панелі хостингу, не через реальний
  `crontab` (SSH-доступ до crontab на цьому акаунті технічно заблокований
  CloudLinux-обгорткою);
- OpenCart DB доступна серверу без тунелю (той самий хостинг-акаунт).

---

## 12. Як розвивався проєкт (за журналом `HANDOFF.md`)

Хоча в git-історії лише два «квадратних» коміти (сквошені), хронологію
реального розвитку видно з дат і секцій у `HANDOFF.md`:

1. Базовий щоденний звіт: OpenCart + GA4 + Search Console + Facebook + Google
   Ads, доставка через Telegram-бота з кнопкою й cron-розсилкою.
2. Інтеграція з АНР (реальні закриті чеки по аптеках) — окремий XML-парсер,
   бо OpenCart сам по собі не міг відрізнити «замовлення оформлено» від
   «товар реально забрали» (статус 15 — «глухий кут»).
3. `report_text_formatter.py` як окремий, user-authored файл — виніс усе
   текстове форматування з `daily_report.py` в самостійний модуль.
4. `pharma_news.py` — фарм-новини з RSS.
5. Місячний звіт (`monthly_report.py`) — надбудова над тими самими джерелами.
6. Друга підсистема — аналітика залишків: спершу власний трекер падінь
   (`stock_snapshot.py`), потім значно точніша поденна історія з 1С
   (`sales_daily.py`), навколо якої переписані `defectura.py`,
   `low_stock_alert.py`, `redistribution.py` (перехід на чотири-/
   п'ятиступеневий fallback з єдиним rolling-вікном замість статичного
   періоду);
- `product_categories.py` і `seasonality.py` — розбивка по терапевтичних
  групах і прогноз сезонного попиту;
- `refusals.py` — разовий історичний імпорт відмов;
- `transfer_pages.py` та `stock_history_status.py` — публічний і
  внутрішній HTML-вивід для завідуючих аптеками.

Наскрізні уроки, зафіксовані як «house style» в `HANDOFF.md` і послідовно
видні в коді:

- **не вгадувати схему** — перед будь-яким запитом до чужої БД/API спершу
  `DESCRIBE`/`SHOW TABLES` чи еквівалент;
- **одне джерело падає — решта звіту все одно доходить** (патерн
  `_safe_fetch`/множинний fallback у `defectura.py`/`low_stock_alert.py`);
- **прогноз лише тоді, коли є на чому будувати** — кілька функцій явно
  повертають «дані недоступні» замість вигаданих цифр (`seasonality.py`,
  `anr_sales.get_monthly_data`);
- **секрети ніколи не потрапляють у чат чи в git** — `.env`-и й
  `.gitignore` з самого початку;
- rolling-вікна (від «сьогодні», а не статичний період) там, де бізнес-правило
  сформульоване як «неліквід — це N днів без продажу», щоб визначення саме
  зсувалося вперед з кожним днем без змін коду.

---

## 13. Підсумок: карта «що за що відповідає»

| Питання | Де відповідь |
|---|---|
| Продажі сайту (сирі) | `opencart_sales.py` → MySQL `oc_order`/`oc_order_product` |
| Реальна виручка аптек | `anr_sales.py` → XML-фід `sales_YYYY-MM-DD.xml` |
| Відвідуваність сайту | `daily_report.py::fetch_ga4_active_users` → GA4 Data API |
| Пошукові запити | `daily_report.py::fetch_search_console_top_queries` → Search Console API |
| Facebook-реклама | `meta_ads.py` → Graph API Insights |
| Google-реклама | `google_ads.py` → Google Ads REST (`googleAds:search`) |
| Новини галузі | `pharma_news.py` → RSS `apteka.ua/rss` |
| Текст звіту | `report_text_formatter.py::build_report` |
| HTML звіту | `daily_report.py::render_report_html` |
| Місячний звіт | `monthly_report.py` (надбудова над тими самими джерелами) |
| Поденна історія продажів для аналітики залишків | `sales_daily.py` → SQLite `sales_daily.db` |
| Дефектура / скоро закінчиться / перерозподіл / мертвий вантаж | `defectura.py`, `low_stock_alert.py`, `redistribution.py` |
| Сезонний прогноз | `seasonality.py` |
| HTML-сторінки для аптек на сайті | `transfer_pages.py` |
| Доставка в Telegram | `telegram-bot/bot.py` (на вимогу), `send_daily_report.py`/`send_monthly_report.py` (cron) |

---

*Документ складено на основі коду репозиторію `apteka-g24-reports` та файлу
`HANDOFF.md` станом на останнє оновлення журналу (2026-07-13/2026-08-20-і
зміни за фрагментами коду свіжіших дат). Секрети (`.env`, токени, реальні
`chat_id` користувачів) до документа не включались.*
