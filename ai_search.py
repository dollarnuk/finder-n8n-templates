"""
AI Chat Search (OpenAI) — перетворює запити природною мовою у параметри фільтрації.
Використовує OpenAI для побудови FTS5 запиту та вибору категорій/нод.
"""

import os
import json
import asyncio
import logging
from openai import OpenAI

from database import get_all_nodes, get_all_categories, search_workflows

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

try:
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client for search: {e}")
    client = None

SEARCH_SYSTEM_PROMPT = """Ти — AI-помічник для пошуку n8n воркфлоу.
Твоє завдання: отримати запит користувача та перетворити його на параметри пошуку.

Доступні категорії: {categories}
Доступні типи нод: {nodes}

Результат має бути у JSON форматі:
{{
  "fts_query": "слова для повнотекстового пошуку через OR або AND",
  "category": "найбільш відповідна категорія (або пуста строка)",
  "node": "найбільш відповідна нода (або пуста строка)",
  "explanation": "коротке пояснення українською, що ти шукаєш"
}}"""

async def translate_query(user_query: str) -> dict:
    """Translate natural language query to search parameters."""
    if not OPENAI_API_KEY:
        return {
            "fts_query": user_query,
            "category": "",
            "node": "",
            "explanation": "AI-пошук не налаштовано. Використовую звичайний пошук."
        }
    
    if not client:
        return {
            "fts_query": user_query,
            "category": "",
            "node": "",
            "explanation": "OpenAI клієнт не ініціалізовано. Використовую звичайний пошук."
        }

    try:
        # Get context
        logger.info("Retrieving categories and nodes...")
        categories = get_all_categories()
        nodes = get_all_nodes()
        logger.info(f"Context retrieved: {len(categories)} categories, {len(nodes)} nodes.")
        
        # Limit nodes to most common ones
        nodes_list = nodes[:20] 
        cats_list = categories

        logger.info(f"Sending AI Search request to {OPENAI_MODEL}...")
        
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SEARCH_SYSTEM_PROMPT.format(
                    categories=", ".join(cats_list),
                    nodes=", ".join(nodes_list)
                )},
                {"role": "user", "content": user_query}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        
        result = json.loads(response.choices[0].message.content)
        return result

    except Exception as e:
        logger.error(f"AI Chat Search error: {e}")
        error_msg = str(e)
        
        return {
            "fts_query": user_query,
            "category": "",
            "node": "",
            "explanation": f"Помилка AI: {error_msg}. Використовую звичайний пошук."
        }

async def perform_ai_search(query: str, page: int = 1):
    """Perform full AI-assisted search."""
    # 1. Translate query via AI
    params = await translate_query(query)
    
    # 2. Perform actual search in DB
    search_results = search_workflows(
        query=params.get("fts_query", query),
        category=params.get("category", ""),
        node=params.get("node", ""),
        page=page,
        sort="usefulness"
    )
    
    # 3. Parse JSON strings in results for frontend
    if "workflows" in search_results:
        for wf in search_results["workflows"]:
            if isinstance(wf.get("nodes"), str):
                try: wf["nodes"] = json.loads(wf["nodes"])
                except: wf["nodes"] = []
            if isinstance(wf.get("categories"), str):
                try: wf["categories"] = json.loads(wf["categories"])
                except: wf["categories"] = []
    
    # 4. Combine
    return {
        "explanation": params.get("explanation", ""),
        "ai_params": params,
        "results": search_results
    }
