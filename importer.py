import json
import hashlib
import os
import re
import asyncio
import logging
import zipfile
import io
import tempfile
from pathlib import Path

import httpx

from database import insert_workflow, insert_workflows_batch, add_github_repo, update_repo_sync, get_db

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Node type -> category mapping
NODE_CATEGORIES = {
    "n8n-nodes-base.slack": "Комунікація",
    "n8n-nodes-base.discord": "Комунікація",
    "n8n-nodes-base.telegram": "Комунікація",
    "n8n-nodes-base.telegramTrigger": "Комунікація",
    "n8n-nodes-base.mattermost": "Комунікація",
    "n8n-nodes-base.microsoftTeams": "Комунікація",
    "n8n-nodes-base.emailSend": "Email",
    "n8n-nodes-base.gmail": "Email",
    "n8n-nodes-base.microsoftOutlook": "Email",
    "n8n-nodes-base.googleSheets": "Таблиці",
    "n8n-nodes-base.spreadsheetFile": "Таблиці",
    "n8n-nodes-base.airtable": "Таблиці",
    "n8n-nodes-base.notion": "Продуктивність",
    "n8n-nodes-base.trello": "Продуктивність",
    "n8n-nodes-base.asana": "Продуктивність",
    "n8n-nodes-base.clickUp": "Продуктивність",
    "n8n-nodes-base.todoist": "Продуктивність",
    "n8n-nodes-base.openAi": "AI / LLM",
    "@n8n/n8n-nodes-langchain.openAi": "AI / LLM",
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": "AI / LLM",
    "@n8n/n8n-nodes-langchain.lmChatAnthropic": "AI / LLM",
    "@n8n/n8n-nodes-langchain.lmChatGoogleGemini": "AI / LLM",
    "@n8n/n8n-nodes-langchain.agent": "AI / LLM",
    "@n8n/n8n-nodes-langchain.chainLlm": "AI / LLM",
    "@n8n/n8n-nodes-langchain.vectorStoreQdrant": "AI / LLM",
    "@n8n/n8n-nodes-langchain.embeddingsOpenAi": "AI / LLM",
    "n8n-nodes-base.httpRequest": "HTTP / API",
    "n8n-nodes-base.webhook": "HTTP / API",
    "n8n-nodes-base.respondToWebhook": "HTTP / API",
    "n8n-nodes-base.postgres": "Бази даних",
    "n8n-nodes-base.mysql": "Бази даних",
    "n8n-nodes-base.mongoDb": "Бази даних",
    "n8n-nodes-base.redis": "Бази даних",
    "n8n-nodes-base.supabase": "Бази даних",
    "n8n-nodes-base.googleDrive": "Файли / Хмара",
    "n8n-nodes-base.dropbox": "Файли / Хмара",
    "n8n-nodes-base.s3": "Файли / Хмара",
    "n8n-nodes-base.ftp": "Файли / Хмара",
    "n8n-nodes-base.github": "DevOps",
    "n8n-nodes-base.gitlab": "DevOps",
    "n8n-nodes-base.jira": "DevOps",
    "n8n-nodes-base.hubspot": "CRM / Маркетинг",
    "n8n-nodes-base.salesforce": "CRM / Маркетинг",
    "n8n-nodes-base.pipedrive": "CRM / Маркетинг",
    "n8n-nodes-base.mailchimp": "CRM / Маркетинг",
    "n8n-nodes-base.wordpress": "CMS / Контент",
    "n8n-nodes-base.rss": "CMS / Контент",
    "n8n-nodes-base.rssFeedRead": "CMS / Контент",
    "n8n-nodes-base.twitter": "Соцмережі",
    "n8n-nodes-base.facebook": "Соцмережі",
    "n8n-nodes-base.instagram": "Соцмережі",
    "n8n-nodes-base.linkedIn": "Соцмережі",
    "n8n-nodes-base.cron": "Планувальник",
    "n8n-nodes-base.scheduleTrigger": "Планувальник",
}

TRIGGER_NODES = {
    "n8n-nodes-base.webhook": "Webhook",
    "n8n-nodes-base.manualTrigger": "Manual",
    "n8n-nodes-base.cron": "Scheduled",
    "n8n-nodes-base.scheduleTrigger": "Scheduled",
    "n8n-nodes-base.telegramTrigger": "Telegram",
    "n8n-nodes-base.emailTrigger": "Email",
    "n8n-nodes-base.formTrigger": "Form",
    "@n8n/n8n-nodes-langchain.chatTrigger": "Chat",
}


def _github_headers():
    """Build GitHub API headers with optional token."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


def parse_workflow_json(json_str: str) -> dict:
    """Parse n8n workflow JSON and extract metadata."""
    if not json_str or len(json_str) < 50:
        raise ValueError("Файл занадто малий для воркфлоу n8n")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        raise ValueError("Невалідний JSON")

    # Handle both direct workflow and wrapped format
    if isinstance(data, list):
        data = data[0] if (data and isinstance(data[0], dict)) else {}

    if not isinstance(data, dict):
        raise ValueError("Воркфлоу має бути об'єктом (JSON Object)")

    nodes_list = data.get("nodes", [])
    if not isinstance(nodes_list, list) or not nodes_list:
        raise ValueError("Воркфлоу не містить нод (поле 'nodes' порожнє або відсутнє)")

    name = data.get("name", "Без назви")

    # Extract node types
    node_types = set()
    for node in nodes_list:
        ntype = node.get("type", "")
        if ntype:
            short = ntype.replace("n8n-nodes-base.", "").replace("@n8n/n8n-nodes-langchain.", "")
            node_types.add(short)

    # Extract categories based on node types
    categories = set()
    for node in nodes_list:
        ntype = node.get("type", "")
        cat = NODE_CATEGORIES.get(ntype)
        if cat:
            categories.add(cat)
        if "langchain" in ntype.lower() or "openai" in ntype.lower():
            categories.add("AI / LLM")

    if not categories:
        categories.add("Інше")

    # Detect trigger type
    trigger_type = "Complex"
    for node in nodes_list:
        ntype = node.get("type", "")
        if ntype in TRIGGER_NODES:
            trigger_type = TRIGGER_NODES[ntype]
            break

    # Build description
    description = data.get("description", "") or ""
    if not description:
        node_names = [n.get("name", "") for n in nodes_list if n.get("name")]
        if node_names:
            description = "Ноди: " + ", ".join(node_names[:10])
            if len(node_names) > 10:
                description += f" (+{len(node_names) - 10})"

    json_hash = hashlib.sha256(json_str.encode()).hexdigest()[:16]

    return {
        "name": name,
        "description": description,
        "nodes": sorted(node_types),
        "categories": sorted(categories),
        "node_count": len(nodes_list),
        "trigger_type": trigger_type,
        "json_content": json_str,
        "json_hash": json_hash,
    }


async def import_from_json(json_str: str, source_url: str = "", source_repo: str = "", analyze: bool = False) -> dict:
    """Import a single workflow from raw JSON."""
    parsed = parse_workflow_json(json_str)
    wf_id = insert_workflow(
        name=parsed["name"],
        description=parsed["description"],
        nodes=parsed["nodes"],
        categories=parsed["categories"],
        node_count=parsed["node_count"],
        trigger_type=parsed["trigger_type"],
        source_url=source_url,
        source_repo=source_repo,
        json_content=parsed["json_content"],
        json_hash=parsed["json_hash"],
    )
    if wf_id:
        if analyze:
            try:
                from analyzer import analyze_and_save
                await analyze_and_save(wf_id)
            except Exception as e:
                logger.error(f"AI analysis failed for imported workflow {wf_id}: {e}")
        
        return {"status": "ok", "id": wf_id, "name": parsed["name"]}
    else:
        return {"status": "duplicate", "name": parsed["name"]}


async def import_from_directory(dir_path: str, source_repo: str = "", analyze: bool = False) -> dict:
    """Import all JSON workflow files from a local directory (batch mode)."""
    p = Path(dir_path)
    if not p.is_dir():
        return {"status": "error", "message": f"Папку не знайдено: {dir_path}"}

    json_files = sorted(p.glob("*.json"))
    if not json_files:
        return {"status": "error", "message": "JSON файлів не знайдено"}

    logger.info(f"Found {len(json_files)} JSON files in {dir_path}")

    # Parse all files first, then batch insert
    batch = []
    errors = 0
    for f in json_files:
        try:
            content = f.read_text(encoding="utf-8")
            parsed = parse_workflow_json(content)
            parsed["source_url"] = f"file://{f.name}"
            parsed["source_repo"] = source_repo
            batch.append(parsed)
        except Exception as e:
            logger.warning(f"Error parsing {f.name}: {e}")
            errors += 1

        if len(batch) % 500 == 0 and len(batch) > 0:
            logger.info(f"Parsed {len(batch) + errors}/{len(json_files)} files...")

    logger.info(f"Parsed {len(batch)} workflows, {errors} errors. Inserting into DB...")

    imported, duplicates = insert_workflows_batch(batch)

    # Trigger AI analysis for new ones if requested
    if analyze and imported > 0:
        logger.info(f"Triggering AI analysis for {imported} imported workflows...")
        from database import get_db
        conn = get_db()
        # Find just imported IDs based on their hashes
        hashes = [wf["json_hash"] for wf in batch]
        placeholders = ",".join(["?"] * len(hashes))
        rows = conn.execute(f"SELECT id FROM workflows WHERE json_hash IN ({placeholders})", hashes).fetchall()
        for row in rows:
            try:
                from analyzer import analyze_and_save
                await analyze_and_save(row["id"])
                await asyncio.sleep(1.0) # Rate limiting for Gemini free tier
            except Exception as e:
                logger.error(f"AI batch analysis error for {row['id']}: {e}")

    logger.info(f"Import complete: {imported} new, {duplicates} duplicates, {errors} errors")

    return {
        "status": "ok",
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total_files": len(json_files),
    }


async def import_from_url(url: str, analyze: bool = False) -> dict:
    """Import workflow(s) from a URL - GitHub file, GitHub repo dir, or n8n.io."""
    url = url.strip()

    # GitHub raw file
    if "raw.githubusercontent.com" in url and url.endswith(".json"):
        return await _import_github_raw(url, analyze=analyze)

    # GitHub blob/file URL
    if "github.com" in url and "/blob/" in url and url.endswith(".json"):
        raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        return await _import_github_raw(raw_url, analyze=analyze)

    # GitHub repo or directory
    if "github.com" in url and "/tree/" in url:
        return await _import_github_dir(url, analyze=analyze)

    # GitHub repo root (no /tree/)
    if re.match(r"https?://github\.com/[\w.\-]+/[\w.\-]+/?$", url):
        return await _import_github_dir(url, analyze=analyze)

    # n8n.io workflow URL
    if "n8n.io/workflows/" in url:
        return await _import_n8n_io(url, analyze=analyze)

    # Google Drive URL
    if "drive.google.com" in url:
        return await _import_google_drive(url, analyze=analyze)

    return {"status": "error", "message": "Непідтримуваний формат URL"}


async def _import_github_raw(raw_url: str, analyze: bool = False) -> dict:
    """Import a single JSON file from GitHub raw URL."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(raw_url, headers=_github_headers())
        if resp.status_code != 200:
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        return await import_from_json(resp.text, source_url=raw_url, analyze=analyze)


async def _get_default_branch(client: httpx.AsyncClient, owner: str, repo: str) -> str:
    """Discover the default branch of a GitHub repo."""
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=_github_headers()
        )
        if resp.status_code == 200:
            return resp.json().get("default_branch", "main")
    except Exception:
        pass
    return "main"


async def _import_github_dir(url: str, analyze: bool = False) -> dict:
    """Import all JSON files from a GitHub repo by downloading ZIP archive.
    This avoids git/trees truncation and Contents API limits for large repos.
    """
    match = re.match(r"https?://github\.com/([\w.\-]+)/([\w.\-]+)(?:/tree/([^?#]+))?", url)
    if not match:
        return {"status": "error", "message": "Невірний GitHub URL"}

    owner, repo_name, tree_part = match.groups()
    repo_url = f"https://github.com/{owner}/{repo_name}"

    # Determine branch and path filter
    async with httpx.AsyncClient(timeout=60) as client:
        if tree_part:
            parts = tree_part.split("/")
            branch = parts[0]
            path_filter = "/".join(parts[1:]) if len(parts) > 1 else ""
        else:
            branch = await _get_default_branch(client, owner, repo_name)
            path_filter = ""

    # Download ZIP archive (single request, no truncation)
    zip_url = f"https://github.com/{owner}/{repo_name}/archive/refs/heads/{branch}.zip"
    logger.info(f"Downloading ZIP archive from {zip_url}...")

    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        resp = await client.get(zip_url)
        if resp.status_code != 200:
            return {"status": "error", "message": f"ZIP download failed: HTTP {resp.status_code}"}

    logger.info(f"ZIP downloaded: {len(resp.content) / 1024 / 1024:.1f} MB. Extracting JSON files...")

    # Extract JSON files from ZIP
    imported = 0
    duplicates = 0
    errors = 0
    batch = []
    BATCH_SIZE = 500
    total_json = 0

    # ZIP root folder is typically "repo_name-branch/"
    zip_prefix = f"{repo_name}-{branch}/"
    target_prefix = zip_prefix + (path_filter + "/" if path_filter else "")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        json_names = [n for n in zf.namelist() if n.endswith(".json") and n.startswith(target_prefix)]
        total_json = len(json_names)
        logger.info(f"Found {total_json} JSON files in ZIP archive")

        for i, name in enumerate(json_names):
            try:
                content = zf.read(name).decode("utf-8")
                parsed = parse_workflow_json(content)
                # Build a raw URL for reference
                rel_path = name[len(zip_prefix):]
                parsed["source_url"] = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}/{rel_path}"
                parsed["source_repo"] = repo_url
                batch.append(parsed)
            except Exception as e:
                logger.warning(f"Error parsing {name}: {e}")
                errors += 1

            if len(batch) >= BATCH_SIZE:
                new, dups = insert_workflows_batch(batch)
                imported += new
                duplicates += dups
                batch = []
                logger.info(f"Import progress: {i + 1}/{total_json} "
                            f"(+{imported} new, {duplicates} dup, {errors} err)")

    if batch:
        new, dups = insert_workflows_batch(batch)
        imported += new
        duplicates += dups
    
    # Trigger AI analysis for the whole repo if requested
    if analyze and imported > 0:
        logger.info(f"Triggering AI analysis for {imported} imported GitHub workflows...")
        from database import get_db
        from analyzer import analyze_and_save
        conn = get_db()
        # Find imported IDs from this repo
        rows = conn.execute("SELECT id FROM workflows WHERE source_repo = ? AND ai_analyzed_at = ''", (repo_url,)).fetchall()
        for row in rows:
            try:
                await analyze_and_save(row["id"])
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"AI batch analysis error: {e}")

    logger.info(f"GitHub import complete: {imported} new, {duplicates} dup, {errors} err out of {total_json}")

    # Register repo for sync
    add_github_repo(repo_url)
    update_repo_sync(repo_url, imported)

    return {
        "status": "ok",
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total_files": total_json,
    }


async def _import_n8n_io(url: str, analyze: bool = False) -> dict:
    """Import from n8n.io/workflows/ URL."""
    match = re.search(r"/workflows/(\d+)", url)
    if not match:
        return {"status": "error", "message": "Не вдалося визначити ID воркфлоу"}

    wf_id = match.group(1)
    api_url = f"https://api.n8n.io/api/workflows/templates/{wf_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return {"status": "error", "message": f"n8n.io API: {resp.status_code}"}

        data = resp.json()
        workflow = data.get("workflow", data)
        json_str = json.dumps(workflow, ensure_ascii=False)
        return await import_from_json(json_str, source_url=url, analyze=analyze)


async def _import_google_drive(url: str, analyze: bool = False) -> dict:
    """Import from a Google Drive shared file link."""
    # Extract file ID
    file_id = ""
    is_folder = False

    if "/file/d/" in url:
        parts = url.split("/file/d/")
        if len(parts) > 1:
            file_id = parts[1].split("/")[0].split("?")[0]
    elif "/folders/" in url:
        is_folder = True
        parts = url.split("/folders/")
        if len(parts) > 1:
            file_id = parts[1].split("/")[0].split("?")[0]
    elif "id=" in url:
        parts = url.split("id=")
        if len(parts) > 1:
            file_id = parts[1].split("&")[0]

    if is_folder:
        return {
            "status": "error", 
            "message": "Ви вставили посилання на ПАПКУ Google Drive. Наразі підтримуються лише посилання на ОКРЕМІ файли воркфлоу (.json). "
                       "Щоб завантажити багато файлів одночасно, скористайтеся вкладкою «Файл» (Drag-and-Drop) або GitHub репозиторієм."
        }

    if not file_id:
        return {"status": "error", "message": "Не вдалося визначити ID файлу Google Drive. Переконайтеся, що це пряме посилання на JSON-файл."}

    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    logger.info(f"Downloading from Google Drive: {download_url}")

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(download_url)
        if resp.status_code != 200:
            if "virus" in resp.text.lower():
                return {"status": "error", "message": "Файл занадто великий для Google Drive scan, або потребує підтвердження. Спробуйте інший метод."}
            return {"status": "error", "message": f"Google Drive error: HTTP {resp.status_code}"}
        
        try:
            return await import_from_json(resp.text, source_url=url, analyze=analyze)
        except Exception as e:
            return {"status": "error", "message": f"Помилка парсингу Google Drive файлу: {str(e)}"}


async def sync_github_repo(repo_url: str) -> dict:
    """Re-sync a GitHub repo (auto-detect default branch)."""
    match = re.match(r"https?://github\.com/([\w.\-]+)/([\w.\-]+)", repo_url)
    if not match:
        return {"status": "error", "message": "Невірний URL"}

    owner, repo_name = match.groups()

    async with httpx.AsyncClient(timeout=30) as client:
        branch = await _get_default_branch(client, owner, repo_name)

    url = f"https://github.com/{owner}/{repo_name}/tree/{branch}"
    return await _import_github_dir(url)


async def sync_all_repos():
    """Sync all registered GitHub repos."""
    conn = get_db()
    rows = conn.execute("SELECT repo_url FROM github_repos WHERE enabled = 1").fetchall()

    results = []
    for row in rows:
        try:
            result = await sync_github_repo(row["repo_url"])
            results.append({"repo": row["repo_url"], **result})
        except Exception as e:
            logger.error(f"Sync failed for {row['repo_url']}: {e}")
            results.append({"repo": row["repo_url"], "status": "error", "message": str(e)})
    return results
