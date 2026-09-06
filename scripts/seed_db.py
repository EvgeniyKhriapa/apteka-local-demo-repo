"""
seed_db.py — створює локальну SQLite-базу з демонстративними даними аптечної
мережі: препарати, аптеки (філії) та історія замовлень за останні 14 днів.

Ідея: справжній проєкт читає такі дані з MySQL (OpenCart). Тут та сама
структура (товар / філія / замовлення / рядок замовлення) відтворена в
SQLite, щоб можна було запустити звіт локально без встановлення MySQL-сервера
і без будь-яких реальних credentials.

Запуск (один раз, або щоразу коли хочете перегенерувати дані з нуля):
    python demo/seed_db.py
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "pharmacy_demo.db"

# --- Довідники (аналог oc_product / oc_warehouses_description) -------------

PHARMACIES = [
    "Аптека №1 — вул. Соборна, 12",
    "Аптека №2 — просп. Незалежності, 45",
    "Аптека №3 — вул. Шевченка, 8",
    "Аптека №4 — вул. Грушевського, 21",
]

# (назва препарату, категорія, роздрібна ціна, грн)
PRODUCTS = [
    ("Парацетамол 500мг №10",              "Знеболювальні",        25.50),
    ("Ібупрофен 200мг №20",                "Знеболювальні",        48.00),
    ("Но-шпа 40мг №24",                    "Знеболювальні",        95.30),
    ("Аспірин Кардіо 100мг №28",           "Серцево-судинні",      62.00),
    ("Кардіомагніл 75мг №30",              "Серцево-судинні",     145.00),
    ("Еналаприл 10мг №20",                 "Серцево-судинні",      38.50),
    ("Амброксол сироп 100мл",              "Від кашлю",            68.90),
    ("Бромгексин таблетки №20",            "Від кашлю",            42.00),
    ("Мукалтин №10",                       "Від кашлю",            18.20),
    ("Лоратадин 10мг №10",                 "Антигістамінні",       32.00),
    ("Цетрин №10",                         "Антигістамінні",       89.00),
    ("Вітамін С 500мг №30",                "Вітаміни та мінерали", 55.00),
    ("Магній В6 №50",                      "Вітаміни та мінерали", 112.00),
    ("Мультивітаміни Компливит №60",       "Вітаміни та мінерали", 210.00),
    ("Омепразол 20мг №28",                 "ШКТ",                   47.50),
    ("Лінекс форте №14",                   "ШКТ",                  185.00),
    ("Смекта саше №10",                    "ШКТ",                   98.00),
    ("Називін спрей 0.05% 10мл",           "Для носа",              72.00),
    ("Аквамаріс спрей 30мл",               "Для носа",              145.00),
    ("Валеріана екстракт №50",             "Заспокійливі",          22.00),
    ("Персен №40",                         "Заспокійливі",         168.00),
    ("Хлоргексидин 0.05% 100мл",           "Антисептики",           28.00),
    ("Перекис водню 3% 100мл",             "Антисептики",           15.50),
    ("Бинт стерильний 5м×10см",            "Медичні вироби",        12.00),
    ("Шприц одноразовий 5мл №1",           "Медичні вироби",         3.50),
    ("Термометр електронний",              "Медичні вироби",       165.00),
    ("Активоване вугілля №10",             "ШКТ",                   14.00),
    ("Ренні жувальні таблетки №24",        "ШКТ",                   87.00),
    ("Долгіт крем 5% 50г",                 "Знеболювальні",         79.00),
    ("Валідол 60мг №10",                   "Серцево-судинні",       19.00),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS pharmacies (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY,
    order_date      TEXT NOT NULL,      -- YYYY-MM-DD
    pharmacy_id     INTEGER NOT NULL,
    status          TEXT NOT NULL,      -- 'paid' | 'refunded'
    FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    quantity    INTEGER NOT NULL,
    price       REAL NOT NULL,          -- ціна на момент продажу
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
"""


def build_database(days_back: int = 14, seed: int = 42) -> None:
    rng = random.Random(seed)

    if DB_PATH.exists():
        DB_PATH.unlink()  # завжди чиста генерація, щоб демо було відтворюваним

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO pharmacies (id, name) VALUES (?, ?)",
        list(enumerate(PHARMACIES, start=1)),
    )
    conn.executemany(
        "INSERT INTO products (id, name, category, price) VALUES (?, ?, ?, ?)",
        [(i, name, cat, price) for i, (name, cat, price) in enumerate(PRODUCTS, start=1)],
    )

    order_id = 1
    item_id = 1
    today = date.today()

    for offset in range(days_back, 0, -1):
        order_date = today - timedelta(days=offset)
        # Трохи більше замовлень у "вчора", щоб було видно позитивну динаміку
        # у звіті одразу після першого запуску.
        base_orders = rng.randint(18, 30)
        if offset == 1:
            base_orders = int(base_orders * 1.15)

        for _ in range(base_orders):
            pharmacy_id = rng.choice(range(1, len(PHARMACIES) + 1))
            status = "refunded" if rng.random() < 0.04 else "paid"

            conn.execute(
                "INSERT INTO orders (id, order_date, pharmacy_id, status) VALUES (?, ?, ?, ?)",
                (order_id, order_date.isoformat(), pharmacy_id, status),
            )

            n_items = rng.randint(1, 4)
            chosen = rng.sample(range(1, len(PRODUCTS) + 1), n_items)
            for product_id in chosen:
                name, category, price = PRODUCTS[product_id - 1]
                qty = rng.randint(1, 3)
                conn.execute(
                    "INSERT INTO order_items (id, order_id, product_id, quantity, price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (item_id, order_id, product_id, qty, price),
                )
                item_id += 1

            order_id += 1

    conn.commit()
    conn.close()
    print(f"Готово: {DB_PATH} ({order_id - 1} замовлень, {item_id - 1} рядків товарів)")


if __name__ == "__main__":
    build_database()
