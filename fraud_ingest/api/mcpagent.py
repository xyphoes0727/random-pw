from fastapi import WebSocket, WebSocketDisconnect
from pathway.io import python as pw_python
from typing import TypedDict, Optional
from pathway.internals.config import get_pathway_config
import math
from neo4j import GraphDatabase
from fastapi import FastAPI, Request
import uvicorn
import os
import json
import base64
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aio_pika
import httpx
from openai import OpenAI
from pinecone import Pinecone
import pathway as pw
from pathway.xpacks.llm.mcp_server import McpServable, McpServer, PathwayMcp

message_buffer = asyncio.Queue()
load_dotenv()

X_API_KEY = os.getenv("X_API_KEY")
DUMMY_MAIL = os.getenv("DUMMY_MAIL")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "quickstart")
LOKI_ENDPOINT = os.getenv("LOKI_ENDPOINT", "")
LOKI_INSTANCE_ID = os.getenv("LOKI_INSTANCE_ID")
GRAFANA_CLOUD_ACCESS_TOKEN = os.getenv("GRAFANA_CLOUD_ACCESS_TOKEN")
PATHWAY_LICENSE_KEY = os.getenv("PW_LICENSE_KEY")
MCP_BROKER_URL = os.getenv("MCP_BROKER_URL")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_KEY_2 = os.environ.get("OPENAI_API_KEY_2")

client_emb = OpenAI(api_key=OPENAI_API_KEY)

if not PINECONE_API_KEY:
    raise RuntimeError("PINECONE_API_KEY missing in environment")

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX_NAME)

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
MYSQL_DB = os.getenv("MYSQL_DATABASE")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_HOST = os.getenv("MYSQL_HOST")

rdkafka_settings = {
    "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093"),
    "group.id": "ml",
    "auto.offset.reset": "earliest",
    "security.protocol": "plaintext",
}


def loki_headers():
    auth = f"{LOKI_INSTANCE_ID}:{GRAFANA_CLOUD_ACCESS_TOKEN}"
    return {
        "Authorization": "Basic " + base64.b64encode(auth.encode()).decode(),
        "Accept": "application/json",
    }


async def fetch_logs(start_iso: str, window_sec: int = 5, loki_query: str = "{}"):
    try:
        ts = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except:
        return []

    start = int((ts - timedelta(seconds=window_sec)).timestamp() * 1e9)
    end = int((ts + timedelta(seconds=window_sec)).timestamp() * 1e9)

    url = f"{LOKI_ENDPOINT.rstrip('/')}/loki/api/v1/query_range"

    params = {
        "query": loki_query,
        "start": start,
        "end": end,
        "limit": 3000,
    }

    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(url, headers=loki_headers(), params=params)
        resp.raise_for_status()

    logs = []
    payload = resp.json()

    for stream in payload.get("data", {}).get("result", []):
        for _, line in stream.get("values", []):
            logs.append(line)
    print("Logs:", logs)
    return logs


def analyze_with_llm(combined_logs: str):
    """
    Accepts a single string. Returns parsed JSON dict (summary/cause/category) or error dict.
    """
    prompt = f"""
    Return only JSON:
    {{
    "summary": "...",
    "cause": "...",
    "category": "..."
    }}

    Logs:
    {combined_logs}
    """

    resp = client_emb.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        # keep default token limits; adjust if you need longer context
    )
    content = resp.choices[0].message.content
    if not content:
        content = ""

    raw = content.strip()
    try:
        if raw.startswith(""):
            # strip triple fence if present
            # handle json ...  or \n...\n
            lines = raw.splitlines()
            if len(lines) >= 3 and lines[0].startswith("") and lines[-1].startswith("```"):
                raw = "\n".join(lines[1:-1])
            else:
                raw = raw.strip("`")
        return json.loads(raw)
    except Exception:
        return {"error": "llm_parse_failed", "raw": raw}


def generate_alert_message_sync(alert_data):
    try:
        alerts = alert_data.get("alerts", [])
        if not alerts:
            return {"error": "No alerts found in payload"}

        first_alert = alerts[0]

        alert_context = {
            "alert_name": first_alert.get("labels", {}).get("alertname", "Unknown"),
            "severity": first_alert.get("labels", {}).get("severity", "warning"),
            "status": first_alert.get("status", "firing"),
            "starts_at": first_alert.get("startsAt"),
            "summary": first_alert.get("annotations", {}).get("summary", ""),
            "description": first_alert.get("annotations", {}).get("description", ""),
        }

        prompt = f"""
        Create a one-line summary of this alert:

        Alert: {alert_context['alert_name']}
        Severity: {alert_context['severity']}
        Status: {alert_context['status']}
        Summary: {alert_context['summary']}

        Return ONLY one sentence.
        """

        try:
            client_chat = OpenAI(api_key=OPENAI_API_KEY)

            response = client_chat.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=50
            )

            summary = response.choices[0].message.content.strip()

            return {
                "error": "null",
                "summary": summary
            }

        except Exception:
            try:
                client_chat_2 = OpenAI(api_key=OPENAI_API_KEY_2)
                response = client_chat_2.chat.completions.create(
                    model="gpt-4.1",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=50
                )

                summary = response.choices[0].message.content.strip()

                return {
                    "error": "null",
                    "summary": summary
                }

            except Exception as e:
                return {
                    "error": str(e),
                    "summary": ""
                }
    except Exception:
        pass


async def fetch_and_summarize(start_iso: str, window_sec=5, loki_query='{app_id!=""}', upload=False):
    logs = await fetch_logs(start_iso, window_sec, loki_query)
    if not logs:
        return {"logs_count": 0, "combined": "", "llm_result": None}

    combined = "\n".join(logs)
    llm_result = await asyncio.to_thread(analyze_with_llm, combined)
    upload_result = None
    # if upload and isinstance(llm_result, dict) and not llm_result.get("error"):
    #     upload_result = await asyncio.to_thread(upload_to_pinecone_sync, llm_result)
    return {"llm_result": llm_result}


# ---- Pathway MCP schemas ----
class FetchLogSchema(pw.Schema):
    start_iso: str
    window_sec: int
    loki_query: str


class SummarizeSchema(pw.Schema):
    combined_logs: str


class ProcessWindowSchema(pw.Schema):
    start_iso: str
    window_sec: int
    loki_query: str
    upload: bool


class AlertProcessingSchema(pw.Schema):
    alert_data: str


# ---- UDFs (async executor) ----
@pw.udf
def udf_generate_alert_message(alert_data_str: str):
    try:
        alert_data = json.loads(alert_data_str)
        return generate_alert_message_sync(alert_data)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "message": "Alert data is not valid JSON"}
    except Exception as e:
        return {"error": "generation_failed", "message": str(e)}


class AlertMessageTool(McpServable):
    def run(self, table: pw.Table) -> pw.Table:
        t = table.with_columns(
            result=udf_generate_alert_message(pw.this.alert_data)
        )
        return t.select(human_alert_message=pw.this.result)

    def register_mcp(self, server: McpServer):
        server.tool(
            name="generate_human_alert",
            request_handler=self.run,
            schema=AlertProcessingSchema,
        )


@pw.udf(executor=pw.udfs.fully_async_executor())
async def _udf_fetch_logs(start_iso: str, window_sec: int, loki_query: str):
    try:
        result = await fetch_logs(start_iso, window_sec, loki_query)
        return result
    except Exception as e:
        return {"error": "fetch_failed", "message": str(e)}


@pw.udf(executor=pw.udfs.fully_async_executor())
async def _udf_analyze_with_llm(combined_logs):
    """
    Accept either a string or a list of strings.
    """
    try:
        if isinstance(combined_logs, list):
            combined = "\n".join(str(x) for x in combined_logs)
        else:
            combined = str(combined_logs)
        return analyze_with_llm(combined)
    except Exception as e:
        return {"error": "llm_failed",
                "message": str(e)}


# ---- MCP tools (use UDFs + await_futures) ----
class FetchLogsTool(McpServable):
    def run(self, table: pw.Table) -> pw.Table:
        t = table.with_columns(
            logs_future=_udf_fetch_logs(
                pw.this.start_iso, pw.this.window_sec, pw.this.loki_query)
        ).await_futures()
        return t.select(result=pw.this.logs_future)

    def register_mcp(self, server: McpServer):
        server.tool(name="fetch_logs", request_handler=self.run,
                    schema=FetchLogSchema)


class SummarizeTool(McpServable):
    def run(self, table: pw.Table) -> pw.Table:
        t = table.with_columns(
            summary_future=_udf_analyze_with_llm(pw.this.combined_logs)
        ).await_futures()
        return t.select(result=pw.this.summary_future)

    def register_mcp(self, server: McpServer):
        server.tool(name="summarize_logs",
                    request_handler=self.run, schema=SummarizeSchema)


# Central service that runs all other fns
class ProcessWindowTool(McpServable):
    def run(self, table: pw.Table) -> pw.Table:
        t1 = table.with_columns(
            logs_future=_udf_fetch_logs(
                pw.this.start_iso, pw.this.window_sec, pw.this.loki_query)
        ).await_futures()

        t2 = t1.with_columns(
            combined_future=_udf_analyze_with_llm(pw.this.logs_future)
        ).await_futures()

        return t2.select(result=pw.this.combined_future)

    def register_mcp(self, server: McpServer):
        server.tool(name="process_window", request_handler=self.run,
                    schema=ProcessWindowSchema)


def start_mcp_server(host: str = "localhost", port: int = 8123, serve=None):
    if serve is None:
        # Tools to add
        serve = [FetchLogsTool(), SummarizeTool(), ProcessWindowTool()]

        for t in serve:
            print("Registering tool:", type(t).__name__)

    if PATHWAY_LICENSE_KEY:
        try:
            from pathway.internals.config import get_pathway_config
            cfg = get_pathway_config()
            if not getattr(cfg, "license_key", None):
                cfg.license_key = PATHWAY_LICENSE_KEY
        except Exception:
            os.environ["PW_LICENSE_KEY"] = PATHWAY_LICENSE_KEY

    mcp = PathwayMcp(
        name="Ambient MCP Server",
        transport="streamable-http",
        host=host,
        port=port,
        serve=serve,
    )
    return mcp


app = FastAPI()


@app.post("/grafana/alert")
async def receive_alert(request: Request):
    data = await request.json()
    print("Received alert:", data)

    # Extract timestamp from first alert
    try:
        starts_at = data["alerts"][0]["startsAt"]
    except:
        return {"error": "Invalid alert payload - missing startsAt"}

    print("Starttime:", starts_at)
    # Call your existing processing pipeline
    result = await fetch_and_summarize(
        start_iso=starts_at,
        window_sec=5,
        loki_query='{app_id!=""}',
        upload=True
    )

    print("Pipeline result:", result)

    await broadcast_to_frontend({
        "type": "alert_result",
        "result": result["llm_result"],
    })
    return {"status": "ok"}

connected_clients = []


async def broadcast_to_frontend(message: dict):
    to_remove = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except:
            to_remove.append(ws)

    for ws in to_remove:
        connected_clients.remove(ws)


@app.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "alert-message-generator",
        "timestamp": datetime.utcnow().isoformat(),
        "llm_available": bool(OPENAI_KEY)
    }

# ---- dual-mode entrypoint ----
if __name__ == "__main__":
    import threading

    # Start Pathway MCP in background thread
    def run_pathway():
        mcp_server = start_mcp_server()
        pw.run()

    threading.Thread(target=run_pathway, daemon=True).start()
    # threading.Thread(target=run_rmq, daemon=True).start()
    # Start FastAPI for receiving alerts
    uvicorn.run(app, host="0.0.0.0", port=8124)
