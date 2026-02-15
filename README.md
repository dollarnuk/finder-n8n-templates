# n8n Hub — База воркфлоу та AI Помічник

**n8n Hub** — це високопродуктивний веб-додаток для пошуку, перегляду та інтелектуального аналізу n8n воркфлоу. Система перетворює звичайну колекцію JSON файлів на активну базу знань з AI-пошуком та автоматичною оцінкою якості.

## Головні можливості

- **AI Chat Search** — інтелектуальний пошук природною мовою (через Gemini API). **Ліміт: 3 безкоштовні пошуки**.
- **Pro Subscription (WayForPay)** — необмежений AI-пошук. Підтримка оплат з усього світу (UAH/USD).
- **AI Workflow Analysis** — автоматична оцінка корисності, універсальності та складності (UK + EN).
- **Миттєвий імпорт в n8n** — кнопка копіювання спеціального URL для функції `Import from URL`.
- **Повнотекстовий пошук** — миттєвий пошук через SQLite FTS5 по назвах, описах та типах вузлів.
- **Масовий імпорт** — підтримка GitHub репозиторіїв та локальних папок (~4200 воркфлоу за секунди).
- **Фільтри** — категорізація за вузлами та типами тригерів.
- **Автосинхронізація** з GitHub репозиторіями (за розкладом).
- **Мультимовність** — інтерфейс та AI-аналіз українською та англійською.
- **Авторизація та профілі** — Google OAuth, збереження даних користувача в БД, відстеження активності.
- **Адаптивний дизайн** — працює на десктопі та мобільних.
- **Docker** — один контейнер, простий деплой.

## Швидкий старт (локально)

```bash
# Встановити залежності
pip install -r requirements.txt

# Запустити (автоімпорт з data/workflows/ при першому запуску)
uvicorn app:app --host 0.0.0.0 --port 8000

# Відкрити http://localhost:8000
```

При першому запуску, якщо БД порожня і папка `data/workflows/` містить JSON файли, вони будуть автоматично імпортовані (~4170 воркфлоу за ~10 секунд).

## Швидкий старт з Docker

```bash
# Налаштуйте змінні
cp .env.example .env
# відредагуйте .env — змініть ADMIN_PASS та SECRET_KEY

# Запуск
docker compose up -d

# Відкрийте http://localhost:8000
```

## Структура проєкту

```
├── CLAUDE.md               # Архітектура та інструкції для AI-асистентів
├── app.py                  # FastAPI сервер + API роути + Google OAuth
├── database.py             # SQLite + FTS5 пошук
├── importer.py             # Парсинг та імпорт воркфлоу
├── analyzer.py             # AI-аналіз воркфлоу (Gemini, retry, rate limit)
├── ai_search.py            # AI Chat Search (Gemini)
├── templates/
│   └── index.html          # Веб-інтерфейс (UK + EN)
├── data/
│   └── workflows/          # JSON файли воркфлоу
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

**Стек**: Python, FastAPI, SQLite FTS5, Jinja2, httpx, Gemini AI

> Детальна архітектура та інструкції для розробників — див. [CLAUDE.md](CLAUDE.md)

## Змінні оточення

| Змінна | Default | Опис |
|---|---|---|
| `ADMIN_USER` | `admin` | Логін |
| `ADMIN_PASS` | `changeme` | Пароль |
| `SECRET_KEY` | `...` | Ключ для сесій |
| `DB_PATH` | `./workflows.db` | Шлях до SQLite БД |
| `LOCAL_WORKFLOWS_DIR` | `./data/workflows` | Папка для автоімпорту |
| `GITHUB_TOKEN` | — | GitHub PAT (для rate limit) |
| `SYNC_INTERVAL_HOURS` | `24` | Інтервал синхронізації (годин) |
| `GEMINI_API_KEY` | — | Ключ Google Gemini AI |
| `GEMINI_MODEL` | `models/gemini-flash-latest` | Модель AI (рекомендовано `models/gemini-2.0-flash`) |
| `GOOGLE_CLIENT_ID` | — | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth Client Secret |

## API

| Метод | URL | Опис |
|---|---|---|
| GET | `/api/search?q=&category=&node=&page=` | Пошук воркфлоу |
| GET | `/api/workflow/{id}` | Деталі воркфлоу |
| GET | `/api/workflow/{id}/json` | Завантажити JSON |
| POST | `/api/import/url` | Імпорт за URL (auth) |
| POST | `/api/import/json` | Імпорт JSON (auth) |
| POST | `/api/import/file` | Імпорт файлу (auth) |
| POST | `/api/import/local` | Імпорт з папки (auth) |
| GET | `/api/repos` | Список репозиторіїв (auth) |
| POST | `/api/repos/sync/{id}` | Синхронізувати репо (auth) |
| POST | `/api/repos/sync-all` | Синхронізувати все (auth) |
| DELETE | `/api/repos/{id}` | Видалити репо (auth) |
| DELETE | `/api/workflow/{id}` | Видалити воркфлоу (auth) |
| GET | `/api/stats` | Статистика |
| GET | `/api/filters` | Доступні фільтри |
| POST | `/api/login` | Авторизація |
| POST | `/api/logout` | Вихід |
| POST | `/api/analyze/{id}` | AI-аналіз одного воркфлоу (auth) |
| POST | `/api/analyze/batch` | AI-аналіз партією (auth) |
| POST | `/api/chat` | AI Chat Search (пошук природною мовою) |
| GET | `/api/workflow/{id}/import` | Миттєвий імпорт в n8n |
| GET | `/api/auth/google/login` | Google OAuth логін |
| GET | `/api/auth/me` | Поточний користувач (avatar, email) |
| POST | `/api/admin/analyze-all` | AI-аналіз всіх (admin) |
| POST | `/api/admin/clear-all` | Очистити БД (admin) |

## Деплой на EasyPanel

1. Завантажте проєкт у GitHub репозиторій
2. В EasyPanel: **Service** → **App** → GitHub → ваш репо
3. Build: Docker (автоматично знайде Dockerfile)
4. Environment Variables: `ADMIN_PASS`, `SECRET_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
5. Вкажіть змінні для **WayForPay** в `.env`:
   - `WFP_MERCHANT_ACCOUNT`
   - `WFP_MERCHANT_SECRET_KEY`
   - `WFP_MERCHANT_DOMAIN` (домен вашого сайту)
6. Volumes: `/data` для збереження БД
7. Port: `8000`
8. Налаштуйте домен + HTTPS
