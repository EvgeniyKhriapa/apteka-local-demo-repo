# apteka-local-demo — локальний звіт продажів препаратів (без Telegram)

Повністю локальний, автономний Python-проєкт: генерує щоденний звіт продажів
аптечної мережі на основі власної SQLite-бази препаратів. Проєкт є похідним
(local demo) від оригінального репозиторію звітності `apteka-g24-reports` —
текстовий рендер звіту використовує **справжній, незмінений
`report_text_formatter.py`** з того проєкту, а HTML-версія побудована в
стриманому "офісному" стилі спеціально для цього демо.

Жодних зовнішніх залежностей: тільки стандартна бібліотека Python 3.10+
(`sqlite3`, `datetime`, `pathlib`). Жодного Telegram, MySQL, Google/Meta API —
усе працює локально, на одному ПК, без інтернету й без секретів.

## Що робить проєкт

1. `scripts/seed_db.py` створює локальну SQLite-базу `scripts/pharmacy_demo.db`
   із 30 препаратами (знеболювальні, серцево-судинні, вітаміни тощо),
   4 аптеками і ~330 випадковими замовленнями за останні 14 днів.
2. `scripts/daily_report.py` читає цю базу, збирає дані у форматі, який
   очікує оригінальний `build_report()`, і генерує:
   - компактну текстову версію — друкується в консоль (у реальному проєкті
     це пішло б повідомленням у Telegram);
   - повний текстовий звіт — `reports/<дата>.md`;
   - офісний HTML-звіт — `reports/<дата>.html` (відкривається в браузері).

Секції, для яких у цьому демо немає джерела даних (аналітика сайту GA4,
Facebook Ads, Google Ads), чесно позначені як недоступні — так само, як у
оригінальному проєкті `_safe_fetch` ловить помилку зовнішнього API і не
зупиняє генерацію решти звіту.

## Структура репозиторію

```
apteka-local-demo/
├── scripts/
│   ├── seed_db.py                 — генерація демо-бази препаратів/аптек/замовлень
│   ├── report_text_formatter.py   — ОРИГІНАЛЬНИЙ файл з apteka-g24-reports, без змін
│   └── daily_report.py            — оркестратор: читає базу, рендерить текст+HTML
├── tests/
│   └── test_daily_report.py       — unittest-перевірка всього конвеєра
├── reports/                       — сюди зберігаються згенеровані .md/.html (у git не потрапляють)
├── docs/                          — технічна документація оригінального проєкту apteka-g24-reports
│   ├── apteka-g24-reports — технічна документація.md
│   └── apteka-g24-reports — вихідний код.md
├── .github/workflows/tests.yml    — CI: автоматичний запуск тестів на push/PR
├── requirements.txt               — залежностей немає (лише stdlib); файл-заготовка на майбутнє
├── .gitignore
└── LICENSE (MIT)
```

## Запуск локально (PyCharm)

1. **Відкрити проєкт**: File → Open → вибрати цю теку (де лежить
   `requirements.txt`).
2. **Інтерпретатор**: File → Settings → Project → Python Interpreter →
   Add Interpreter → Virtualenv Environment → New, Python 3.10+.
   Встановлювати нічого не потрібно — залежностей немає.
3. **Позначити `scripts/` як Sources Root** (правий клік на теку → Mark
   Directory as → Sources Root) — щоб імпорт `import report_text_formatter`
   у `daily_report.py` коректно резолвився і в самому PyCharm.
4. **Створити демо-дані**: Run Configuration на `scripts/seed_db.py` →
   запустити (Shift+F10). Можна перезапускати будь-коли — база щоразу
   перестворюється з нуля з новим набором випадкових замовлень.
5. **Згенерувати звіт**: Run Configuration на `scripts/daily_report.py` →
   Working directory — корінь репозиторію. Результат з'явиться в консолі
   PyCharm і у файлах `reports/<дата>.md` / `reports/<дата>.html`.
6. **(Опційно) Запустити тести**: Run Configuration типу "Python tests" →
   Unittests → Target: `tests.test_daily_report`, або з терміналу:
   ```
   python -m unittest tests.test_daily_report -v
   ```

## Запуск з терміналу (без PyCharm)

```bash
git clone <URL-вашого-репозиторію>
cd apteka-local-demo
python3 scripts/seed_db.py
python3 scripts/daily_report.py
```

## Як підключити цей проєкт до GitHub

Репозиторій уже ініціалізований локально (`git init` + перший коміт). Щоб
опублікувати його на GitHub:

1. Створіть новий **порожній** репозиторій на github.com (без README/.gitignore
   — вони вже є тут, щоб уникнути конфлікту при першому push).
2. У теці проєкту виконайте:
   ```bash
   git remote add origin https://github.com/<ваш-акаунт>/<назва-репозиторію>.git
   git branch -M main
   git push -u origin main
   ```
3. Готово — GitHub Actions (`.github/workflows/tests.yml`) автоматично
   запустить тести на Python 3.10/3.11/3.12 при кожному push чи pull request.

## Зв'язок з оригінальним проєктом `apteka-g24-reports`

Це демо не є копією продакшн-системи — воно свідомо спрощене й повністю
локальне. Але воно навмисно побудоване так, щоб бути сумісним і зрозумілим
поруч з оригіналом:

- `report_text_formatter.py` — буквально той самий файл, без жодної зміни
  логіки чи форматування;
- структура даних (`data["apteky"]`, `data["site"]`, `data["analytics"]`
  тощо) — той самий контракт, який очікує `build_report()`;
- патерн "джерело недоступне → `available: False`, решта звіту все одно
  генерується" — той самий, що й `_safe_fetch` в оригінальному
  `daily_report.py`;
- повна архітектурна документація оригінального проєкту (з поясненнями всіх
  модулів і вихідним кодом) лежить у `docs/` — для контексту, якщо захочете
  колись розширити це демо реальними джерелами (OpenCart/MySQL, Google Ads,
  Facebook Ads, Telegram).
