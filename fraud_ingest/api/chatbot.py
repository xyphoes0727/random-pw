"""
Core module for the AI Chatbot that handles tool-use orchestration,
database interaction (MySQL), vector database querying (Pinecone),
and conversation management using Django's cache.

It defines functions for running read-only SQL queries, embedding user
queries for vector search, generating data for plotting, and managing
conversation history.
"""

from .constants import (
    MAX_TEXT_CHARS,
    RETRIEVER_TIMEOUT,
    RETRIEVER_RETRIES,
    MAX_INPUT_CHARS,
    SELECT_ONLY_RE,
    FORBIDDEN_RE,
    ALLOWED_COLUMNS,
    SYSTEM_PROMPT,
    PLOT_KEYWORDS
)

import os
import json
import re
import time
import requests
from dotenv import load_dotenv
from openai import OpenAI
import pymysql
from dbutils.pooled_db import PooledDB
from typing import Any, Dict, List, Tuple
from loguru import logger
from pinecone import Pinecone
import uuid
from django.core.cache import cache
from .constants import MODEL

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')

load_dotenv(dotenv_path=dotenv_path)


PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index("quickstart")

DB_NAME = os.getenv("MYSQL_DATABASE")
DB_USER = os.getenv("MYSQL_USER")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))

CONVERSATION_TTL = 86400
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_KEY_2 = os.getenv("OPENAI_API_KEY_2", "")

client_tool = OpenAI(api_key=OPENAI_API_KEY)


if not DB_NAME or not DB_USER:
    raise RuntimeError(
        "Missing MYSQL_DATABASE or MYSQL_USER in environment (chatbot tool)")

_pool = PooledDB(
    creator=pymysql,
    maxconnections=5,
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
    autocommit=True,
    cursorclass=pymysql.cursors.DictCursor
)

SENSITIVE_COLUMNS = [
    "nameorig",
    "namedest",
    "account",
]


def _mask_value(value: Any, column_name: str) -> Any:
    """
    Masks sensitive string values in a column, leaving the first and last four
    characters visible, or returns the original value if it's too short.
    """
    str_val = str(value)

    if len(str_val) > 4:
        prefix_len = 1
        suffix_len = 4

        prefix = str_val[:prefix_len]
        suffix = str_val[-suffix_len:]
        masked_part = '*' * (len(str_val) - prefix_len - suffix_len)

        if len(masked_part) < 1:
            return str_val

        return f"{prefix}{masked_part}{suffix}"

    return str_val


def _mask_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Applies value masking to all columns listed in SENSITIVE_COLUMNS
    within a row.
    """
    masked_row = {}
    for col, value in row.items():
        if col.lower() in SENSITIVE_COLUMNS:
            masked_row[col] = _mask_value(value, col)
        else:
            masked_row[col] = value
    return masked_row


def run_read_query(query: str) -> Dict[str, Any]:
    """
    Executes a read-only SQL query against the MySQL pool and
    returns the results.
    """
    conn = None
    cur = None
    try:
        conn = _pool.connection()
        cur = conn.cursor()
        query_start = time.time()
        cur.execute(query)
        logger.info(f"[TIME] SQL query executed in {time.time() - query_start:.2f} seconds")
        rows = cur.fetchall()
        if not rows:
            return {"columns": [], "rows": [], "message": "No data found."}

        masked_rows = [_mask_row(row) for row in rows]

        columns = list(rows[0].keys())
        data_rows = [[row[col] for col in columns] for row in masked_rows]
        message = f"Query executed successfully. {len(data_rows)} rows."
        return {"columns": columns, "rows": data_rows, "message": message}

    except pymysql.err.MySQLError as e:
        return {"error": f"MySQL Error: {type(e).__name__}: {str(e)}"}
    except Exception as e:
        return {"error": f"Backend Error: {type(e).__name__}: {str(e)}"}

    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def is_safe_read_query(q: str) -> Tuple[bool, str]:
    """
    Checks if a given query is safe and read-only (only SELECT statements
    are permitted, with checks against forbidden keywords).
    """
    if not q or not q.strip():
        return False, "Empty query"
    if FORBIDDEN_RE.search(q):
        return False, "Forbidden SQL keywords or semicolon detected."
    if not SELECT_ONLY_RE.match(q):
        return False, "Only SELECT queries are allowed."
    return True, "Ok, can read this query."


def _get_cache_key(conversation_id: str) -> str:
    """Generate cache key for conversation"""
    return f"conversation:{conversation_id}"


def get_or_create_conversation(conversation_id: str = None) -> tuple:
    """Get existing conversation from cache or create new one"""
    if conversation_id:
        try:
            cache_key = _get_cache_key(conversation_id)
            cache_start = time.time()
            history = cache.get(cache_key)
            logger.info(f"[TIME] Cache read took {time.time() - cache_start:.4f}s")
            if history is not None:
                logger.info(
                    f"Retrieved conversation {conversation_id}"
                    f"from cache with {len(history)} messages")
                return conversation_id, history
        except Exception as e:
            logger.error(f"Error retrieving conversation from cache: {e}")

    # Create new conversation
    new_id = str(uuid.uuid4())
    cache_key = _get_cache_key(new_id)
    try:
        cache.set(cache_key, [], timeout=CONVERSATION_TTL)
        logger.info(f"Created new conversation {new_id} in cache")
    except Exception as e:
        logger.error(f"Error creating conversation in cache: {e}")
        raise

    return new_id, []


def add_to_conversation(conversation_id: str, role: str,
                        content: str, tool_calls=None):
    """Add message to conversation history in cache"""
    try:
        cache_key = _get_cache_key(conversation_id)
        history = cache.get(cache_key, [])

        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls

        history.append(message)
        cache_start = time.time()
        cache.set(cache_key, history, timeout=CONVERSATION_TTL)
        logger.info(f"[TIME] Cache write took {time.time() - cache_start:.4f}s")
        logger.debug(f"Added {role} message to conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error adding to conversation: {e}")
        raise


def get_conversation_context(conversation_id: str) -> List[Dict]:
    """Get full conversation history from cache (no message limit)"""
    try:
        cache_key = _get_cache_key(conversation_id)
        history = cache.get(cache_key, [])
        logger.debug(
            f"Retrieved {len(history)} messages"
            f"for conversation {conversation_id}")
        return history
    except Exception as e:
        logger.error(f"Error getting conversation context: {e}")
        return []


def clear_conversation(conversation_id: str):
    """Clear conversation history from cache"""
    try:
        cache_key = _get_cache_key(conversation_id)
        cache.delete(cache_key)
        logger.info(f"Cleared conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error clearing conversation: {e}")


def refresh_conversation_ttl(conversation_id: str):
    """Refresh the TTL of a conversation (extend expiration by 1 day)"""
    try:
        cache_key = _get_cache_key(conversation_id)
        history = cache.get(cache_key)
        if history is not None:
            cache.set(cache_key, history, timeout=CONVERSATION_TTL)
            logger.debug(f"Refreshed TTL for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error refreshing conversation TTL: {e}")


sql_tool_schema = [{
    "type": "function",
    "function": {
        "name": "run_sql_query",
        "description":
        "Run a read-only SQL query on the MySQL transactions database",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "only select query allowed"}
            },
            "required": ["query"]
        }
    }
}]

error_tool_schema = [{
    "type": "function",
    "function": {
        "name": "query_vector_db",
        "description": "Query Pinecone vector DB for similar incidents.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 10}
            },
            "required": ["query"]
        }
    }
}]

plot_tool_schema = [{
    "type": "function",
    "function": {
        "name": "get_plot_data",
        "description": (
            "Generate aggregated data for plotting (SELECT-only)."
            "Supports chart_type: "
            "line, bar, pie, scatter. Returns chart-friendly JSON:"
            "{ chart_type, meta:{sql}, chart:{labels, datasets} }."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "pie", "scatter"],
                    "description": "Chart type to return"
                },
                "aggregation": {
                    "type": "string",
                    "enum": ["count", "sum", "avg", "min", "max"],
                    "description": "Aggregation function for metric"
                    "(count works without metric)"
                },
                "metric": {
                    "type": "string",
                    "description": "Numeric column to aggregate."
                    "Use transactionId only with count."
                },
                "x_column": {
                    "type": "string",
                    "description": "Column for x-axis (for scatter)"
                    "or time column for time-series (default: 'time')"
                },
                "y_column": {
                    "type": "string",
                    "description": "Column for y-axis (for scatter)"
                },
                "time_granularity": {
                    "type": "string",
                    "enum": ["hour", "day", "week", "month"],
                    "description": "Time bucket when chart_type is line"
                },
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "group_by": {"type": "string", "description":
                             "Optional categorical column for"
                             "grouped bar or multi-line"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["chart_type"]
        }
    }
}]


def _normalize_minimal(
        item: Dict[str, Any], source: str, rank: int) -> Dict[str, Any]:
    """Return only essential fields (minimal schema).
    Truncate text to avoid huge payloads."""
    if not isinstance(item, dict):
        return {
            "source": source,
            "rank": rank,
            "score": None,
            "text": str(item),
            "metadata": {}
        }

    text = item.get("text") or item.get("snippet") or ""
    if isinstance(text, str) and len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "...(truncated)"

    return {
        "source": source,
        "rank": rank,
        "score": item.get("score"),
        "text": text,
        "metadata": item.get("metadata") or {}
    }


def _call_retriever_and_normalize(url: str, payload: Dict[str, Any],
                                  source: str,
                                  timeout: float = 8.0) -> Dict[str, Any]:
    """
    Call retriever and return normalized 'results' list and any error.
    """
    last_err = None
    for attempt in range(1, RETRIEVER_RETRIES + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            raw = data.get("results", data.get("items", []))

            results = []
            for idx, item in enumerate(raw, start=1):
                results.append(_normalize_minimal(item, source, rank=idx))

            return {"results": results}
        except requests.RequestException as e:
            last_err = str(e)
            if attempt < RETRIEVER_RETRIES:
                time.sleep(0.5 * attempt)
            continue
        except ValueError:
            return {"error": f"{source} retriever returned non-json response",
                    "results": []}

    return {"error": f"{source} retriever failed after"
            f"{RETRIEVER_RETRIES} attempts: {last_err}", "results": []}


def run_sql_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool handler for 'run_sql_query'. Validates query safety and executes it.
    """
    q = (args.get("query", "") or "").strip()
    ok, reason = is_safe_read_query(q)
    if not ok:
        return {"error": reason}
    return run_read_query(q)


def run_query_vector_db_tool(args: dict) -> dict:
    """
    Tool handler for 'query_vector_db'. Generates an embedding for the query
    and queries the Pinecone index.
    """
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "Empty query"}

    try:
        k = int(args.get("k", 10))
    except (ValueError, TypeError):
        k = 10

    # Create embedding
    emb = []
    try:
        client_emb = OpenAI(api_key=OPENAI_API_KEY)

        emb = client_emb.embeddings.create(
            model="text-embedding-3-small",
            input=q
        ).data[0].embedding

    except Exception as e:
        logger.warning(
            f"OpenAI first key. Switching to second key | Error: {e}  Resp: {emb}")

        try:
            client_emb_2 = OpenAI(api_key=OPENAI_API_KEY_2)
            emb = client_emb_2.embeddings.create(
                model="text-embedding-3-small",
                input=q
            ).data[0].embedding

        except Exception as e:
            logger.error(f"Second API Key also failed. ")
            return {"error": f"Embedding failed: {e}"}

    try:
        result = index.query(
            vector=emb,
            top_k=k,
            include_metadata=True,
        )
    except Exception as e:
        return {"error": f"Pinecone query failed: {e}"}

    # Format results
    pine_results = []
    for rank, match in enumerate(result.matches, start=1):
        pine_results.append({
            "source": "pinecone",
            "rank": rank,
            "score": match.score,
            "id": match.id,
            "metadata": match.metadata or {}
        })

    return {
        "query": q,
        "k": k,
        "pinecone": pine_results,
    }


def _is_allowed(col: str) -> bool:
    return isinstance(col, str) and col in ALLOWED_COLUMNS


def _time_bucket_sql(col: str, interval: str) -> str:
    """
    Generates the MySQL SQL expression for time-series aggregation (bucketing).
    """
    if interval == "hour":
        return f"DATE_FORMAT({col}, '%Y-%m-%d %H:00:00')"
    if interval == "day":
        return f"DATE({col})"
    if interval == "week":
        return f"CONCAT(YEAR({col}), '-', LPAD(WEEK({col}),2,'0'))"
    if interval == "month":
        return f"DATE_FORMAT({col}, '%Y-%m-01')"
    return f"DATE({col})"


def run_plot_tool(args: dict) -> dict:
    """
    Tool handler for 'get_plot_data'. Constructs a database query to aggregate
    data based on plotting requirements (line, bar, pie, scatter) and formats
    the result into a chart-friendly JSON payload.
    """
    if not isinstance(args, dict):
        return {"error": "Invalid args: expected object"}

    chart_type = (args.get("chart_type") or "").lower()
    aggregation = (args.get("aggregation") or "").lower()
    metric = args.get("metric")
    x_column = args.get("x_column")
    y_column = args.get("y_column")
    time_granularity = (args.get("time_granularity")
                        or "day").lower()
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    group_by = args.get("group_by")

    if not chart_type:
        if (x_column and x_column in ("time", "step")) or not x_column:
            chart_type = "line"
        else:
            chart_type = "bar"

    if chart_type in ("line", "bar", "pie"):
        if not aggregation:
            aggregation = "count"
        elif aggregation not in ("count", "sum", "avg", "min", "max"):
            return {
                "error": "aggregation must be one of: count,sum,avg,min,max."
            }

        if aggregation != "count":
            if not metric or (
                    metric != "transactionId" and not _is_allowed(metric)):
                return {"error": f"Invalid metric '{metric}'."}

    if chart_type == "line":
        if not x_column:
            x_column = "time"

    if chart_type == "scatter":
        if not x_column or not y_column:
            return {"error": "scatter requires x_column and y_column."}
        if not _is_allowed(x_column) or not _is_allowed(y_column):
            return {"error": "x_column/y_column not allowed."}

    if chart_type not in ("line", "bar", "pie", "scatter"):
        return {"error": "chart_type must be one of: line, bar, pie, scatter."}

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def _validate_date_str(d: str) -> bool:
        return bool(d and isinstance(d, str) and _DATE_RE.match(d))

    if start_date and not _validate_date_str(start_date):
        return {"error": "start_date must be in YYYY-MM-DD format."}
    if end_date and not _validate_date_str(end_date):
        return {"error": "end_date must be in YYYY-MM-DD format."}

    try:
        limit = max(1, min(int(args.get("limit", 10)), 1000))
    except Exception:
        limit = 10

    time_column = x_column if (x_column and chart_type == "line") else "time"
    if time_column and not _is_allowed(time_column):
        return {"error": f"time/x_column '{time_column}' not allowed."}
    if group_by and not _is_allowed(group_by):
        return {"error": f"group_by '{group_by}' not allowed."}

    where = []
    if start_date:
        where.append(f"{time_column} >= '{start_date} 00:00:00'")
    if end_date:
        where.append(f"{time_column} <= '{end_date} 23:59:59'")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    try:
        if chart_type == "line":
            agg = (
                "COUNT(*) as value"
                if aggregation == "count"
                else f"{aggregation.upper()}({metric}) as value"
            )
            bucket = _time_bucket_sql(time_column, time_granularity)
            if group_by:
                sql = (
                    f"SELECT {bucket} AS bucket, {group_by} AS label, {agg} "
                    f"FROM enriched{where_sql} "
                    "GROUP BY bucket,label "
                    "ORDER BY bucket ASC, value DESC"
                )
            else:
                sql = (
                    f"SELECT {bucket} AS bucket, {agg} "
                    f"FROM enriched{where_sql} "
                    "GROUP BY bucket "
                    "ORDER BY bucket ASC"
                )

        elif chart_type == "bar":
            if group_by and not time_granularity:
                agg = (
                    "COUNT(*) as value"
                    if aggregation == "count"
                    else f"{aggregation.upper()}({metric}) as value"
                )
                sql = (
                    f"SELECT {group_by} AS label, {agg} "
                    f"FROM enriched{where_sql} "
                    "GROUP BY label "
                    "ORDER BY value DESC "
                    f"LIMIT {limit}"
                )
            else:
                agg = (
                    "COUNT(*) as value"
                    if aggregation == "count"
                    else f"{aggregation.upper()}({metric}) as value"
                )
                bucket = _time_bucket_sql(time_column, time_granularity)
                sql = (
                    f"SELECT {bucket} AS bucket, {agg} "
                    f"FROM enriched{where_sql} "
                    "GROUP BY bucket "
                    "ORDER BY bucket ASC"
                )

        elif chart_type == "pie":
            if not group_by:
                return {"error": "pie requires group_by (category column)."}
            agg = (
                "COUNT(*) as value"
                if aggregation == "count"
                else f"{aggregation.upper()}({metric}) as value"
            )
            sql = (
                f"SELECT {group_by} AS label, {agg} "
                f"FROM enriched{where_sql} "
                "GROUP BY label "
                "ORDER BY value DESC "
                f"LIMIT {limit}"
            )

        elif chart_type == "scatter":

            local_where = list(where)
            local_where.append(f"{x_column} IS NOT NULL")
            local_where.append(f"{y_column} IS NOT NULL")
            where_sql_scatter = (
                " WHERE " + " AND ".join(local_where)) if local_where else ""
            sql = (
                f"SELECT {x_column} AS x, {y_column} AS y "
                f"FROM enriched{where_sql_scatter} "
                f"LIMIT {limit}"
            )

        else:
            return {"error": "Unhandled chart_type."}
        
        logger.info(f"Generated SQL for plot: {sql}")
        plot_sql_start = time.time()
        res = run_read_query(sql)
        logger.info(f"[TIME] run_plot_tool SQL execution took {time.time() - plot_sql_start:.4f}s")
        if "error" in res:
            return {"error": res["error"]}

        cols = res.get("columns", [])
        raw_rows = res.get("rows", [])

        normalized_rows = []
        for r in raw_rows:
            if isinstance(r, dict):
                normalized_rows.append(r)
            elif isinstance(r, (list, tuple)):
                mapped = {cols[i]: r[i] if i < len(
                    r) else None for i in range(len(cols))}
                normalized_rows.append(mapped)
            else:
                key = cols[0] if cols else "value"
                normalized_rows.append({key: r})

        rows = normalized_rows
        payload = {"chart_type": chart_type, "meta": {"sql": sql}}

        if chart_type == "line":
            if not rows:
                payload["chart"] = {"labels": [], "datasets": []}
            else:
                if "label" in cols and "bucket" in cols:
                    buckets = []
                    series = {}
                    for r in rows:
                        b = str(r.get("bucket"))
                        lbl = str(r.get("label"))
                        val = float(r.get("value") or 0)
                        if b not in buckets:
                            buckets.append(b)
                        series.setdefault(lbl, {})[b] = val
                    datasets = [{"label": k, "data": [series[k].get(
                        b, 0) for b in buckets]} for k in series]
                    payload["chart"] = {
                        "labels": buckets, "datasets": datasets}
                else:
                    labels = [str(r.get("bucket")) for r in rows]
                    data = [float((r.get("value") or 0)) for r in rows]
                    payload["chart"] = {
                        "labels": labels,
                        "datasets": [{"label":
                                      f"{aggregation}({metric or 'count'})",
                                      "data": data}]
                    }

        elif chart_type in ("bar", "pie"):
            if not rows:
                payload["chart"] = {"labels": [], "datasets": []}
            else:
                label_key = "label" if "label" in cols else (
                    cols[0] if cols else None)
                value_key = "value" if "value" in cols else (
                    cols[1] if len(cols) > 1 else None)
                labels = [str(r.get(label_key)) for r in rows]
                data = [float((r.get(value_key) or 0)) for r in rows]
                payload["chart"] = {
                    "labels": labels,
                    "datasets": [
                        {
                            "label": f"{aggregation}({metric or 'count'})",
                            "data": data
                        }
                    ]
                }
        else:
            points = []
            for r in rows:
                x = r.get("x")
                y = r.get("y")
                try:
                    points.append({"x": float(x), "y": float(y)})
                except Exception:
                    continue
            payload["chart"] = {"datasets": [
                {"label": f"{y_column} vs {x_column}", "data": points}]}
        logger.info("Payload", payload)
        return {"ok": True, "result": payload, "message": res["message"]}

    except Exception as e:
        return {"error": f"Plot tool error: {type(e).__name__}: {e}"}


tool_handlers = {
    "run_sql_query": run_sql_tool,
    "query_vector_db": run_query_vector_db_tool,
    "get_plot_data": run_plot_tool
}

ALL_TOOLS_SCHEMA = sql_tool_schema + error_tool_schema + plot_tool_schema


def is_plot_intent(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.lower()
    return any(kw in t for kw in PLOT_KEYWORDS)


def chat_plot_with_context(user_input: str,
                           conversation_id: str = None) -> Dict[str, Any]:
    """For 'make a graph' style requests with context"""

    conv_id, history = get_or_create_conversation(conversation_id)

    messages = [
        {
            "role": "system",
            "content": (
                SYSTEM_PROMPT
                + "\nThis is a plot/graph request. "
                + "You MUST call the get_plot_data tool."
            ),
        }
    ]

    context = get_conversation_context(conv_id)
    messages.extend(context)

    messages.append({"role": "user", "content": user_input})

    add_to_conversation(conv_id, "user", user_input)

    response = client_tool.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=plot_tool_schema,
        tool_choice="auto",
    )

    msg = response.choices[0].message
    if not getattr(msg, "tool_calls", None):
        return {"error": "Model did not call get_plot_data tool.",
                "conversation_id": conv_id}

    plot_call = None
    for c in msg.tool_calls:
        if c.function.name == "get_plot_data":
            plot_call = c
            break

    if plot_call is None:
        return {"error": "No get_plot_data tool call in response.",
                "conversation_id": conv_id}

    raw_args = plot_call.function.arguments or "{}"
    try:
        args = json.loads(raw_args) if isinstance(
            raw_args, str) else (raw_args or {})
    except json.JSONDecodeError:
        return {"error": "Invalid arguments for get_plot_data.",
                "conversation_id": conv_id}

    if not args.get("aggregation"):
        args["aggregation"] = "count"
    if not args.get("chart_type"):
        x_col = args.get("x_column")
        if x_col in ("time", "step") or not x_col:
            args["chart_type"] = "line"
        else:
            args["chart_type"] = "bar"

    logger.info(f"chat_plot: running get_plot_data with args={args}")
    result = run_plot_tool(args)

    add_to_conversation(conv_id, "assistant", json.dumps(result, default=str))

    return {
        "mode": "plot",
        "tool": "get_plot_data",
        "tool_args": args,
        "response": result,
        "conversation_id": conv_id,
    }


def chat_stream_with_context(user_input: str, conversation_id: str = None):
    """General multi-tool orchestration with conversation context"""
    request_start = time.time()
    logger.info(f"[TIME] Starting chat_stream_with_context")

    conv_id, history = get_or_create_conversation(conversation_id)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    context = get_conversation_context(conv_id)
    messages.extend(context)

    messages.append({"role": "user", "content": user_input})

    add_to_conversation(conv_id, "user", user_input)

    assistant_response = ""

    while True:
        response = client_tool.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=ALL_TOOLS_SCHEMA,
            tool_choice="auto",
        )

        msg = response.choices[0].message

        if not getattr(msg, "tool_calls", None):
            break

        logger.debug(f"LLM requested {len(msg.tool_calls)} tool calls(s).")

        tool_call_messages = []

        for call in msg.tool_calls:
            tool_name = call.function.name
            tool_call_id = call.id

            if tool_name not in tool_handlers:
                logger.warning(f"Unknown tool requested: {tool_name}")
                error_msg = (
                    "Sorry, I don't have the ability to perform"
                    f"the action '{tool_name}'.\n"
                    "Can you clarify what exactly you'd like me to do?"
                )
                yield error_msg
                add_to_conversation(conv_id, "assistant", error_msg)
                return

            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(
                    raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                error_msg = (
                    "I received an invalid or incomplete request.\n"
                    "Could you clarify your query or action so I can"
                    "help properly?"
                )
                yield error_msg
                add_to_conversation(conv_id, "assistant", error_msg)
                return

            logger.info(f"Running tool '{tool_name}' with args={args}")
            tool_time = time.time()
            logger.info(f"[TIME] Tool '{tool_name}' execution started at {tool_time}")

            try:
                result = tool_handlers[tool_name](args)
                logger.info(f"[TIME] Tool '{tool_name}' execution completed in"
                            f" {time.time() - tool_time:.2f} seconds")
            except Exception as e:
                logger.exception(f"Tool '{tool_name}' failed.")
                error_msg = (
                    f"I tried to perform '{tool_name}' but"
                    "something went wrong.\n"
                    f"Error: {type(e).__name__}\n"
                    "Please clarify what you'd like me to do."
                )
                yield error_msg
                add_to_conversation(conv_id, "assistant", error_msg)
                return

            tool_call_messages.append({
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result, default=str),
                "tool_call_id": tool_call_id
            })

            if tool_name == "get_plot_data":
                if isinstance(result, dict) and result.get("error"):
                    err_obj = {
                        "error": str(result.get("error")),
                        "meta": result.get("meta", {})
                    }
                    tool_call_messages.append({
                        "role": "assistant",
                        "content": json.dumps(err_obj)
                    })
                else:
                    payload = result.get("result") if isinstance(
                        result, dict) else None
                    if not payload:
                        err_obj = {
                            "error": "Plot tool returned no payload",
                            "meta": {"sql": None}
                        }
                        tool_call_messages.append({
                            "role": "assistant",
                            "content": json.dumps(err_obj)
                        })
                    else:
                        tool_call_messages.append({
                            "role": "assistant",
                            "content": json.dumps(payload, default=str)
                        })

        messages.append({
            "role": "assistant",
            "tool_calls": msg.tool_calls,
        })
        messages.extend(tool_call_messages)

    stream = client_tool.chat.completions.create(
        messages=messages,
        model=MODEL,
        stream=True,
    )

    for chunks in stream:
        choice = chunks.choices[0]
        delta = choice.delta
        if delta.content:
            text_piece = delta.content
            assistant_response += text_piece
            yield text_piece

    add_to_conversation(conv_id, "assistant", assistant_response)

    yield f"\n__CONVERSATION_ID__:{conv_id}"

    logger.info("Streaming completed with context saved")
    logger.info(f"[TIME] chat_stream_with_context completed in"
                f" {time.time() - request_start:.2f} seconds")


def chat(user_input: str, conversation_id: str = None) -> str:
    """
    Return full response as a single string with conversation context.
    """
    return "".join(chat_stream_with_context(user_input, conversation_id))
