"""
AI Workflow Analyzer (Gemini) — аналізує n8n воркфлоу через Google Gemini API.
Оцінює: корисність, універсальність, складність, масштабність.
Генерує: короткий опис українською + теги для пошуку.
"""

import os
import json
import asyncio
import logging
import google.generativeai as genai

from database import update_workflow_ai, get_unanalyzed_workflows, get_workflow

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "models/gemini-flash-latest")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY, transport="rest")

ANALYSIS_PROMPT = """Ти — експерт з n8n автоматизацій. Проаналізуй цей workflow та дай структуровану відповідь у JSON.

Workflow:
- Назва: {name}
- Опис: {description}
- Ноди ({node_count}): {nodes}
- Категорії: {categories}
- Тип тригера: {trigger_type}

Оціни від 1 до 10:
1. usefulness — наскільки корисний для бізнесу (1=тестовий/демо, 10=критичний бізнес-процес)
2. universality — наскільки універсальний (1=вузькоспеціалізований, 10=підходить будь-якому бізнесу)
3. complexity — складність налаштування (1=plug-and-play, 10=потрібен досвідчений розробник)
4. scalability — масштабність (1=для одного юзера, 10=enterprise-рівень)

Також:
5. summary — короткий опис (2-3 речення українською), що робить цей workflow і кому він корисний
6. tags — 3-5 тегів для пошуку (англійською, малі літери, одне-два слова)

Відповідь ТІЛЬКИ валідний JSON:
{{"usefulness": N, "universality": N, "complexity": N, "scalability": N, "summary": "...", "tags": ["tag1", "tag2"]}}"""


def _build_prompt(wf: dict) -> str:
    """Build analysis prompt from workflow data."""
    nodes_str = ", ".join(wf.get("nodes", [])[:30])  # Limit to 30 nodes
    cats_str = ", ".join(wf.get("categories", []))
    return ANALYSIS_PROMPT.format(
        name=wf.get("name", "Без назви"),
        description=(wf.get("description", "") or "")[:500],
        node_count=wf.get("node_count", 0),
        nodes=nodes_str,
        categories=cats_str or "не визначено",
        trigger_type=wf.get("trigger_type", "невідомий"),
    )


async def analyze_workflow(wf: dict) -> dict:
    """Analyze a single workflow using Gemini API.
    Returns dict with scores, summary and tags, or None on error.
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not set")
        return None

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = _build_prompt(wf)
        
        # Using to_thread for the sync call to avoid await expression issues
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                temperature=0.3,
                response_mime_type="application/json",
            )
        )
        
        raw = response.text.strip()
        result = json.loads(raw)

        # Validate and clamp scores
        for key in ("usefulness", "universality", "complexity", "scalability"):
            try:
                val = result.get(key, 5)
                result[key] = max(1, min(10, int(val)))
            except:
                result[key] = 5

        result.setdefault("summary", "")
        result.setdefault("tags", [])
        if isinstance(result["tags"], str):
            result["tags"] = [t.strip() for t in result["tags"].split(",")]

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from Gemini for workflow {wf.get('id')}: {e}")
        return None
    except Exception as e:
        logger.error(f"Gemini analysis error for workflow {wf.get('id')}: {e}")
        return None


async def analyze_and_save(wf_id: int) -> dict:
    """Analyze a single workflow by ID and save results to DB."""
    wf = get_workflow(wf_id)
    if not wf:
        return {"error": "Workflow not found"}

    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not configured"}

    # Parse nodes/categories from JSON strings
    wf_data = {
        "id": wf["id"],
        "name": wf["name"],
        "description": wf["description"],
        "nodes": json.loads(wf["nodes"]) if isinstance(wf["nodes"], str) else wf["nodes"],
        "categories": json.loads(wf["categories"]) if isinstance(wf["categories"], str) else wf["categories"],
        "node_count": wf["node_count"],
        "trigger_type": wf["trigger_type"],
    }

    result = await analyze_workflow(wf_data)
    if not result:
        return {"error": "AI analysis failed"}

    update_workflow_ai(
        wf_id,
        usefulness=result["usefulness"],
        universality=result["universality"],
        complexity=result["complexity"],
        scalability=result["scalability"],
        summary=result["summary"],
        tags=result["tags"],
    )

    return {
        "status": "ok",
        "workflow_id": wf_id,
        "scores": result,
    }


async def analyze_batch(limit: int = 50) -> dict:
    """Analyze a batch of unanalyzed workflows.
    Returns summary of results.
    """
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not configured"}

    workflows = get_unanalyzed_workflows(limit)
    if not workflows:
        return {"status": "ok", "message": "All workflows already analyzed", "analyzed": 0}

    analyzed = 0
    errors = 0

    for wf in workflows:
        # Parse nodes/categories
        wf_data = {
            "id": wf["id"],
            "name": wf["name"],
            "description": wf["description"],
            "nodes": json.loads(wf["nodes"]) if isinstance(wf["nodes"], str) else wf["nodes"],
            "categories": json.loads(wf["categories"]) if isinstance(wf["categories"], str) else wf["categories"],
            "node_count": wf["node_count"],
            "trigger_type": wf["trigger_type"],
        }

        result = await analyze_workflow(wf_data)
        if result:
            update_workflow_ai(
                wf["id"],
                usefulness=result["usefulness"],
                universality=result["universality"],
                complexity=result["complexity"],
                scalability=result["scalability"],
                summary=result["summary"],
                tags=result["tags"],
            )
            analyzed += 1
            logger.info(f"Analyzed {analyzed}/{len(workflows)}: {wf['name'][:50]} → usefulness={result['usefulness']}")
        else:
            errors += 1

        # Rate limiting: Gemini 1.5 Flash has higher limits, but 1s pause is safe for free tier
        await asyncio.sleep(1.0)

    return {
        "status": "ok",
        "analyzed": analyzed,
        "errors": errors,
        "remaining": len(get_unanalyzed_workflows(1)),
    }
