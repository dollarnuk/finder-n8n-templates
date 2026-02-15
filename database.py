import sqlite3
import json
import os
import threading
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "./workflows.db")

_local = threading.local()


def get_db():
    """Get a thread-local database connection (reused per thread)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return _local.conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            nodes TEXT DEFAULT '[]',
            categories TEXT DEFAULT '[]',
            node_count INTEGER DEFAULT 0,
            trigger_type TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            source_repo TEXT DEFAULT '',
            json_content TEXT NOT NULL,
            json_hash TEXT UNIQUE NOT NULL,
            added_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            ai_usefulness INTEGER DEFAULT 0,
            ai_universality INTEGER DEFAULT 0,
            ai_complexity INTEGER DEFAULT 0,
            ai_scalability INTEGER DEFAULT 0,
            ai_summary TEXT DEFAULT '',
            ai_tags TEXT DEFAULT '[]',
            ai_use_cases TEXT DEFAULT '[]',
            ai_target_audience TEXT DEFAULT '',
            ai_integrations_summary TEXT DEFAULT '',
            ai_difficulty_level TEXT DEFAULT '',
            ai_analyzed_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS github_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_url TEXT UNIQUE NOT NULL,
            last_synced TEXT,
            workflow_count INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS workflow_nodes (
            workflow_id INTEGER NOT NULL,
            node_name TEXT NOT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
            UNIQUE(workflow_id, node_name)
        );

        CREATE TABLE IF NOT EXISTS workflow_categories (
            workflow_id INTEGER NOT NULL,
            category_name TEXT NOT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
            UNIQUE(workflow_id, category_name)
        );

        CREATE INDEX IF NOT EXISTS idx_wn_name ON workflow_nodes(node_name);
        CREATE INDEX IF NOT EXISTS idx_wc_name ON workflow_categories(category_name);

        CREATE VIRTUAL TABLE IF NOT EXISTS workflows_fts USING fts5(
            name, description, nodes, categories, ai_summary, ai_tags, ai_use_cases, ai_target_audience, ai_integrations_summary,
            content='workflows',
            content_rowid='id',
            tokenize='unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS workflows_ai AFTER INSERT ON workflows BEGIN
            INSERT INTO workflows_fts(rowid, name, description, nodes, categories, ai_summary, ai_tags, ai_use_cases, ai_target_audience, ai_integrations_summary)
            VALUES (new.id, new.name, new.description, new.nodes, new.categories, new.ai_summary, new.ai_tags, new.ai_use_cases, new.ai_target_audience, new.ai_integrations_summary);
        END;

        CREATE TRIGGER IF NOT EXISTS workflows_ad AFTER DELETE ON workflows BEGIN
            INSERT INTO workflows_fts(workflows_fts, rowid, name, description, nodes, categories, ai_summary, ai_tags, ai_use_cases, ai_target_audience, ai_integrations_summary)
            VALUES ('delete', old.id, old.name, old.description, old.nodes, old.categories, old.ai_summary, old.ai_tags, old.ai_use_cases, old.ai_target_audience, old.ai_integrations_summary);
        END;

        CREATE TRIGGER IF NOT EXISTS workflows_au AFTER UPDATE ON workflows BEGIN
            INSERT INTO workflows_fts(workflows_fts, rowid, name, description, nodes, categories, ai_summary, ai_tags, ai_use_cases, ai_target_audience, ai_integrations_summary)
            VALUES ('delete', old.id, old.name, old.description, old.nodes, old.categories, old.ai_summary, old.ai_tags, old.ai_use_cases, old.ai_target_audience, old.ai_integrations_summary);
            INSERT INTO workflows_fts(rowid, name, description, nodes, categories, ai_summary, ai_tags, ai_use_cases, ai_target_audience, ai_integrations_summary)
            VALUES (new.id, new.name, new.description, new.nodes, new.categories, new.ai_summary, new.ai_tags, new.ai_use_cases, new.ai_target_audience, new.ai_integrations_summary);
        END;
    """)
    conn.commit()
    _migrate_ai_columns()
    _migrate_lookup_tables()


def _migrate_ai_columns():
    """Add AI analysis columns to existing workflows table if missing."""
    conn = get_db()
    cursor = conn.execute("PRAGMA table_info(workflows)")
    columns = {row[1] for row in cursor.fetchall()}
    ai_columns = {
        "ai_usefulness": "INTEGER DEFAULT 0",
        "ai_universality": "INTEGER DEFAULT 0",
        "ai_complexity": "INTEGER DEFAULT 0",
        "ai_scalability": "INTEGER DEFAULT 0",
        "ai_summary": "TEXT DEFAULT ''",
        "ai_tags": "TEXT DEFAULT '[]'",
        "ai_use_cases": "TEXT DEFAULT '[]'",
        "ai_target_audience": "TEXT DEFAULT ''",
        "ai_integrations_summary": "TEXT DEFAULT ''",
        "ai_difficulty_level": "TEXT DEFAULT ''",
        "ai_analyzed_at": "TEXT DEFAULT ''",
    }
    for col, col_type in ai_columns.items():
        if col not in columns:
            conn.execute(f"ALTER TABLE workflows ADD COLUMN {col} {col_type}")
    conn.commit()


def _migrate_lookup_tables():
    """Populate lookup tables from existing workflow data if empty."""
    conn = get_db()
    node_count = conn.execute("SELECT COUNT(*) FROM workflow_nodes").fetchone()[0]
    if node_count > 0:
        return
    wf_count = conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
    if wf_count == 0:
        return
    rows = conn.execute("SELECT id, nodes, categories FROM workflows").fetchall()
    for r in rows:
        wf_id = r["id"]
        for node in json.loads(r["nodes"] or "[]"):
            conn.execute("INSERT OR IGNORE INTO workflow_nodes VALUES (?, ?)", (wf_id, node))
        for cat in json.loads(r["categories"] or "[]"):
            conn.execute("INSERT OR IGNORE INTO workflow_categories VALUES (?, ?)", (wf_id, cat))
    conn.commit()


def insert_workflow(name, description, nodes, categories, node_count,
                    trigger_type, source_url, source_repo, json_content, json_hash):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    try:
        cursor = conn.execute("""
            INSERT INTO workflows (name, description, nodes, categories, node_count,
                trigger_type, source_url, source_repo, json_content, json_hash, added_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, json.dumps(nodes), json.dumps(categories),
              node_count, trigger_type, source_url, source_repo, json_content, json_hash, now, now))
        wf_id = cursor.lastrowid

        nodes_list = nodes if isinstance(nodes, list) else json.loads(nodes)
        for node in nodes_list:
            conn.execute("INSERT OR IGNORE INTO workflow_nodes VALUES (?, ?)", (wf_id, node))
        cats_list = categories if isinstance(categories, list) else json.loads(categories)
        for cat in cats_list:
            conn.execute("INSERT OR IGNORE INTO workflow_categories VALUES (?, ?)", (wf_id, cat))

        conn.commit()
        return wf_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return None


def insert_workflows_batch(workflows_data):
    """Insert multiple workflows in a single transaction.
    workflows_data: list of dicts from parse_workflow_json + source_url/source_repo.
    Returns (imported_count, duplicate_count).
    """
    conn = get_db()
    now = datetime.utcnow().isoformat()
    imported = 0
    duplicates = 0

    try:
        for wf in workflows_data:
            try:
                cursor = conn.execute("""
                    INSERT INTO workflows (name, description, nodes, categories, node_count,
                        trigger_type, source_url, source_repo, json_content, json_hash, added_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (wf["name"], wf["description"],
                      json.dumps(wf["nodes"]), json.dumps(wf["categories"]),
                      wf["node_count"], wf["trigger_type"],
                      wf.get("source_url", ""), wf.get("source_repo", ""),
                      wf["json_content"], wf["json_hash"], now, now))
                wf_id = cursor.lastrowid

                for node in wf["nodes"]:
                    conn.execute("INSERT OR IGNORE INTO workflow_nodes VALUES (?, ?)", (wf_id, node))
                for cat in wf["categories"]:
                    conn.execute("INSERT OR IGNORE INTO workflow_categories VALUES (?, ?)", (wf_id, cat))

                imported += 1
            except sqlite3.IntegrityError:
                duplicates += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return imported, duplicates


def search_workflows(query="", category="", node="", page=1, per_page=24,
                     sort="recent", min_score=0):
    conn = get_db()
    conditions = []
    params = []

    if query:
        fts_query = " OR ".join(f'"{w}"*' for w in query.strip().split())
        conditions.append("w.id IN (SELECT rowid FROM workflows_fts WHERE workflows_fts MATCH ?)")
        params.append(fts_query)

    if category:
        conditions.append("w.id IN (SELECT workflow_id FROM workflow_categories WHERE category_name = ?)")
        params.append(category)

    if node:
        conditions.append("w.id IN (SELECT workflow_id FROM workflow_nodes WHERE node_name = ?)")
        params.append(node)

    if min_score > 0:
        conditions.append("w.ai_usefulness >= ?")
        params.append(min_score)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * per_page

    # Sort options
    sort_map = {
        "recent": "w.added_at DESC",
        "usefulness": "w.ai_usefulness DESC, w.added_at DESC",
        "complexity_asc": "w.ai_complexity ASC, w.added_at DESC",
        "complexity_desc": "w.ai_complexity DESC, w.added_at DESC",
        "nodes": "w.node_count DESC, w.added_at DESC",
    }
    order_by = sort_map.get(sort, "w.added_at DESC")

    count = conn.execute(f"SELECT COUNT(*) FROM workflows w {where}", params).fetchone()[0]

    rows = conn.execute(f"""
        SELECT w.id, w.name, w.description, w.nodes, w.categories, w.node_count,
               w.trigger_type, w.source_url, w.source_repo, w.added_at,
               w.ai_usefulness, w.ai_complexity, w.ai_summary,
               w.ai_use_cases, w.ai_target_audience, w.ai_integrations_summary, w.ai_difficulty_level
        FROM workflows w {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    """, params + [per_page, offset]).fetchall()

    return {
        "total": count,
        "page": page,
        "per_page": per_page,
        "pages": (count + per_page - 1) // per_page,
        "workflows": [dict(r) for r in rows]
    }


def get_workflow(wf_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM workflows WHERE id = ?", (wf_id,)).fetchone()
    return dict(row) if row else None


def delete_workflow(wf_id):
    conn = get_db()
    conn.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))
    conn.commit()


def get_all_nodes():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT node_name FROM workflow_nodes ORDER BY node_name").fetchall()
    return [r["node_name"] for r in rows]


def get_all_categories():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT category_name FROM workflow_categories ORDER BY category_name").fetchall()
    return [r["category_name"] for r in rows]


def get_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
    repos = conn.execute("SELECT COUNT(*) FROM github_repos").fetchone()[0]
    unique_nodes = conn.execute("SELECT COUNT(DISTINCT node_name) FROM workflow_nodes").fetchone()[0]
    analyzed = conn.execute("SELECT COUNT(*) FROM workflows WHERE ai_analyzed_at != ''").fetchone()[0]
    avg_usefulness = conn.execute("SELECT COALESCE(AVG(ai_usefulness), 0) FROM workflows WHERE ai_analyzed_at != ''").fetchone()[0]
    return {
        "total_workflows": total, "total_repos": repos, "unique_nodes": unique_nodes,
        "analyzed_count": analyzed, "avg_usefulness": round(avg_usefulness, 1)
    }


def update_workflow_ai(wf_id, usefulness, universality, complexity, scalability, summary, tags, 
                       use_cases=None, target_audience=None, integrations_summary=None, difficulty_level=None):
    """Update AI analysis scores for a workflow."""
    conn = get_db()
    conn.execute("""
        UPDATE workflows SET
            ai_usefulness = ?, ai_universality = ?, ai_complexity = ?,
            ai_scalability = ?, ai_summary = ?, ai_tags = ?,
            ai_use_cases = ?, ai_target_audience = ?, ai_integrations_summary = ?, 
            ai_difficulty_level = ?, ai_analyzed_at = ?
        WHERE id = ?
    """, (usefulness, universality, complexity, scalability, summary,
          json.dumps(tags, ensure_ascii=False), 
          json.dumps(use_cases or [], ensure_ascii=False),
          target_audience or "",
          integrations_summary or "",
          difficulty_level or "",
          datetime.utcnow().isoformat(), wf_id))
    conn.commit()


def get_unanalyzed_workflows(limit=50):
    """Get workflows that haven't been analyzed by AI yet."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, name, description, nodes, categories, node_count, trigger_type, json_content
        FROM workflows WHERE ai_analyzed_at = '' OR ai_analyzed_at IS NULL
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# GitHub repos management
def add_github_repo(repo_url):
    conn = get_db()
    try:
        conn.execute("INSERT INTO github_repos (repo_url) VALUES (?)", (repo_url,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_github_repos():
    conn = get_db()
    rows = conn.execute("SELECT * FROM github_repos ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def update_repo_sync(repo_url, count):
    conn = get_db()
    conn.execute("UPDATE github_repos SET last_synced = ?, workflow_count = ? WHERE repo_url = ?",
                 (datetime.utcnow().isoformat(), count, repo_url))
    conn.commit()


def delete_github_repo(repo_id):
    conn = get_db()
    repo = conn.execute("SELECT repo_url FROM github_repos WHERE id = ?", (repo_id,)).fetchone()
    if repo:
        conn.execute("DELETE FROM workflows WHERE source_repo = ?", (repo["repo_url"],))
        conn.execute("DELETE FROM github_repos WHERE id = ?", (repo_id,))
        conn.commit()
