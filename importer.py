import json
import hashlib
import os
import re
import asyncio
import logging
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
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        raise ValueError("Невалідний JSON")

    # Handle both direct workflow and wrapped format
    if isinstance(data, list):
        data = data[0] if data else {}

    nodes_list = data.get("nodes", [])
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


async def import_from_json(json_str: str, source_url: str = "", source_repo: str = "") -> dict:
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
        return {"status": "ok", "id": wf_id, "name": parsed["name"]}
    else:
        return {"status": "duplicate", "name": parsed["name"]}


async def import_from_directory(dir_path: str, source_repo: str = "") -> dict:
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

    logger.info(f"Import complete: {imported} new, {duplicates} duplicates, {errors} errors")

    return {
        "status": "ok",
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total_files": len(json_files),
    }


async def import_from_url(url: str) -> dict:
    """Import workflow(s) from a URL - GitHub file, GitHub repo dir, or n8n.io."""
    url = url.strip()

    # GitHub raw file
    if "raw.githubusercontent.com" in url and url.endswith(".json"):
        return await _import_github_raw(url)

    # GitHub blob/file URL
    if "github.com" in url and "/blob/" in url and url.endswith(".json"):
        raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        return await _import_github_raw(raw_url)

    # GitHub repo or directory
    if "github.com" in url and "/tree/" in url:
        return await _import_github_dir(url)

    # GitHub repo root (no /tree/)
    if re.match(r"https?://github\.com/[\w.\-]+/[\w.\-]+/?$", url):
        return await _import_github_dir(url)

    # n8n.io workflow URL
    if "n8n.io/workflows/" in url:
        return await _import_n8n_io(url)

    return {"status": "error", "message": "Непідтримуваний формат URL"}


async def _import_github_raw(raw_url: str) -> dict:
    """Import a single JSON file from GitHub raw URL."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(raw_url, headers=_github_headers())
        if resp.status_code != 200:
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        return await import_from_json(resp.text, source_url=raw_url)


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


async def _import_github_dir(url: str) -> dict:
    """Import all JSON files from a GitHub directory using API."""
    # Parse: github.com/owner/repo/tree/branch/path
    match = re.match(r"https?://github\.com/([\w.\-]+)/([\w.\-]+)(?:/tree/([^?#]+))?", url)
    if not match:
        return {"status": "error", "message": "Невірний GitHub URL"}

    owner, repo_name, tree_part = match.groups()
    repo_url = f"https://github.com/{owner}/{repo_name}"

    # Get tree listing with a short-lived client
    async with httpx.AsyncClient(timeout=60) as client:
        if tree_part:
            parts = tree_part.split("/")
            branch = parts[0]
            path = "/".join(parts[1:]) if len(parts) > 1 else ""
        else:
            branch = await _get_default_branch(client, owner, repo_name)
            path = ""

        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{branch}?recursive=1"
        resp = await client.get(api_url, headers=_github_headers())
        if resp.status_code != 200:
            return {"status": "error", "message": f"GitHub API: {resp.status_code}"}

        tree = resp.json().get("tree", [])

    json_files = []
    for item in tree:
        if item["type"] == "blob" and item["path"].endswith(".json"):
            if path:
                if item["path"].startswith(path + "/") or item["path"] == path:
                    json_files.append(item["path"])
            else:
                if "/workflows/" in item["path"] or item["path"].startswith("workflows/"):
                    json_files.append(item["path"])
                elif item["path"].count("/") <= 1:
                    json_files.append(item["path"])

    if not json_files:
        json_files = [i["path"] for i in tree if i["type"] == "blob" and i["path"].endswith(".json")]

    logger.info(f"Found {len(json_files)} JSON files to import from {owner}/{repo_name}")

    imported = 0
    duplicates = 0
    errors = 0
    batch = []
    BATCH_SIZE = 100

    # Process files in chunks with fresh connections
    for i, fpath in enumerate(json_files):
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{branch}/{fpath}"

        # Retry up to 3 times
        content = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(raw_url, headers=_github_headers())

                if resp.status_code == 403:
                    logger.warning("GitHub rate limit hit, waiting 60s...")
                    await asyncio.sleep(60)
                    continue

                if resp.status_code == 200:
                    content = resp.text
                    break
                else:
                    logger.warning(f"HTTP {resp.status_code} for {fpath}")
                    break
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/3 failed for {fpath}: {e}")
                await asyncio.sleep(2)

        if content:
            try:
                parsed = parse_workflow_json(content)
                parsed["source_url"] = raw_url
                parsed["source_repo"] = repo_url
                batch.append(parsed)
            except Exception as e:
                logger.warning(f"Parse error {fpath}: {e}")
                errors += 1
        else:
            errors += 1

        # Flush batch to DB
        if len(batch) >= BATCH_SIZE:
            new, dups = insert_workflows_batch(batch)
            imported += new
            duplicates += dups
            batch = []
            logger.info(f"GitHub import progress: {i + 1}/{len(json_files)} "
                        f"(+{imported} new, {duplicates} dup, {errors} err)")

        # Small delay every 10 requests
        if (i + 1) % 10 == 0:
            await asyncio.sleep(0.1)

    # Flush remaining
    if batch:
        new, dups = insert_workflows_batch(batch)
        imported += new
        duplicates += dups

    logger.info(f"GitHub import complete: {imported} new, {duplicates} dup, {errors} err out of {len(json_files)}")

    # Register repo for sync
    add_github_repo(repo_url)
    update_repo_sync(repo_url, imported)

    return {
        "status": "ok",
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors,
        "total_files": len(json_files),
    }


async def _import_n8n_io(url: str) -> dict:
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
        return await import_from_json(json_str, source_url=url)


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
