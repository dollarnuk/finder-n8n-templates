"""
AI Chat Search (Gemini) — перетворює запити природною мовою у параметри фільтрації.
Використовує Gemini для побудови FTS5 запиту та вибору категорій/нод.
"""

import os
import json
import asyncio
import logging
import google.generativeai as genai

from database import get_all_nodes, get_all_categories, search_workflows

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "models/gemini-flash-latest")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY, transport="rest")

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
}}

Приклад:
User: "хочу автоматизувати пости в телеграм з гугл таблиць"
Result: {{
  "fts_query": "telegram google sheets",
  "category": "Social Media",
  "node": "n8n-nodes-base.googleSheets",
  "explanation": "Шукаю воркфлоу для інтеграції Telegram та Google Sheets."
}}"""

async def translate_query(user_query: str) -> dict:
    """Translate natural language query to search parameters."""
    if not GEMINI_API_KEY:
        return {
            "fts_query": user_query,
            "category": "",
            "node": "",
            "explanation": "AI-пошук не налаштовано. Використовую звичайний пошук."
        }

    try:
        # Get context
        logger.info("Retrieving categories and nodes...")
        categories = get_all_categories()
        nodes = get_all_nodes()
        logger.info(f"Context retrieved: {len(categories)} categories, {len(nodes)} nodes.")
        
        # Limit nodes to most common ones to avoid prompt overflow
        # For now just use first 100 or specific relevant ones if we had stats
        nodes_list = nodes[:20] 
        cats_list = categories

        model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=SEARCH_SYSTEM_PROMPT.format(
                categories=", ".join(cats_list),
                nodes=", ".join(nodes_list)
            )
        )

        logger.info(f"Sending AI Search request to {GEMINI_MODEL}...")
        # Using to_thread for the sync call to avoid await expression issues with some SDK versions/transports
        response = await asyncio.to_thread(
            model.generate_content,
            user_query,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                response_mime_type="application/json",
            )
        )
        logger.info(f"AI Search response received.")

        result = json.loads(response.text)
        return result

    except Exception as e:
        logger.error(f"AI Chat Search error: {e}")
        return {
            "fts_query": user_query,
            "category": "",
            "node": "",
            "explanation": f"Помилка AI: {str(e)}. Використовую звичайний пошук."
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
