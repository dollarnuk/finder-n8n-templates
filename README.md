# n8n Hub — База воркфлоу

Самохостований веб-додаток для пошуку, перегляду та управління колекцією n8n воркфлоу.

## Можливості

- **Повнотекстовий пошук** — SQLite FTS5, пошук по назві, опису, нодах
- **Фільтри** — по категоріях (AI/LLM, Email, CRM, DevOps...) та типах нод
- **Імпорт** з різних джерел:
  - GitHub репозиторій або папка
  - GitHub raw JSON файл
  - n8n.io/workflows/ (офіційні шаблони)
  - Вставка JSON вручну
  - Завантаження .json файлу
  - Локальна папка (batch імпорт)
- **Автосинхронізація** з GitHub репозиторіями (за розкладом)
- **Авторизація** — перегляд відкритий, редагування за логіном/паролем
- **Адаптивний дизайн** — працює на десктопі та мобільних
- **Docker** — один контейнер, простий деплой

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
├── app.py                  # FastAPI сервер + API роути
├── database.py             # SQLite + FTS5 пошук
├── importer.py             # Парсинг та імпорт воркфлоу
├── templates/
│   └── index.html          # Веб-інтерфейс (українською)
├── data/
│   └── workflows/          # JSON файли воркфлоу (4186 шт.)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

**Стек**: Python, FastAPI, SQLite FTS5, Jinja2, httpx

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

## Деплой на EasyPanel

1. Завантажте проєкт у GitHub репозиторій
2. В EasyPanel: **Service** → **App** → GitHub → ваш репо
3. Build: Docker (автоматично знайде Dockerfile)
4. Environment Variables: `ADMIN_PASS`, `SECRET_KEY`
5. Volumes: `/data` для збереження БД
6. Port: `8000`
7. Налаштуйте домен + HTTPS
