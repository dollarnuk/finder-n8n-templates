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
| starlette SessionMiddleware | — | Session-based авторизація |
| python-multipart | — | Обробка файлів (upload) |
| itsdangerous | — | Підпис сесій |

---

## Структура файлів

```
d:\PROJECT\N8N Find workflows\
├── CLAUDE.md               ← ЦЕЙ ФАЙЛ (архітектура для AI)
├── app.py                  ← FastAPI сервер, API routes, auth (250 рядків)
├── database.py             ← SQLite + FTS5, CRUD операції (287 рядків)
├── importer.py             ← Парсинг JSON, імпорт з джерел (420 рядків)
├── analyzer.py             ← Менеджер AI-аналізу (Gemini)
├── ai_search.py            ← AI Chat Search (Gemini)
├── templates/
│   └── index.html          ← Єдиний HTML шаблон, вся UI (957 рядків)
├── Dockerfile              ← Docker образ (python:3.12-slim)
├── docker-compose.yml      ← Docker Compose конфігурація
├── requirements.txt        ← Python залежності
├── .env.example            ← Приклад env змінних
├── .gitignore              ← Git ігнорування
├── README.md               ← Документація для користувачів
└── data/
    └── workflows/          ← 4186 JSON файлів воркфлоу
        ├── 0001-nostr-damus-ai-report.json
        ├── 0002-telegram-math-quiz.json
        └── ... (ще ~4184 файлів)
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

1. **Ініціалізація**: При першому запуску (`lifespan`) додаток перевіряє `DB_PATH`. Якщо БД порожня, він сканує `LOCAL_WORKFLOWS_DIR` та виконує масовий імпорт через `insert_workflows_batch`.
2. **Аналіз метаданих**: `importer.py` не просто читає JSON, а парсить його структуру, рахує ноди та автоматично призначає категорії за типом нод (на основі `NODE_CATEGORIES`). Це дозволяє фільтрувати воркфлоу без AI.
3. **AI-Збагачення**: `analyzer.py` працює асинхронно. Він бере JSON структуру воркфлоу, відправляє в Gemini та отримує оцінки (1-10) та summary. Це дозволяє ранжувати воркфлоу за якістю.
4. **Розумний пошук**: Коли користувач пише в чат, `ai_search.py` запитує Gemini: "На що це схоже з наших категорій/нод?". AI повертає не просто відповідь, а параметри для SQL запиту.
5. **Продуктивність**: Вся база (~4200 записів) працює миттєво завдяки SQLite FTS5 (повнотекстовий пошук) та lookup-таблицям для нод і категорій (O(1) замість O(n)).

### Таблиці БД

| Таблиця | Призначення |
|---|---|
| `workflows` | Основна: id, name, description, nodes (JSON), categories (JSON), node_count, trigger_type, source_url, source_repo, json_content, json_hash (UNIQUE), added_at, updated_at |
| `github_repos` | Зареєстровані GitHub репо для авто-синхронізації: id, repo_url (UNIQUE), last_synced, workflow_count, enabled |
| `workflow_nodes` | Lookup: workflow_id + node_name (для O(1) фільтрів) |
| `workflow_categories` | Lookup: workflow_id + category_name (для O(1) фільтрів) |
| `workflows_fts` | FTS5 віртуальна таблиця (name, description, nodes, categories). Оновлюється тригерами |

**Важливо:** lookup-таблиці `workflow_nodes` та `workflow_categories` дублюють дані з JSON полів `nodes` і `categories` таблиці `workflows`. Це зроблено для швидких фільтрів замість O(n) парсингу JSON. При зміні nodes/categories потрібно оновлювати обидва місця.

### Авторизація

- Session-based через `starlette.middleware.sessions.SessionMiddleware`
- Один адміністратор: `ADMIN_USER` / `ADMIN_PASS` (env vars)
- Сесія зберігається в cookie (підписана `SECRET_KEY`)
- Для перегляду та пошуку авторизація НЕ потрібна
- Для імпорту, видалення, управління репо — потрібна

---

## Ключові функції по файлах

### database.py

| Функція | Опис |
|---|---|
| `get_db()` | Thread-local з'єднання SQLite (WAL mode, foreign keys) |
| `init_db()` | Створення таблиць, індексів, FTS5, тригерів |
| `_migrate_lookup_tables()` | Заповнення lookup-таблиць з існуючих даних (одноразова міграція) |
| `insert_workflow(...)` | Вставка одного воркфлоу + lookup записи |
| `insert_workflows_batch(data)` | Batch вставка в одній транзакції. Повертає (imported, duplicates) |
| `search_workflows(query, category, node, page)` | FTS5 пошук + фільтри через subquery по lookup-таблицях |
| `get_workflow(id)` | Отримати один воркфлоу за ID |
| `delete_workflow(id)` | Видалити (CASCADE видаляє lookup + FTS) |
| `get_all_nodes()` | `SELECT DISTINCT node_name FROM workflow_nodes` |
| `get_all_categories()` | `SELECT DISTINCT category_name FROM workflow_categories` |
| `get_stats()` | Кількість: workflows, repos, unique nodes |
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
| `_import_github_dir(url)` | Імпорт всіх JSON з GitHub директорії (через API trees) |
| `_import_n8n_io(url)` | Імпорт з n8n.io/workflows/ID |
| `sync_github_repo(url)` | Ре-синхронізація одного репо |
| `sync_all_repos()` | Синхронізація всіх enabled репо |

**NODE_CATEGORIES** — маппінг `n8n-nodes-base.slack` → `"Комунікація"` тощо (73 записи, 14 категорій).
**TRIGGER_NODES** — маппінг тригерних нод → тип тригера (8 записів).

### app.py

| Функція / Endpoint | Метод | Опис |
|---|---|---|
| `lifespan()` | — | Startup: init_db, автоімпорт з LOCAL_WORKFLOWS_DIR якщо БД порожня, запуск periodic_sync |
| `periodic_sync()` | — | Background task: sync_all_repos кожні SYNC_INTERVAL_HOURS годин |
| `GET /` | GET | Головна сторінка (Jinja2 рендер index.html зі stats, nodes, categories) |
| `POST /api/login` | POST | Авторизація (form: username, password) |
| `POST /api/logout` | POST | Вихід |
| `GET /api/search` | GET | Пошук (query params: q, category, node, page) |
| `GET /api/workflow/{id}` | GET | Деталі воркфлоу |
| `GET /api/workflow/{id}/json` | GET | Завантажити JSON файл |
| `DELETE /api/workflow/{id}` | DELETE | Видалити воркфлоу (потрібна auth) |
| `POST /api/import/url` | POST | Імпорт за URL (form: url) (потрібна auth) |
| `POST /api/import/json` | POST | Імпорт JSON тексту (form: json_text) (потрібна auth) |
| `POST /api/import/file` | POST | Імпорт JSON файлу (form: file) (потрібна auth) |
| `POST /api/import/local` | POST | Імпорт з локальної папки (form: directory) (потрібна auth) |
| `GET /api/repos` | GET | Список GitHub репо (потрібна auth) |
| `POST /api/repos/sync/{id}` | POST | Синхронізувати один репо (потрібна auth) |
| `POST /api/repos/sync-all` | POST | Синхронізувати всі репо (потрібна auth) |
| `DELETE /api/repos/{id}` | DELETE | Видалити репо (потрібна auth) |
| `POST /api/analyze/{id}` | POST | AI-аналіз одного воркфлоу (auth) |
| `POST /api/analyze/batch` | POST | AI-аналіз партією (auth) |
| `POST /api/chat` | POST | AI Chat Search (пошук природною мовою) |
| `GET /api/workflow/{id}/import` | GET | Миттєвий імпорт в n8n (Import from URL) |
| `GET /api/filters` | GET | Списки нод та категорій (для оновлення фільтрів) |
| `GET /api/stats` | GET | Статистика |

### templates/index.html

Єдиний HTML файл, що містить:
- **CSS** (382 рядки): Dark theme, CSS custom properties, responsive
- **HTML** (190 рядків): Header, stats bar, search/filters, grid, 4 modals (detail, import, auth, repos)
- **JavaScript** (385 рядків): Vanilla JS, no frameworks
  - Пошук з debounce 300ms
  - Рендер карток та пагінації
  - Імпорт (3 таби: URL, JSON, File)
  - Управління репозиторіями
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
| `GEMINI_MODEL` | `gemini-flash-latest` | Модель Gemini для аналізу |
| `PYTHONUNBUFFERED` | `1` | Рекомендовано для логів |

---

## Що зроблено (Фаза 1 — завершена)

1. **Thread-local DB з'єднання** — замість створення нового на кожен запит
2. **Lookup-таблиці** `workflow_nodes` та `workflow_categories` — для O(1) фільтрів замість O(n) парсингу JSON
3. **Batch import** `insert_workflows_batch()` — в одній транзакції, швидкий масовий імпорт
4. **Локальний імпорт** `import_from_directory()` — імпорт з локальної ФС без мережі
5. **GitHub token** — `GITHUB_TOKEN` env var для збільшення rate limit
6. **Auto branch detection** — `_get_default_branch()` визначає default branch через API
7. **Rate limiting** — 100ms пауза кожні 10 запитів, 60s чекання при 403
8. **4170 воркфлоу імпортовано** з колекції DragonJAR/n8n-workflows-esp (14 файлів з невалідним JSON пропущено, 2 дублікати)
9. **Повністю працюючий додаток** — пошук, фільтри, авторизація, імпорт, деталі воркфлоу, завантаження JSON

---

## Що потрібно допрацювати

- [x] **AI-аналіз та оцінка** — `ai_usefulness`, `ai_complexity` тощо (через Gemini)
- [x] **AI Chat-пошук** — природна мова → SQL/FTS5 через AI
- [x] **Instant Import** — URL для прямого імпорту в n8n (Phase 2C)
- [ ] **SSE прогрес-бар для імпорту** — зараз імпорт з GitHub довгий і без зворотного зв'язку.
- [ ] **Searchable dropdowns для фільтрів** — зараз звичайні `<select>`, при 400+ нодах важко знайти потрібну.
- [ ] **Експорт колекції** — завантажити всі або відфільтровані воркфлоу як ZIP

### Фаза 3 — Docker та деплой

- [ ] **Фіналізація Dockerfile** — healthcheck, .dockerignore, оптимізація розміру
- [ ] **Деплой на EasyPanel** — VPS, Docker container, persistent volumes
- [ ] **HTTPS** — через EasyPanel / reverse proxy

### Інші ідеї

- [ ] Тегування воркфлоу (кастомні мітки)
- [ ] Улюблені / обрані воркфлоу
- [ ] Порівняння двох воркфлоу
- [ ] Автоматичний аналіз якості воркфлоу
- [ ] Мультимовність (зараз тільки українська)

---

## Як запустити локально

```bash
# 1. Перейти в папку проєкту
cd "d:\PROJECT\N8N Find workflows"

# 2. Встановити залежності
pip install -r requirements.txt

# 3. Запустити (автоімпорт з data/workflows/ при першому запуску)
uvicorn app:app --host 0.0.0.0 --port 8000

# Або напряму:
python app.py
```

Відкрити: http://localhost:8000

При першому запуску, якщо БД порожня і папка `data/workflows/` існує, автоматично імпортуються всі JSON файли (~4170 воркфлоу за ~10 секунд).

---

## Як деплоїти на EasyPanel (Docker)

```bash
# 1. Побудувати та запустити
docker-compose up -d --build

# 2. Або окремо
docker build -t n8n-hub .
docker run -d -p 8000:8000 -v n8n_data:/data -v ./data/workflows:/app/data/workflows:ro n8n-hub
```

В EasyPanel:
1. Створити сервіс типу "Docker"
2. Вказати репозиторій або завантажити код
3. Встановити env vars (ADMIN_PASS, SECRET_KEY)
4. Підключити persistent volume на `/data`
5. Налаштувати domain + HTTPS

---

## Важливі нюанси для розробників

1. **FTS5 тригери** — при INSERT/UPDATE/DELETE в `workflows` таблиці, FTS5 оновлюється автоматично через SQL тригери. Не потрібно вручну оновлювати `workflows_fts`.

2. **Lookup-таблиці** — при вставці нового воркфлоу, `insert_workflow()` та `insert_workflows_batch()` автоматично заповнюють `workflow_nodes` і `workflow_categories`. При видаленні, CASCADE автоматично видаляє пов'язані записи.

3. **JSON hash** — дедуплікація по `json_hash` (SHA256[:16]). Якщо воркфлоу з таким хешем вже є, повернеться `IntegrityError` і він буде пропущений.

4. **Windows encoding** — при роботі на Windows, `parse_workflow_json` може натрапити на emoji в назвах воркфлоу. Для тестів в консолі використовуйте `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`.

5. **XSS захист** — у фронтенді всі дані проходять через `esc()` функцію перед вставкою в DOM. При додаванні нового коду, завжди використовуйте `esc()` для user-generated content.

6. **Категорії** — визначаються автоматично за типом нод через `NODE_CATEGORIES` маппінг в `importer.py`. Для додавання нової категорії, додайте маппінг в цей словник.

7. **Gemini SDK нюанси**: 
   - Використовуйте `transport="rest"` у `genai.configure()`. gRPC може зависати в деяких середовищах Windows.
   - Викликайте `model.generate_content` через `asyncio.to_thread()`, навіть якщо бібліотека має асинхронні методи. Це вирішує проблему з "awaitable properties" та неочікуваною поведінкою SDK.
   - Бажана модель: `models/gemini-flash-latest` (або `gemini-1.5-flash`).

8. **AI Search (FTS5)**: `ai_search.py` конвертує запит користувача у JSON з `fts_query`. Це поле автоматично розбивається на слова з оператором `OR` для максимального покриття через FTS5.
