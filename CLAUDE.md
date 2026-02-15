# n8n Hub — Архітектура та інструкції для AI-асистентів

> Цей файл містить повний опис проєкту для AI-асистентів (Claude, GPT тощо),
> які будуть допрацьовувати додаток.

## Що це за проєкт

**n8n Hub** — веб-додаток для пошуку, перегляду та управління колекцією n8n воркфлоу.
Дозволяє імпортувати JSON воркфлоу з різних джерел (GitHub, n8n.io, файли, локальна папка),
індексувати їх у SQLite з повнотекстовим пошуком (FTS5), фільтрувати за категоріями та типами нод.

**Мова інтерфейсу:** українська.

---

## Стек технологій

| Технологія | Версія | Призначення |
|---|---|---|
| Python | 3.11+ | Backend |
| FastAPI | 0.115+ | Web framework (ASGI) |
| Uvicorn | 0.34+ | ASGI server |
| SQLite + FTS5 | вбудований | БД + повнотекстовий пошук |
| Jinja2 | 3.1+ | HTML шаблони |
| httpx | 0.28+ | Async HTTP клієнт (GitHub API, n8n.io) |
| google-generativeai | 0.8+ | Gemini AI для аналізу та пошуку |
| starlette SessionMiddleware | — | Session-based авторизація |
| python-multipart | — | Обробка файлів (upload) |
| itsdangerous | — | Підпис сесій |

---

## Структура файлів

```
d:\PROJECT\N8N Find workflows\
├── CLAUDE.md               ← ЦЕЙ ФАЙЛ (архітектура для AI)
├── app.py                  ← FastAPI сервер, API routes, auth (~308 рядків)
├── database.py             ← SQLite + FTS5, CRUD операції (~361 рядків)
├── importer.py             ← Парсинг JSON, імпорт з джерел (~420 рядків)
├── analyzer.py             ← AI-аналіз воркфлоу (Gemini) (~201 рядків)
├── ai_search.py            ← AI Chat Search (Gemini) (~129 рядків)
├── templates/
│   └── index.html          ← Єдиний HTML шаблон, вся UI (~1809 рядків)
├── Dockerfile              ← Docker образ (python:3.12-slim)
├── docker-compose.yml      ← Docker Compose конфігурація
├── .dockerignore           ← Docker ігнорування
├── requirements.txt        ← Python залежності
├── .env.example            ← Приклад env змінних
├── .gitignore              ← Git ігнорування (data/workflows/ ігнорується)
├── README.md               ← Документація для користувачів
└── data/
    └── workflows/          ← ~4186 JSON файлів воркфлоу (НЕ в git, тільки локально)
```

---

## Архітектура

### Архітектурна діаграма

```mermaid
graph TD
    Sources[Sources: GitHub, Files, n8n.io] --> Importer[importer.py]
    Importer --> Metadata[Metadata: nodes, categories, triggers]
    Metadata --> DB_Write[database.py: insert_workflows_batch]
    DB_Write --> SQLite[(SQLite: workflows)]
    SQLite --> FTS[SQLite FTS5: workflows_fts]

    SQLite --> Analyzer[analyzer.py: Gemini AI]
    Analyzer --> Scores[Scores: Usefulness, Complexity, etc.]
    Scores --> SQLite

    User[User Query] --> AI_Search[ai_search.py: Gemini AI]
    AI_Search --> FTS_Query[Optimized FTS5 Query + Filters]
    FTS_Query --> SQLite
    SQLite --> UI[templates/index.html]
```

### Як це працює (Логіка)

1. **Ініціалізація**: При першому запуску (`lifespan`) додаток перевіряє `DB_PATH`. Якщо БД порожня, він сканує `LOCAL_WORKFLOWS_DIR` та виконує масовий імпорт через `insert_workflows_batch`. Також може імпортувати з `INITIAL_REPOS` (GitHub URLs).
2. **Аналіз метаданих**: `importer.py` не просто читає JSON, а парсить його структуру, рахує ноди та автоматично призначає категорії за типом нод (на основі `NODE_CATEGORIES`). Це дозволяє фільтрувати воркфлоу без AI.
3. **AI-Збагачення**: `analyzer.py` працює асинхронно. Він бере JSON структуру воркфлоу, відправляє в Gemini та отримує оцінки (1-10) та summary. Це дозволяє ранжувати воркфлоу за якістю.
4. **Розумний пошук**: Коли користувач пише в чат, `ai_search.py` запитує Gemini: "На що це схоже з наших категорій/нод?". AI повертає не просто відповідь, а параметри для SQL запиту.
5. **Продуктивність**: Вся база (~4200 записів) працює миттєво завдяки SQLite FTS5 (повнотекстовий пошук) та lookup-таблицям для нод і категорій (O(1) замість O(n)).

### Таблиці БД

| Таблиця | Призначення |
|---|---|
| `workflows` | Основна: id, name, description, nodes (JSON), categories (JSON), node_count, trigger_type, source_url, source_repo, json_content, json_hash (UNIQUE), added_at, updated_at, ai_usefulness, ai_universality, ai_complexity, ai_scalability, ai_summary, ai_tags (JSON), ai_analyzed_at, ai_use_cases (JSON), ai_target_audience, ai_integrations_summary, ai_difficulty_level |
| `github_repos` | Зареєстровані GitHub репо для авто-синхронізації: id, repo_url (UNIQUE), last_synced, workflow_count, enabled |
| `workflow_nodes` | Lookup: workflow_id + node_name (для O(1) фільтрів) |
| `workflow_categories` | Lookup: workflow_id + category_name (для O(1) фільтрів) |
| `workflows_fts` | FTS5 віртуальна таблиця (name, description, nodes, categories). Оновлюється тригерами |

**Важливо:** lookup-таблиці `workflow_nodes` та `workflow_categories` дублюють дані з JSON полів `nodes` і `categories` таблиці `workflows`. Це зроблено для швидких фільтрів замість O(n) парсингу JSON. При зміні nodes/categories потрібно оновлювати обидва місця.

### Авторизація

- **Google OAuth**: Основний метод входу через `authlib`.
- **Адміністратор**: Тільки користувач з email `goodstaffshop@gmail.com` має права адміністратора.
- **Session-based**: Через `starlette.middleware.sessions.SessionMiddleware` (cookies з підписом `SECRET_KEY`).
- **Рівні доступу**:
  - Гість/Користувач: Перегляд, пошук, AI Chat (read-only).
  - Адмін: Імпорт, видалення воркфлоу, управління GitHub репозиторіями, пакетний AI-аналіз.
- **Fallback**: Legacy логін `ADMIN_USER`/`ADMIN_PASS` доступний як запасний варіант (backend).

---

## Ключові функції по файлах

### database.py

| Функція | Опис |
|---|---|
| `get_db()` | Thread-local з'єднання SQLite (**DELETE mode**, foreign keys) |
| `init_db()` | Створення таблиць, індексів, FTS5, тригерів + міграції |
| `_migrate_ai_columns()` | Додавання AI-колонок якщо їх ще нема |
| `_migrate_lookup_tables()` | Заповнення lookup-таблиць з існуючих даних (одноразова міграція) |
| `insert_workflow(...)` | Вставка одного воркфлоу + lookup записи |
| `insert_workflows_batch(data)` | Batch вставка в одній транзакції. Повертає (imported, duplicates) |
| `search_workflows(query, category, node, page, sort, min_score)` | FTS5 пошук + фільтри через subquery по lookup-таблицях |
| `get_workflow(id)` | Отримати один воркфлоу за ID |
| `delete_workflow(id)` | Видалити (CASCADE видаляє lookup + FTS) |
| `get_all_nodes()` | `SELECT DISTINCT node_name FROM workflow_nodes` |
| `get_all_categories()` | `SELECT DISTINCT category_name FROM workflow_categories` |
| `get_stats()` | Кількість: workflows, repos, unique nodes, analyzed, avg_usefulness |
| `update_workflow_ai(wf_id, ...)` | Оновити AI-аналіз для воркфлоу |
| `get_unanalyzed_workflows(limit)` | Вибрати ще не проаналізовані |
| `add_github_repo(url)` | Додати репо для синхронізації |
| `get_github_repos()` | Список репо |
| `update_repo_sync(url, count)` | Оновити дату синхронізації |
| `delete_github_repo(id)` | Видалити репо + його воркфлоу |

### importer.py

| Функція | Опис |
|---|---|
| `parse_workflow_json(json_str)` | Парсинг n8n JSON → dict з metadata. Визначає nodes, categories (за NODE_CATEGORIES маппінгом), trigger_type (за TRIGGER_NODES) |
| `import_from_json(json_str)` | Імпорт одного воркфлоу з JSON рядка |
| `import_from_directory(dir_path)` | Batch імпорт всіх *.json з локальної папки |
| `import_from_url(url)` | Маршрутизація: визначає тип URL → відповідний метод |
| `_import_github_raw(url)` | Імпорт одного файлу з raw.githubusercontent.com |
| `_get_default_branch(client, owner, repo)` | Визначення default branch через GitHub API |
| `_import_github_dir(url)` | **ZIP-метод**: завантажує весь репо як ZIP, витягує JSON файли, batch insert |
| `_import_n8n_io(url)` | Імпорт з n8n.io/workflows/ID |
| `sync_github_repo(url)` | Ре-синхронізація одного репо |
| `sync_all_repos()` | Синхронізація всіх enabled репо |

**NODE_CATEGORIES** — маппінг `n8n-nodes-base.slack` → `"Комунікація"` тощо (73 записи, 14 категорій).
**TRIGGER_NODES** — маппінг тригерних нод → тип тригера (8 записів).

### analyzer.py

| Функція | Опис |
|---|---|
| `analyze_workflow(wf)` | Аналіз одного воркфлоу через Gemini. Повертає dict зі scores та summary |
| `analyze_and_save(wf_id)` | Аналіз + збереження в БД |
| `analyze_batch(limit)` | Пакетний аналіз непроаналізованих воркфлоу (з паузою 1с між запитами) |

### ai_search.py

| Функція | Опис |
|---|---|
| `translate_query(user_query)` | Конвертує природну мову → параметри пошуку через Gemini |
| `perform_ai_search(query, page)` | Повний AI-пошук: translate → search_workflows → parse → return |

### app.py

| Endpoint | Метод | Опис |
|---|---|---|
| `GET /` | GET | Головна сторінка (Jinja2) |
| `GET /health` | GET | Health check для Docker |
| `POST /api/login` | POST | Авторизація |
| `POST /api/logout` | POST | Вихід |
| `GET /api/search` | GET | Пошук (q, category, node, page, sort, min_score) |
| `GET /api/workflow/{id}` | GET | Деталі воркфлоу |
| `GET /api/workflow/{id}/json` | GET | Завантажити JSON файл |
| `GET /api/workflow/{id}/import` | GET | n8n Import from URL (чистий JSON) |
| `DELETE /api/workflow/{id}` | DELETE | Видалити (auth) |
| `POST /api/import/url` | POST | Імпорт за URL (auth) |
| `POST /api/import/json` | POST | Імпорт JSON тексту (auth) |
| `POST /api/import/file` | POST | Імпорт JSON файлу (auth) |
| `POST /api/import/local` | POST | Імпорт з локальної папки (auth) |
| `GET /api/repos` | GET | Список GitHub репо (auth) |
| `POST /api/repos/sync/{id}` | POST | Синхронізувати репо (auth) |
| `POST /api/repos/sync-all` | POST | Синхронізувати всі (auth) |
| `DELETE /api/repos/{id}` | DELETE | Видалити репо (auth) |
| `POST /api/analyze/{id}` | POST | AI-аналіз одного (auth) |
| `POST /api/analyze/batch` | POST | AI-аналіз партією (auth) |
| `POST /api/chat` | POST | AI Chat Search |
| `GET /api/auth/google/login` | GET | Ініціація Google OAuth |
| `GET /api/auth/google/callback`| GET | Коллбек від Google (auth success) |
| `POST /api/admin/analyze-all` | POST | Аналізувати всеAI (admin only) |
| `POST /api/admin/clear-all` | POST | Повне очищення БД (admin only) |
| `GET /api/filters` | GET | Списки нод та категорій |
| `GET /api/stats` | GET | Статистика |

### templates/index.html

Єдиний HTML файл (~1809 рядків), що містить:
- **CSS** (~1056 рядків): Dark theme, CSS custom properties, responsive, AI chat стилі
- **HTML** (~226 рядків): Header, stats bar, search/filters, grid, 5 modals (detail, import, auth, repos), AI chat widget
- **JavaScript** (~527 рядків): Vanilla JS, no frameworks
  - Пошук з debounce 300ms
  - Рендер карток та пагінації з AI scores
  - Імпорт (3 таби: URL, JSON, File)
  - Управління репозиторіями
  - AI Chat Search (floating widget)
  - AI аналіз окремих воркфлоу та batch
  - Instant Import URL для n8n
  - Toast notifications
  - XSS захист через `esc()` функцію

---

## Змінні оточення

| Змінна | Default | Опис |
|---|---|---|
| `ADMIN_USER` | `admin` | Логін адміністратора |
| `ADMIN_PASS` | `changeme` | Пароль адміністратора |
| `SECRET_KEY` | `n8n-hub-secret-key-change-me` | Ключ для підпису сесій |
| `DB_PATH` | `./workflows.db` | Шлях до SQLite БД |
| `LOCAL_WORKFLOWS_DIR` | `./data/workflows` | Папка з JSON воркфлоу для автоімпорту при першому запуску |
| `INITIAL_REPOS` | `""` | Comma-separated GitHub URLs для імпорту при першому запуску |
| `GITHUB_TOKEN` | `""` | GitHub Personal Access Token (для збільшення rate limit) |
| `SYNC_INTERVAL_HOURS` | `24` | Інтервал автосинхронізації GitHub репо (годин) |
| `GEMINI_API_KEY` | `""` | Google AI (Gemini) API Key |
| `GEMINI_MODEL` | `models/gemini-flash-latest` | Модель Gemini для аналізу |
| `GOOGLE_CLIENT_ID` | `""` | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | `""` | Google OAuth Client Secret |
| `PYTHONUNBUFFERED` | `1` | Рекомендовано для логів |

---

## Поточний стан деплою

### Продакшен: EasyPanel

- **Сервер**: VPS 144.91.71.55
- **Домен**: `finder-n8n-templates-finder-n8n-templates.g3fhgi.easypanel.host`
- **GitHub repo**: `https://github.com/dollarnuk/finder-n8n-templates.git` (branch: main)
- **Dockerfile**: Python 3.12-slim, порт 8000, healthcheck
- **Volume**: `n8n-hub-data` → `/data` (SQLite БД)

### Environment vars в EasyPanel:
```
ADMIN_PASS=<ваш пароль>
SECRET_KEY=<ваш secret key>
GEMINI_API_KEY=<ваш Gemini API key>
GEMINI_MODEL=models/gemini-flash-latest
GITHUB_TOKEN=<ваш GitHub PAT token>
```
**Реальні значення зберігаються в EasyPanel та .env (не в git).**

**ВАЖЛИВО — НЕ встановлювати** `INITIAL_REPOS=default` або `INITIAL_REPOS=<URL власного коду>`. Або залишити порожнім, або вставити URL з воркфлоу (наприклад DragonJAR).

---

## Що зроблено (повний список)

### Фаза 1 — Базовий функціонал (завершена)

1. **Thread-local DB з'єднання** — замість створення нового на кожен запит
2. **Lookup-таблиці** `workflow_nodes` та `workflow_categories` — для O(1) фільтрів замість O(n) парсингу JSON
3. **Batch import** `insert_workflows_batch()` — в одній транзакції, швидкий масовий імпорт
4. **Локальний імпорт** `import_from_directory()` — імпорт з локальної ФС без мережі
5. **GitHub token** — `GITHUB_TOKEN` env var для збільшення rate limit
6. **Auto branch detection** — `_get_default_branch()` визначає default branch через API
7. **Повністю працюючий додаток** — пошук, фільтри, авторизація, імпорт, деталі воркфлоу, завантаження JSON

### Фаза 2 — AI-функції (завершена)

1. **AI-аналіз** (`analyzer.py`): Gemini аналізує кожен воркфлоу → оцінки usefulness/universality/complexity/scalability (1-10) + summary українською + tags
2. **AI Chat Search** (`ai_search.py`): природна мова → FTS5 запит через Gemini
3. **Instant Import**: `GET /api/workflow/{id}/import` — пряме посилання для n8n "Import from URL"
4. **UI для AI**: floating chat widget, AI scores на картках, AI detail view з 4 оцінками, batch аналіз

### Фаза 3 — Docker та деплой (завершена)

1. **Dockerfile**: python:3.12-slim, healthcheck, persistent volume на `/data`
2. **docker-compose.yml**: production config з volume
3. **.dockerignore**: виключає .git, data/, *.db, .env, __pycache__
4. **.gitignore**: data/workflows/ виключений (73MB JSON файлів)
5. **Деплой на EasyPanel**: працює, Docker build успішний
6. **SQLite DELETE mode**: замість WAL (WAL несумісний з Docker overlay FS)
7. **ZIP-імпорт з GitHub**: завантажує весь репо як ZIP замість поштучних API-запитів (вирішує проблему truncation)

### Відомі проблеми

1. **GitHub імпорт через INITIAL_REPOS неповний**: DragonJAR repo має ~4200 файлів, але через EasyPanel/Docker обмеження імпортується лише ~700-900. Причина: або timeout при завантаженні великого ZIP, або обмеження пам'яті контейнера.
2. **Відсутність прогрес-бару**: імпорт з GitHub — довгий процес без зворотного зв'язку в UI.

---

### Фаза 4 — AI-аналіз ПРИ ІМПОРТІ, Валідація та UI (завершена)

1. **AI-аналіз при імпорті**: Тепер `import_from_json()` та `import_from_url()` автоматично викликають `analyze_and_save()`, якщо передано `analyze=True`.
2. **Розширені метадані**: Додано поля `ai_use_cases`, `ai_target_audience`, `ai_integrations_summary`, `ai_difficulty_level`. Промпт в `analyzer.py` оновлено для їх генерації.
3. **Сувора валідація**: `parse_workflow_json()` тепер перевіряє структуру n8n (наявність `nodes`), мінімальний розмір файлу та валідність JSON.
4. **Покращений UI**: 
   - Підтримка Multi-file upload та Drag & Drop.
   - Прогрес-бар для пакетного імпорту.
   - Таблиця результатів зі статусами (OK, Дублікат, Помилка).
   - Відображення нових AI-даних у модальному вікні деталей.

---

### Фаза 6 — Google Drive та Адмін-панель (завершена)

1. **Імпорт з Google Drive**: `importer.py` підтримує прямі посилання на файли.
2. **Адмін-інструменти**: 
   - `doClearAllWorkflows()` — повне видалення бази.
   - `doAnalyzeAllUnanalyzed()` — масовий аналіз через Gemini.
3. **UI для адміна**: Окремий розділ у модалці репозиторіїв з "червоними" кнопками.

---

### Фаза 7 — Google OAuth Авторизація (завершена)

1. **Backend Auth**: Інтеграція `authlib`, сесії Starlette.
2. **Google Login Popup**: Фронтенд відкриває вікно авторизації та отримує результат через `postMessage`.
3. **Hardcoded Admin**: Чітке обмеження прав для `goodstaffshop@gmail.com`.
4. **Header Profile**: Відображення аватара та імені користувача з Google.
5. **Security logic**: `require_auth` декоратор з параметром `admin_only`.

---

### Фаза 9 — Оптимізація та фоновий AI-аналіз (Пріоритет)
- Перенести `analyze_and_save` у `BackgroundTasks` FastAPI.
- Пришвидшити імпорт великих GitHub репозиторіїв та Google Drive файлів.
- Додати індикатор статусу AI-аналізу в UI.

### Фаза 10 — Монетизація та Реліз
- Підписочна модель: $1-5/місяць
- Безкоштовний доступ: перегляд, базовий пошук
- Платний: AI-пошук, завантаження JSON, instant import, доступ до всієї бази
- Реєстрація користувачів (зараз тільки один admin)
- Stripe або інша платіжна система

### Конкурентний аналіз
Перед монетизацією потрібно дослідити конкурентів:
- **n8n.io/workflows** — офіційна бібліотека шаблонів (безкоштовна)
- Інші третьосторонні n8n-маркетплейси
- Порівняти функції, UX, ціни

### Інші ідеї
- [ ] Тегування воркфлоу (кастомні мітки)
- [ ] Улюблені / обрані воркфлоу
- [ ] Порівняння двох воркфлоу
- [ ] Мультимовність (зараз тільки українська)
- [ ] Експорт колекції як ZIP
- [ ] Статистика популярності (перегляди, завантаження)

---

## Як запустити локально

```bash
# 1. Перейти в папку проєкту
cd "d:\PROJECT\N8N Find workflows"

# 2. Встановити залежності
pip install -r requirements.txt

# 3. Створити .env (скопіювати з .env.example)
# Обов'язково: ADMIN_PASS, SECRET_KEY, GEMINI_API_KEY

# 4. Запустити
uvicorn app:app --host 0.0.0.0 --port 8000
# Або:
python app.py
```

Відкрити: http://localhost:8000

При першому запуску, якщо БД порожня і `LOCAL_WORKFLOWS_DIR` вказує на папку з JSON файлами, автоматично імпортуються всі.

---

## Як деплоїти на EasyPanel (Docker)

### Поточна конфігурація
1. GitHub repo: `dollarnuk/finder-n8n-templates`, branch `main`
2. Build path: `/`, Dockerfile: `Dockerfile`
3. Порт: **8000**
4. Volume: `n8n-hub-data` → `/data`
5. Env vars: див. розділ "Поточний стан деплою" вище

### Перебудова
Після push в main, в EasyPanel натиснути "Rebuild" або налаштувати auto-deploy.

```bash
# Або через docker-compose локально:
docker-compose up -d --build
```

---

## Важливі нюанси для розробників

1. **SQLite DELETE mode (НЕ WAL!)** — `database.py:18` використовує `PRAGMA journal_mode=DELETE`. WAL mode спричиняє `disk I/O error` на Docker overlay filesystem. **Ніколи не змінюйте на WAL для Docker.**

2. **FTS5 тригери** — при INSERT/UPDATE/DELETE в `workflows` таблиці, FTS5 оновлюється автоматично через SQL тригери. Не потрібно вручну оновлювати `workflows_fts`.

3. **Lookup-таблиці** — при вставці нового воркфлоу, `insert_workflow()` та `insert_workflows_batch()` автоматично заповнюють `workflow_nodes` і `workflow_categories`. При видаленні, CASCADE автоматично видаляє пов'язані записи.

4. **JSON hash** — дедуплікація по `json_hash` (SHA256[:16]). Якщо воркфлоу з таким хешем вже є, повернеться `IntegrityError` і він буде пропущений.

5. **XSS захист** — у фронтенді всі дані проходять через `esc()` функцію перед вставкою в DOM. При додаванні нового коду, завжди використовуйте `esc()` для user-generated content.

6. **Категорії** — визначаються автоматично за типом нод через `NODE_CATEGORIES` маппінг в `importer.py`. Для додавання нової категорії, додайте маппінг в цей словник.

7. **Gemini SDK нюанси**:
   - Використовуйте `transport="rest"` у `genai.configure()`. gRPC може зависати в деяких середовищах Windows та Docker.
   - Викликайте `model.generate_content` через `asyncio.to_thread()`, навіть якщо бібліотека має асинхронні методи. Це вирішує проблему з "awaitable properties" та неочікуваною поведінкою SDK.
   - Бажана модель: `models/gemini-flash-latest` (або `gemini-1.5-flash`).
   - Rate limit free tier: ~15 RPM. Використовуйте `await asyncio.sleep(1.0)` між запитами.

8. **AI Search (FTS5)**: `ai_search.py` конвертує запит користувача у JSON з `fts_query`. Це поле автоматично розбивається на слова з оператором `OR` для максимального покриття через FTS5.

9. **GitHub ZIP імпорт**: `_import_github_dir()` завантажує весь репо як ZIP-архів (одним запитом), витягує JSON файли в пам'яті, batch insert кожні 500 штук. Це вирішує проблему truncation API `git/trees`.

10. **data/workflows/ НЕ в git**: Папка з ~4186 JSON файлами (73MB) додана в .gitignore. Для деплою використовуйте INITIAL_REPOS або імпорт через UI.

11. **Сувора валідація JSON**: `importer.py` містить логіку, яка відхиляє занадто малі файли (<50 байт), невалідний JSON або об'єкти без поля `nodes`. Це запобігає забрудненню БД сміттєвими файлами.

12. **Обробка назв за замовчуванням**: Якщо воркфлоу не має власного імені (поле `name`), система автоматично генерує опис на основі імен перших 10 нод. Це дозволяє зберігати інформативність навіть для "безіменних" шаблонів.

13. **Типізація та стайл-гайд**: Backend використовує Type Hinting для всіх ключових функцій. Коментарі в коді переважно українською мовою для кращої відповідності інтерфейсу. При додаванні нових API ендпоінтів завжди використовуйте `JSONResponse` для одноманітності.
