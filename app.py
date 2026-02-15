import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import init_db, search_workflows, get_workflow, delete_workflow, \
    get_all_nodes, get_all_categories, get_stats, get_github_repos, delete_github_repo
from importer import import_from_json, import_from_url, import_from_directory, \
    sync_github_repo, sync_all_repos
from analyzer import analyze_and_save, analyze_batch
from ai_search import perform_ai_search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")
SECRET_KEY = os.environ.get("SECRET_KEY", "n8n-hub-secret-key-change-me")
INITIAL_REPOS = os.environ.get("INITIAL_REPOS", "").strip()
LOCAL_WORKFLOWS_DIR = os.environ.get("LOCAL_WORKFLOWS_DIR", "./data/workflows").strip()
SYNC_INTERVAL_HOURS = int(os.environ.get("SYNC_INTERVAL_HOURS", "24"))


async def periodic_sync():
    """Background task to sync repos periodically."""
    while True:
        await asyncio.sleep(SYNC_INTERVAL_HOURS * 3600)
        try:
            logger.info("Starting periodic GitHub sync...")
            results = await sync_all_repos()
            logger.info(f"Sync complete: {results}")
        except Exception as e:
            logger.error(f"Sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    logger.info("Database initialized")

    stats = get_stats()
    if stats["total_workflows"] == 0:
        # Import from local directory first (fast, no network)
        if LOCAL_WORKFLOWS_DIR and os.path.isdir(LOCAL_WORKFLOWS_DIR):
            logger.info(f"Importing from local directory: {LOCAL_WORKFLOWS_DIR}")
            try:
                result = await import_from_directory(LOCAL_WORKFLOWS_DIR)
                logger.info(f"Local import result: {result}")
            except Exception as e:
                logger.error(f"Local import failed: {e}")

        # Then import from remote repos
        if INITIAL_REPOS:
            for repo_url in INITIAL_REPOS.split(","):
                repo_url = repo_url.strip()
                if repo_url:
                    logger.info(f"Initial import: {repo_url}")
                    try:
                        result = await import_from_url(repo_url)
                        logger.info(f"Import result: {result}")
                    except Exception as e:
                        logger.error(f"Initial import failed for {repo_url}: {e}")

    # Start background sync
    sync_task = asyncio.create_task(periodic_sync())

    yield

    sync_task.cancel()


app = FastAPI(title="n8n Hub", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="templates")


# Auth helpers
def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False)


def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Необхідна авторизація")


# ==================== Health Check ====================

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


# ==================== API Routes ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    stats = get_stats()
    nodes = get_all_nodes()
    categories = get_all_categories()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "nodes": nodes,
        "categories": categories,
        "authenticated": is_authenticated(request),
    })


@app.post("/api/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["authenticated"] = True
        return JSONResponse({"status": "ok"})
    raise HTTPException(status_code=401, detail="Невірний логін або пароль")


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "ok"})


@app.get("/api/search")
async def api_search(q: str = "", category: str = "", node: str = "", page: int = 1,
                     sort: str = "recent", min_score: int = 0):
    results = search_workflows(query=q, category=category, node=node, page=page,
                               sort=sort, min_score=min_score)
    for wf in results["workflows"]:
        wf["nodes"] = json.loads(wf["nodes"]) if isinstance(wf["nodes"], str) else wf["nodes"]
        wf["categories"] = json.loads(wf["categories"]) if isinstance(wf["categories"], str) else wf["categories"]
        wf["ai_use_cases"] = json.loads(wf.get("ai_use_cases")) if isinstance(wf.get("ai_use_cases"), str) else wf.get("ai_use_cases", [])
    return JSONResponse(results)


@app.get("/api/workflow/{wf_id}")
async def api_get_workflow(wf_id: int):
    wf = get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Воркфлоу не знайдено")
    wf["nodes"] = json.loads(wf["nodes"]) if isinstance(wf["nodes"], str) else wf["nodes"]
    wf["categories"] = json.loads(wf["categories"]) if isinstance(wf["categories"], str) else wf["categories"]
    wf["ai_tags"] = json.loads(wf["ai_tags"]) if isinstance(wf.get("ai_tags"), str) else wf.get("ai_tags", [])
    wf["ai_use_cases"] = json.loads(wf.get("ai_use_cases")) if isinstance(wf.get("ai_use_cases"), str) else wf.get("ai_use_cases", [])
    return JSONResponse(wf)


@app.get("/api/workflow/{wf_id}/json")
async def api_get_workflow_json(wf_id: int):
    wf = get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Воркфлоу не знайдено")
    return Response(
        content=wf["json_content"],
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{wf["name"]}.json"'}
    )


@app.delete("/api/workflow/{wf_id}")
async def api_delete_workflow(request: Request, wf_id: int):
    require_auth(request)
    delete_workflow(wf_id)
    return JSONResponse({"status": "ok"})


@app.post("/api/import/url")
async def api_import_url(request: Request, url: str = Form(...)):
    require_auth(request)
    try:
        result = await import_from_url(url, analyze=True)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"URL import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.post("/api/import/json")
async def api_import_json(request: Request, json_text: str = Form(...), name: str = Form("")):
    require_auth(request)
    try:
        result = await import_from_json(json_text, analyze=True)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"JSON import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.post("/api/import/file")
async def api_import_file(request: Request, file: UploadFile = File(...)):
    require_auth(request)
    try:
        content = await file.read()
        result = await import_from_json(content.decode("utf-8"), source_url=f"upload:{file.filename}", analyze=True)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"File import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.post("/api/import/local")
async def api_import_local(request: Request, directory: str = Form(...)):
    require_auth(request)
    try:
        result = await import_from_directory(directory, analyze=True)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Local import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.get("/api/repos")
async def api_get_repos(request: Request):
    require_auth(request)
    repos = get_github_repos()
    return JSONResponse(repos)


@app.post("/api/repos/sync/{repo_id}")
async def api_sync_repo(request: Request, repo_id: int):
    require_auth(request)
    repos = get_github_repos()
    repo = next((r for r in repos if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404)
    result = await sync_github_repo(repo["repo_url"])
    return JSONResponse(result)


@app.post("/api/repos/sync-all")
async def api_sync_all(request: Request):
    require_auth(request)
    results = await sync_all_repos()
    return JSONResponse(results)


@app.delete("/api/repos/{repo_id}")
async def api_delete_repo(request: Request, repo_id: int):
    require_auth(request)
    delete_github_repo(repo_id)
    return JSONResponse({"status": "ok"})


@app.get("/api/filters")
async def api_get_filters():
    nodes = get_all_nodes()
    categories = get_all_categories()
    return JSONResponse({"nodes": nodes, "categories": categories})


@app.get("/api/stats")
async def api_get_stats():
    return JSONResponse(get_stats())


# ==================== AI Analysis Routes ====================

@app.post("/api/analyze/{wf_id}")
async def api_analyze_workflow(request: Request, wf_id: int):
    require_auth(request)
    result = await analyze_and_save(wf_id)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/analyze/batch")
async def api_analyze_batch(request: Request, limit: int = 50):
    require_auth(request)
    result = await analyze_batch(limit=limit)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


# ==================== AI Chat Search ====================

@app.post("/api/chat")
async def api_chat_search(request: Request, body: dict = None):
    query = (body or {}).get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    
    result = await perform_ai_search(query)
    return JSONResponse(result)


# ==================== Instant Import for n8n ====================

@app.get("/api/workflow/{wf_id}/import")
async def api_workflow_import_url(wf_id: int):
    """Returns clean n8n JSON for direct import via 'Import from URL' in n8n."""
    wf = get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Воркфлоу не знайдено")
    return Response(
        content=wf["json_content"],
        media_type="application/json",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
