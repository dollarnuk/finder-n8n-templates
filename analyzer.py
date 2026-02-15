"""
AI Workflow Analyzer (OpenAI) — аналізує n8n воркфлоу через OpenAI API.
Оцінює: корисність, універсальність, складність, масштабність.
Генерує: короткий опис українською + теги для пошуку.
"""

import os
import json
import asyncio
import logging
from openai import OpenAI

from database import update_workflow_ai, get_unanalyzed_workflows, get_workflow

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

try:
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    client = None

# Global status for tracking progress
analysis_status = {
    "status": "idle",  # idle, running
    "total": 0,
    "analyzed": 0,
    "errors": 0,
    "start_time": None
}

ANALYSIS_PROMPT = """Ти — експерт з n8n автоматизацій. Проаналізуй цей workflow та дай структуровану відповідь у JSON ДВОМА МОВАМИ (українською та англійською).

Workflow:
- Назва: {name}
- Опис: {description}
- Ноди ({node_count}): {nodes}
- Категорії: {categories}
- Тип тригера: {trigger_type}

Оціни від 1 до 10:
1. usefulness — наскільки корисний для бізнесу
2. universality — наскільки універсальний
3. complexity — складність налаштування
4. scalability — масштабність

Також надай наступні поля ДВОМА МОВАМИ:
5. suggested_name — краща назва для воркфлоу, якщо поточна "{name}" є невідповідною.
6. summary_uk / summary_en — короткий опис (2-3 речення).
7. tags — 3-5 тегів (англійською).
8. use_cases_uk / use_cases_en — список з 2-3 конкретних бізнес-сценаріїв.
9. target_audience_uk / target_audience_en — основна цільова аудиторія.
10. integrations_summary_uk / integrations_summary_en — людяний опис сервісів, що з'єднуються.
11. difficulty_level — рівень складності (beginner, intermediate, advanced).

Відповідь має бути СУВОРО у форматі JSON:
{{
  "usefulness": N,
  "universality": N,
  "complexity": N,
  "scalability": N,
  "suggested_name": "...",
  "difficulty_level": "...",
  "tags": ["tag1", "tag2"],
  "uk": {{
    "summary": "...",
    "use_cases": ["...", "..."],
    "target_audience": "...",
    "integrations_summary": "..."
  }},
  "en": {{
    "summary": "...",
    "use_cases": ["...", "..."],
    "target_audience": "...",
    "integrations_summary": "..."
  }}
}}"""


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
    """Analyze a single workflow using OpenAI API.
    Returns dict with scores, summary and tags, or None on error.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set")
        return None
    
    if not client:
        logger.error("OpenAI client not initialized")
        return None

    try:
        prompt = _build_prompt(wf)
        
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Ensure all required keys exist with defaults
        for key in ["usefulness", "universality", "complexity", "scalability"]:
            if key not in result:
                result[key] = 5

        result.setdefault("uk", {})
        result.setdefault("en", {})
        result.setdefault("tags", [])
        result.setdefault("difficulty_level", "intermediate")
        result.setdefault("suggested_name", wf.get("name", ""))

        # Ensure nested structures exist
        for lang in ("uk", "en"):
            result[lang].setdefault("summary", "")
            result[lang].setdefault("use_cases", [])
            result[lang].setdefault("target_audience", "")
            result[lang].setdefault("integrations_summary", "")

        if isinstance(result["tags"], str):
            result["tags"] = [t.strip() for t in result["tags"].split(",")]

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from OpenAI for workflow {wf.get('id')}: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenAI analysis error for workflow {wf.get('id')}: {e}")
        return None


async def analyze_and_save(wf_id: int) -> dict:
    """Analyze a single workflow by ID and save results to DB."""
    wf = get_workflow(wf_id)
    if not wf:
        return {"error": "Workflow not found"}

    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not configured"}

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
        usefulness=result.get("usefulness", 5),
        universality=result.get("universality", 5),
        complexity=result.get("complexity", 5),
        scalability=result.get("scalability", 5),
        summary=result.get("uk", {}).get("summary", ""),
        tags=result.get("tags", []),
        use_cases=result.get("uk", {}).get("use_cases", []),
        target_audience=result.get("uk", {}).get("target_audience", ""),
        integrations_summary=result.get("uk", {}).get("integrations_summary", ""),
        difficulty_level=result.get("difficulty_level", "intermediate"),
        result_en=result.get("en", {})
    )

    # Update name if suggested and current name is generic
    suggested_name = result.get("suggested_name")
    current_name = wf.get("name", "")
    generic_names = ["Без назви", "My workflow", "Untitled", "New workflow", "workflow", ""]
    
    if suggested_name and suggested_name != current_name:
        is_generic = current_name in generic_names or not current_name
        if is_generic:
            try:
                from database import get_db
                conn = get_db()
                conn.execute("UPDATE workflows SET name = ? WHERE id = ?", (suggested_name, wf_id))
                conn.commit()
                logger.info(f"Renamed workflow {wf_id}: '{current_name}' -> '{suggested_name}'")
            except Exception as e:
                logger.error(f"Failed to rename workflow {wf_id}: {e}")

    return {
        "status": "ok",
        "workflow_id": wf_id,
        "scores": result,
    }


async def analyze_batch(limit: int = 50) -> dict:
    """Analyze a batch of unanalyzed workflows.
    Returns summary of results including error details.
    """
    global analysis_status
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not configured"}

    workflows = get_unanalyzed_workflows(limit)
    if not workflows:
        analysis_status["status"] = "idle"
        return {"status": "ok", "message": "All workflows already analyzed", "analyzed": 0}

    from datetime import datetime
    analysis_status.update({
        "status": "running",
        "total": len(workflows),
        "analyzed": 0,
        "errors": 0,
        "start_time": datetime.utcnow().isoformat()
    })

    analyzed = 0
    errors = 0
    error_details = []

    try:
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
                    usefulness=result.get("usefulness", 5),
                    universality=result.get("universality", 5),
                    complexity=result.get("complexity", 5),
                    scalability=result.get("scalability", 5),
                    summary=result.get("uk", {}).get("summary", ""),
                    tags=result.get("tags", []),
                    use_cases=result.get("uk", {}).get("use_cases", []),
                    target_audience=result.get("uk", {}).get("target_audience", ""),
                    integrations_summary=result.get("uk", {}).get("integrations_summary", ""),
                    difficulty_level=result.get("difficulty_level", "intermediate"),
                    result_en=result.get("en", {})
                )
                analyzed += 1
                analysis_status["analyzed"] = analyzed
                logger.info(f"Analyzed {analyzed}/{len(workflows)}: {wf['name'][:50]} → usefulness={result['usefulness']}")
            else:
                # Retry once after a longer pause (likely rate limit)
                logger.warning(f"First attempt failed for {wf['id']}: {wf['name'][:50]}, retrying in 10s...")
                await asyncio.sleep(10.0)
                result = await analyze_workflow(wf_data)
                if result:
                    update_workflow_ai(
                        wf["id"],
                        usefulness=result.get("usefulness", 5),
                        universality=result.get("universality", 5),
                        complexity=result.get("complexity", 5),
                        scalability=result.get("scalability", 5),
                        summary=result.get("uk", {}).get("summary", ""),
                        tags=result.get("tags", []),
                        use_cases=result.get("uk", {}).get("use_cases", []),
                        target_audience=result.get("uk", {}).get("target_audience", ""),
                        integrations_summary=result.get("uk", {}).get("integrations_summary", ""),
                        difficulty_level=result.get("difficulty_level", "intermediate"),
                        result_en=result.get("en", {})
                    )
                    analyzed += 1
                    analysis_status["analyzed"] = analyzed
                    logger.info(f"Retry OK {analyzed}/{len(workflows)}: {wf['name'][:50]} → usefulness={result['usefulness']}")
                else:
                    errors += 1
                    analysis_status["errors"] = errors
                    error_details.append({"id": wf["id"], "name": wf["name"][:60]})
                    logger.warning(f"Failed to analyze workflow {wf['id']}: {wf['name'][:50]}")

            # Rate limiting: OpenAI gpt-4o-mini usually has higher limits.
            # Still a small pause is good for stability.
            await asyncio.sleep(0.5)
    finally:
        analysis_status["status"] = "idle"

    return {
        "status": "ok",
        "analyzed": analyzed,
        "errors": errors,
        "remaining": len(get_unanalyzed_workflows(1)),
        "error_details": error_details,
    }
