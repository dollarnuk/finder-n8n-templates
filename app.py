import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

from database import init_db, search_workflows, get_workflow, delete_workflow, \
    get_all_nodes, get_all_categories, get_stats, get_github_repos, delete_github_repo, clear_all_workflows
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

# OAuth Config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'

oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=CONF_URL,
    client_kwargs={
        'scope': 'openid email profile'
    }
)

ADMIN_EMAIL = "goodstaffshop@gmail.com"


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
    return request.session.get("user") is not None


def is_admin(request: Request) -> bool:
    user = request.session.get("user")
    if not user:
        return False
    return user.get("email") == ADMIN_EMAIL


def require_auth(request: Request, admin_only: bool = False):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Необхідна авторизація")
    if admin_only and not is_admin(request):
        raise HTTPException(status_code=403, detail="Доступ лише для адміністратора")


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
        "is_admin": is_admin(request),
        "user": request.session.get("user"),
    })


# ==================== OAuth Routes ====================

@app.get("/api/auth/google/login")
async def google_login(request: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth не налаштовано (відсутні Client ID/Secret)")
    
    redirect_uri = request.url_for('google_auth_callback')
    
    # Support HTTPS behind proxy (like EasyPanel/Cloudflare)
    # Check X-Forwarded-Proto header first
    if request.headers.get("x-forwarded-proto") == "https":
        redirect_uri = str(redirect_uri).replace("http://", "https://")
    elif "easypanel.host" in str(redirect_uri) and not str(redirect_uri).startswith("https"):
        redirect_uri = str(redirect_uri).replace("http://", "https://")
    
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@app.get("/api/auth/google/callback")
async def google_auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            request.session['user'] = {
                'email': user['email'],
                'name': user.get('name', user['email'].split('@')[0]),
                'picture': user.get('picture', '')
            }
            logger.info(f"User logged in: {user['email']}")
        return HTMLResponse("<script>window.opener.postMessage('auth_success', '*'); window.close();</script>")
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        return HTMLResponse(f"<script>alert('Помилка входу: {str(e)}'); window.close();</script>")


@app.post("/api/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # Legacy login kept for now but could be removed
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = {"email": "admin@local", "name": "Admin (Local)"}
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
    require_auth(request, admin_only=True)
    delete_workflow(wf_id)
    return JSONResponse({"status": "ok"})


@app.post("/api/import/url")
async def api_import_url(request: Request, background_tasks: BackgroundTasks, url: str = Form(...)):
    require_auth(request, admin_only=True)
    try:
        # Import is now fast (no blocking AI)
        result = await import_from_url(url, analyze=False)
        if result.get("status") == "ok":
            # Schedule AI analysis in background
            background_tasks.add_task(analyze_batch, limit=50)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"URL import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.post("/api/import/json")
async def api_import_json(request: Request, background_tasks: BackgroundTasks, json_text: str = Form(...), name: str = Form("")):
    require_auth(request, admin_only=True)
    try:
        result = await import_from_json(json_text, analyze=False)
        if result.get("status") == "ok":
            background_tasks.add_task(analyze_batch, limit=50)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"JSON import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.post("/api/import/file")
async def api_import_file(request: Request, background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)):
    require_auth(request, admin_only=True)
    results = []
    for file in files:
        try:
            content = await file.read()
            res = await import_from_json(content.decode("utf-8"), source_url=f"upload:{file.filename}", analyze=False)
            results.append({"name": file.filename, "status": res["status"]})
        except Exception as e:
            results.append({"name": file.filename, "status": "error", "message": str(e)})
    
    # Schedule background analysis if anything was imported
    if any(r["status"] == "ok" for r in results):
        background_tasks.add_task(analyze_batch, limit=50)
        
    return JSONResponse({"status": "ok", "results": results})


@app.post("/api/import/local")
async def api_import_local(request: Request, background_tasks: BackgroundTasks, directory: str = Form(...)):
    require_auth(request, admin_only=True)
    try:
        result = await import_from_directory(directory, analyze=False)
        if result.get("status") == "ok" and result.get("imported", 0) > 0:
            background_tasks.add_task(analyze_batch, limit=50)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Local import error: {e}")
        return JSONResponse({"status": "error", "message": "Внутрішня помилка сервера"}, status_code=500)


@app.get("/api/repos")
async def api_get_repos(request: Request):
    require_auth(request, admin_only=True)
    repos = get_github_repos()
    return JSONResponse(repos)


@app.post("/api/repos/sync/{repo_id}")
async def api_sync_repo(request: Request, background_tasks: BackgroundTasks, repo_id: int):
    require_auth(request, admin_only=True)
    repos = get_github_repos()
    repo = next((r for r in repos if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404)
    result = await sync_github_repo(repo["repo_url"])
    if result.get("status") == "ok" and result.get("imported", 0) > 0:
        background_tasks.add_task(analyze_batch, limit=50)
    return JSONResponse(result)


@app.post("/api/repos/sync-all")
async def api_sync_all(request: Request, background_tasks: BackgroundTasks):
    require_auth(request, admin_only=True)
    results = await sync_all_repos()
    # If any repo had new workflows, analyze them
    if any(r.get("imported", 0) > 0 for r in results if isinstance(r, dict)):
        background_tasks.add_task(analyze_batch, limit=50)
    return JSONResponse(results)


@app.delete("/api/repos/{repo_id}")
async def api_delete_repo(request: Request, repo_id: int):
    require_auth(request, admin_only=True)
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
    require_auth(request, admin_only=True)
    result = await analyze_and_save(wf_id)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/analyze/batch")
async def api_analyze_batch(request: Request, limit: int = 50):
    require_auth(request, admin_only=True)
    result = await analyze_batch(limit=limit)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.post("/api/admin/clear-all")
async def api_admin_clear_all(request: Request):
    require_auth(request, admin_only=True)
    try:
        clear_all_workflows()
        return JSONResponse({"status": "ok", "message": "Усі воркфлоу видалено"})
    except Exception as e:
        logger.error(f"Clear all error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/api/admin/analyze-all")
async def api_admin_analyze_all(request: Request):
    require_auth(request, admin_only=True)
    try:
        # High limit to analyze everything unanalyzed
        result = await analyze_batch(limit=1000)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Analyze all error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


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
