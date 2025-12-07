import asyncio
import re
import httpx
# inputs json and automatically converts to python dict
from urllib.parse import urlparse
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from log_config.log_config import get_logger
import os
import base64
import time
import websockets
from urllib.parse import urlencode
import json
import datetime
import dotenv
from aiokafka import AIOKafkaConsumer
# from api.models import Enriched  This happens because
# your WebSocket consumer imports Django models (Enriched) at module import time, 
# before Django apps are initialized during ASGI startup.
from channels.db import database_sync_to_async
logger = get_logger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '..', '..', '.env')
dotenv.load_dotenv(dotenv_path=dotenv_path)


class MetricConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()

        self.polling_tasks = {}
        self.http_client = httpx.AsyncClient()
        self.instance_id = os.getenv("PROMETHEUS_INSTANCE_ID")
        logger.info(f"Instance ID: {self.instance_id}")
        self.access_token = os.getenv("GRAFANA_CLOUD_ACCESS_TOKEN")
        self.api_endpoint = os.getenv("PROMETHEUS_ENDPOINT")
        self.auth_string = f"{self.instance_id}:{self.access_token}"

        self.auth_header = {
            "Authorization": "Basic " + base64.
            b64encode(self.auth_string.encode()).decode("utf-8")
        }

        logger.info("Metrics Websocket Connected")

    async def disconnect(
        self,
        close_code
    ):
        await self.stop_all_polling()
        await self.http_client.aclose()
        logger.info("Metrics Websocket Disconnected")

    async def receive_json(self, content):
        logger.debug("Received Message: ", content)
        action = content.get("action")

        if action == "subscribe":
            await self.handle_subscribe(content)
        elif (action == "unsubscribe"):
            await self.handle_unsubscribe(content)
        elif (action == "fetch_static"):
            await self.handle_static_fetch(content)
        else:
            logger.warning("Unknown action encountered")
            await self.send_json({"error": "Unknown Action detected"})

    async def handle_subscribe(
        self,
        content
    ):
        service_name = content.get("service_name")
        metric = content.get("metric")

        if metric in self.polling_tasks:
            logger.warning(f"Already polling {metric}")
            return
        task = asyncio.create_task(self.poll_metric(service_name, metric))
        self.polling_tasks[metric] = task
        logger.info(f"Subscribed to {service_name}/{metric}")

    async def handle_unsubscribe(
        self,
        content
    ):
        metric = content.get("metric")
        if metric and metric in self.polling_tasks:
            task = self.polling_tasks.pop(metric)
            task.cancel()
            try:
                await task  # to wait so that it stops correctly
            except asyncio.CancelledError:
                logger.exception("Error in unsubscribing metrics")
                pass
        else:
            logger.warning(f"Trying to unsubscribe not active metric {metric}")

    async def stop_all_polling(self):
        logger.info("Stopping all polling tasks...")
        for metric, task in list(self.polling_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.exception("Error in unsubscribing metrics")
                pass
            logger.debug(f"Cancelled polling task for {metric}")
        self.polling_tasks.clear()

    async def poll_metric(
        self,
        service_name,
        metric
    ):
        logger.info(f"Polling started for {service_name}/{metric}")
        while True:
            try:
                data = await self.fetch_metric_data(
                    service_name,
                    metric
                )
                await self.send_json({
                    "type": "metric",
                    "mode": "realtime",
                    "metric": metric,
                    "data": data
                })
                logger.debug(f"Sent data for {metric}")
                await asyncio.sleep(5)  # wait for 5 sec to start next polling

            except asyncio.CancelledError:
                logger.error(f"Polling stopped for {metric}")
                break
            except Exception as e:
                logger.error(f"Error in polling {metric} {e}")
                await asyncio.sleep(5)

    async def fetch_metric_data(
        self,
        service_name,
        metric
    ):
        query = f'{metric}{{service_name="{service_name}"}}'

        params = {
            "query": query,
        }
        # Full API URL
        complete_url = f"{self.api_endpoint}/api/v1/query"
        try:
            response = await self.http_client.get(
                complete_url, headers=self.auth_header, params=params)
            response.raise_for_status()
            data = response.json().get("data", {})
            logger.info(f"Fetched realtime data for {metric}")
            cleaned_data = self.clean_stream_metric_data(data)
            return cleaned_data
        except Exception as e:
            logger.exception(f"Error in fetching in realtime for {metric} {e}")

    async def handle_static_fetch(self, content):
        service_name = content.get("service_name")
        metric = content.get("metric")
        # should in secs format and coming correctly
        start = content.get("start")
        end = content.get("end")

        logger.debug(
            f"Static Fetch Params:{service_name} {metric} {start} {end}")

        if end is None:
            end = int(time.time())

        if start is None:
            start = end - 60 * 60  # default one hour before to present

        query = f'{metric}{{service_name="{service_name}"}}'
        # step =  self.appropriate_step_value(start,end)
        step = "30s"
        params = {
            "query": query,
            "start": start,
            "end": end,
            "step": step
        }
        complete_url = f"{self.api_endpoint}/api/v1/query_range"
        try:
            response = await self.http_client.get(
                complete_url, headers=self.auth_header, params=params)

            logger.info(response)
            response.raise_for_status()
            data = response.json().get("data", {})
            logger.info(f"Data for Metric {data}")  # for checking
            cleaned_data = self.clean_static_metric_data(data)
            logger.info(f"Fetched static data for {metric}")
            await self.send_json({
                "type": "metric_data",
                "mode": "static",
                "metric": metric,
                "data": cleaned_data
            })
        except Exception as e:
            logger.exception(
                f"Error in fetching in static mode for {metric} {e}")

    def clean_stream_metric_data(
        self,
        data_json
    ):
        logger.debug(f"Cleaning Data: {data_json}")
        result = []
        for item in data_json.get("result", []):
            metric_info = item.get("metric", {})
            service_name = metric_info.get("service_name")
            value_info = item.get("value", [])

            if service_name and len(value_info) == 2:
                try:
                    timestamp = datetime.datetime.fromtimestamp(
                        float(value_info[0])).isoformat()
                    value_int = int(float(value_info[1]))
                    result.append({
                        "service_name": service_name,
                        "timestamp": timestamp,
                        "value": value_int
                    })
                except (ValueError, TypeError):
                    continue

        return result

    def clean_static_metric_data(self, data_json):
        logger.debug(f"Cleaning Data: {data_json}")
        result = []

        for item in data_json.get("result", []):
            metric_info = item.get("metric", {})
            service_name = metric_info.get("service_name")
            values_list = item.get("values", [])

            if service_name and values_list:
                service_data = {"service_name": service_name, "values": []}

                for val in values_list:
                    if len(val) == 2:
                        try:
                            timestamp = datetime.datetime.fromtimestamp(
                                float(val[0])).isoformat()
                            value_int = int(float(val[1]))
                            service_data["values"].append({
                                "timestamp": timestamp,
                                "value": value_int
                            })
                        except (ValueError, TypeError):
                            continue

                # Sort values by timestamp to ensure chronological order
                service_data["values"].sort(key=lambda x: x["timestamp"])
                result.append(service_data)

        return result


class LogsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.stream_task = None
        self.http_client = httpx.AsyncClient()
        self.instance_id = os.getenv("LOKI_INSTANCE_ID")
        self.access_token = os.getenv("GRAFANA_CLOUD_ACCESS_TOKEN")
        self.api_endpoint = os.getenv("LOKI_ENDPOINT")
        self.auth_string = f"{self.instance_id}:{self.access_token}"

        self.auth_header = {
            "Authorization": "Basic " + base64.b64encode(self.auth_string.encode()).decode("utf-8")
        }

        logger.info("Logs Websocket Connected")

    async def disconnect(self, close_code):
        await self.http_client.aclose()
        await self.stop_stream()
        logger.info("Logs Websocket Disconnected")

    async def receive_json(self, content):
        service_name = content.get("service_name")
        start = content.get("start")  # should in nanosec format
        end = content.get("end")
        logger.info(f"Service with start time {service_name} {start}")
        await self.stop_stream()

        if (start or end):
            data = await self.fetch_static_logs(service_name, start, end)
            logger.info(f"Static Log Data {service_name}")
            await self.send_json({
                "type": "log_data",
                "mode": "static",
                "service": service_name,
                "data": data
            })
            return

        self.stream_task = asyncio.create_task(
            self.stream_realtime_logs(service_name))

    async def fetch_static_logs(
        self,
        service_name,
        start,
        end
    ):
        try:
            start = int(start)
        except (TypeError, ValueError):
            start = None

        try:
            end = int(end)
        except (TypeError, ValueError):
            end = None

        if end is None:
            end = time.time_ns()

        if start is None:
            start = end - (24 * 60 * 60 * 1_000_000_000)

        step = self.compute_step(start, end)

        # Default limit is 100

        query = f'{{service_name="{service_name}"}}'
        logger.info(f"start and end time {start} {end}")
        params = {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
            "limit": 500
        }

        complete_url = f"{self.api_endpoint}/loki/api/v1/query_range"

        try:
            response = await self.http_client.get(complete_url, headers=self.auth_header, params=params)
            logger.info(response)
            response.raise_for_status()
            data = response.json().get("data", {})
            # logger.info(f"Logs Data: {data}")  # for checking
            cleaned_data = self.clean_static_logs(data)
            logger.info(f"Fetched static data for {service_name}")

            if service_name == "fraud_detection_frontend":
                parsed = self.parse_frontend_logs(cleaned_data)
                return parsed

            return cleaned_data
        except Exception as e:
            logger.exception(
                f"Error in fetching logs in static mode for {service_name}")
            return {"error": f"Error in fetching static logs {e}"}

    async def stream_realtime_logs(
        self,
        service_name
    ):
        complete_url = "wss://logs-prod-028.grafana.net/loki/api/v1/tail"
        query = f'{{service_name="{service_name}"}}'
        start = str(time.time_ns())
        logger.debug(f"Start time {start}")
        params = {
            "query": query,
            "start": start,

        }
        encoded_url = f"{complete_url}?{urlencode(params)}"

        logger.info("Starting to stream realtime logs")

        logger.debug(self.instance_id)
        try:
            async with websockets.connect(
                encoded_url,
                additional_headers=self.auth_header
            ) as loki_ws:
                async for log_message in loki_ws:
                    try:
                        # logger.info(f"log_message {log_message}")
                        log_json = json.loads(log_message)
                        # logger.info(f"Realtime Logs {service_name} {log_json}")
                        if service_name == "fraud_detection_frontend":
                            parsed = self.parse_realtime_logs(log_json)
                            parsed.sort(key=lambda x: x.get(
                                "timestamp", ""), reverse=True)
                            if parsed:
                                await self.send_json({
                                    "type": "log_data",
                                    "mode": "realtime",
                                    "service": service_name,
                                    "data": parsed
                                })
                            continue

                        streams = log_json.get("streams", [])

                        for stream in streams:
                            stream["values"].sort(
                                key=lambda x: int(x[0]), reverse=True)
                        await self.send_json({
                            "type": "log_data",
                            "mode": "realtime",
                            "service": service_name,
                            "data": streams
                        })

                    except Exception as e:
                        logger.exception(f"Error in parsing json: {e}")
        except asyncio.CancelledError:
            logger.exception("Cancelling Log streaming")
        except Exception as e:
            logger.exception(f"Log Streaming Error: {e}")

    async def stop_stream(self):
        if (self.stream_task):
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass
            self.stream_task = None

        logger.info("Streaming Logs Ended")

    def clean_static_logs(self, data_json):
        logger.debug("Cleaning Stream Logs: {data_json}")

        result = {}

        for item in data_json.get("result", []):
            stream_info = item.get("stream", {})
            values_list = item.get("values", [])

            otel_service_name = stream_info.get("otelServiceName")
            service_name = stream_info.get("service_name")
            severity_text = stream_info.get("severity_text")
            key = (otel_service_name, service_name)

            if key not in result:
                result[key] = {
                    "otelServiceName": otel_service_name,
                    "service_name": service_name,
                    "values": []
                }
            for val in values_list:
                if len(val) == 2:
                    try:
                        epoch_ns = int(val[0])
                        timestamp = datetime.datetime.fromtimestamp(
                            epoch_ns / 1_000_000_000).isoformat()
                        log_message = val[1]

                        result[key]["values"].append({
                            "timestamp": timestamp,
                            "epoch_ns": epoch_ns,
                            "severity_text": severity_text,
                            "log": log_message
                        })
                    except (ValueError, TypeError):
                        continue

        final_result = []
        for key, data in result.items():
            data["values"].sort(key=lambda x: x.get(
                "epoch_ns", 0), reverse=True)
            # Remove epoch_ns after sorting
            for val in data["values"]:
                val.pop("epoch_ns", None)
            final_result.append(data)

        return final_result

    def parse_frontend_logs(self, cleaned):
        global_ttfb, global_fcp, global_lcp, global_cls, global_inp = [], [], [], [], []

        pages = {}

        combined_logs = []
        api_calls = {}
        entries = []
        for stream in cleaned:
            for v in stream["values"]:
                entries.append(v)

        for entry in entries:
            log_line = entry["log"]
            ts = entry["timestamp"]

            if "event_name=faro.tracing.xml-http-request" in log_line:
                url = self._get(log_line, ["event_data_http.url"], None)
                duration_ns = self._get(
                    log_line, ["event_data_duration_ns"], None)
                logger.debug(f"Url:{url}")
                if url and duration_ns:
                    try:
                        endpoint = urlparse(url).path
                    except:
                        endpoint = url  # fallback
                    logger.debug(f"endpoint:{endpoint}")

                    try:
                        duration_ms = round(int(duration_ns) / 1_000_000, 2)
                    except:
                        duration_ms = None

                    if endpoint not in api_calls:
                        api_calls[endpoint] = []
                    api_calls[endpoint].append(duration_ms)

            # For webvitals global and per page
            if "type=web-vitals" in log_line:
                page_id = self._get(
                    log_line, ["page_id", "context_route", "page_url"], "unknown")
                ttfb = self._float(
                    log_line, ["ttfb", "value_ttfb", "time_to_first_byte"])
                fcp = self._float(log_line, ["fcp", "value_fcp"])
                lcp = self._float(log_line, ["lcp", "value_lcp"])
                cls1 = self._float(log_line, ["cls", "value_cls"])
                inp = self._float(log_line, ["inp", "value_inp"])

                global_ttfb.append(ttfb)
                global_fcp.append(fcp)
                global_lcp.append(lcp)
                global_cls.append(cls1)
                global_inp.append(inp)

                if page_id not in pages:
                    pages[page_id] = {
                        "ttfb": [], "fcp": [], "lcp": [], "cls": [], "inp": [], "errors": 0
                    }

                pages[page_id]["ttfb"].append(ttfb)
                pages[page_id]["fcp"].append(fcp)
                pages[page_id]["lcp"].append(lcp)
                pages[page_id]["cls"].append(cls1)
                pages[page_id]["inp"].append(inp)

            # JS error ke liye
            if "kind=exception" in log_line:
                message = self._get(log_line, ["value", "message"])
                route = self._get(
                    log_line, ["page_id", "context_route", "page_url"], "unknown")

                combined_logs.append({
                    "timestamp": ts,
                    "route": route,
                    "level": "error",
                    "message": message,
                })

                if route not in pages:
                    pages[route] = {"ttfb": [], "fcp": [],
                                    "lcp": [], "cls": [], "inp": [], "errors": 0}

                pages[route]["errors"] += 1

            if "kind=log" in log_line:
                message = self._get(log_line, ["message"], "")
                add_msg = self._get(
                    log_line, ["context_additional_message"], "")
                level = self._get(log_line, ["context_level"], "info")
                route = self._get(
                    log_line, ["context_route", "page_id", "page_url"], "unknown")

                combined_logs.append({
                    "timestamp": ts,
                    "route": route,
                    "level": level,
                    "message": message+add_msg,
                })

                if level.lower() == "error":
                    if route not in pages:
                        pages[route] = {"ttfb": [], "fcp": [], "lcp": [
                        ], "cls": [], "inp": [], "errors": 0}
                    pages[route]["errors"] += 1

        # Global Web Vitals
        global_web_vitals = {
            "ttfb": self._avg(global_ttfb),
            "fcp":  self._avg(global_fcp),
            "lcp":  self._avg(global_lcp),
            "cls":  self._avg(global_cls),
            "inp":  self._avg(global_inp),
        }

        page_performance = []
        for page_id, d in pages.items():
            page_performance.append({
                "page_id": page_id,
                "avg_ttfb": self._avg(d["ttfb"]),
                "avg_fcp":  self._avg(d["fcp"]),
                "avg_lcp":  self._avg(d["lcp"]),
                "avg_cls":  self._avg(d["cls"]),
                "avg_inp":  self._avg(d["inp"]),
                "error_count": d["errors"]
            })

        page_performance.sort(key=lambda x: x["page_id"])

        api_latency_list = []

        for endpoint, durations in api_calls.items():
            durations_sorted = sorted(durations)

            api_latency_list.append({
                "endpoint": endpoint,
                "calls": len(durations),
                "p50": self.percentile(durations_sorted, 0.5),
                "p90": self.percentile(durations_sorted, 0.90),
                "p99": self.percentile(durations_sorted, 0.99)
            })

        return {
            "overall_web_vitals": global_web_vitals,
            "page_performance": page_performance,
            "api_latency": api_latency_list,
            "logs": combined_logs
        }

    def percentile(self, arr, pct):
        if not arr:
            return 0

        k = int(len(arr)*pct)
        return arr[min(k, len(arr)-1)]

    def parse_realtime_logs(self, msg_json):
        streams = msg_json.get("streams", [])
        logs = []

        for stream in streams:
            for ts_ns, log_line in stream.get("values", []):

                # ts=self._get(log_line,["timestamp"])
                ts = datetime.datetime.fromtimestamp(
                    int(ts_ns)/1_000_000_000).isoformat()

                if "kind=log" in log_line:
                    logs.append({
                        "timestamp": ts,
                        "route": self._get(log_line, ["context_route", "page_id", "page_url"], "unknown"),
                        "level": self._get(log_line, ["context_level"], "info"),
                        "message": self._get(log_line, ["message"], "") + self._get(log_line, ["context_additional_message"], ""),
                    })

                elif "kind=exception" in log_line:
                    logs.append({
                        "timestamp": ts,
                        "route": self._get(log_line, ["page_id", "context_route", "page_url"], "unknown"),
                        "level": "error",
                        "message": self._get(log_line, ["value", "message"], ""),
                    })
        return logs

    def _extract(self, log, key):
        pattern = rf'{key}="([^"\\]*(?:\\.[^"\\]*)*)"|{key}=([^\s]+)'
        m = re.search(pattern, log)
        if not m:
            return None
        return m.group(1) or m.group(2)

    def _get(self, log, keys, default=None):
        for k in keys:
            v = self._extract(log, k)
            if v:
                return v
        return default

    def _float(self, log, keys, default=None):
        for k in keys:
            v = self._extract(log, k)
            if v:
                try:
                    return float(v)

                except:
                    pass
        return default

    def _avg(self, arr):
        logger.debug(f"Value to be avg:{arr}")
        arr = [v for v in arr if v is not None]

        if arr is None:
            return 0.0
        if (len(arr) == 0):
            return 0
        return round(sum(arr) / len(arr), 3)

    def compute_step(self, start_ns, end_ns):
        dur_ns = end_ns - start_ns
        dur_sec = dur_ns / 1_000_000_000

        if dur_sec <= 60:
            return "1s"
        elif dur_sec <= 3600:
            return "10s"
        elif dur_sec <= 6 * 3600:
            return "30s"
        elif dur_sec <= 12 * 3600:
            return "60s"
        elif dur_sec <= 24 * 3600:
            return "120s"
        else:
            return "300s"


class TraceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.http_client = httpx.AsyncClient()
        self.instance_id = os.getenv("TEMPO_INSTANCE_ID")
        self.access_token = os.getenv("GRAFANA_CLOUD_ACCESS_TOKEN")
        self.api_endpoint = os.getenv("TEMPO_ENDPOINT")
        self.auth_string = f"{self.instance_id}:{self.access_token}"

        self.auth_header = {
            "Authorization": "Basic " + base64.
            b64encode(self.auth_string.encode()).decode("utf-8")
        }

        logger.info("Trace Websocket Connected")

    async def disconnect(
        self,
        close_code
    ):
        self.http_client.aclose()
        logger.info("Trace Websocket Disconnected")

    async def receive_json(self, content):
        try:
            result = await self.handle_trace_search_aggragate(content)
            await self.send_json(result)
        except Exception as e:
            logger.exception(f"Failed to fetch trace details: {e}")

    async def handle_trace_search_aggragate(self, content):
        service_name = content.get("service_name")
        min_duration = content.get("min_duration")  # in sec
        max_duration = content.get("max_duration")
        limit = content.get("limit")
        start = content.get("start")  # unix epoch seconds
        end = content.get("end")
        status = content.get("status")

        traces = await self.query_tempo(
            service_name, min_duration, max_duration,
            limit, start, end, status)
        logger.info(traces)

        aggregated_trace = await self.give_aggregate_results(
            traces, start, end, service_name)

        return aggregated_trace

    async def query_tempo(self, service_name, min_duration,
                          max_duration, limit, start, end, status):

        tags = []
        tags.append(f"service.name={service_name}")

        if status and status.lower() != "all":
            tags.append(f"status:{status.lower()}")
        tags_param = " ".join(tags)

        params = {}

        if tags_param:
            params["tags"] = tags_param
        if min_duration:
            params["minDuration"] = f"{int(min_duration)}ms"
        if max_duration:
            params["maxDuration"] = f"{int(max_duration)}ms"
        if start:
            params["start"] = int(start)
        if end:
            params["end"] = int(end)
        if limit:
            params["limit"] = int(limit)

        complete_url = f"{self.api_endpoint}/api/search"

        try:
            response = await self.http_client.get(
                complete_url, headers=self.auth_header, params=params)
            response.raise_for_status()
            logger.info(response.text)
            res_json = response.json()
            traces = res_json.get("traces", [])
            logger.info("Received Traces from Tempo")
            return traces
        except Exception as e:
            logger.exception(f"Cannot fetch trace details: {e}")

    async def give_aggregate_results(self, traces, start, end, service_name):
        if not traces:
            return {
                "type": "trace_data",
                "service_name": service_name,
                "summary": {
                    "total_traces": 0,
                    "avg_latency": 0,
                    "error_rate_percent": 0,
                    "p95_latency_ms": 0,
                    "time_window": {
                        "start": start,
                        "end": end
                    }
                },
                "traces": [],
            }

        duration = []
        for trace in traces:
            duration.append(trace.get("durationMs", 0))

        total_duration = len(duration)
        avg_latency = sum(duration) / total_duration
        # vo point jisse 95% values choti hai percentile
        p95_latency = sorted(duration)[int(0.95 * total_duration) - 1]
        summary = {
            "total_traces": total_duration,
            "avg_latency_ms": round(avg_latency, 2),
            "p95_latency_ms": round(p95_latency, 2),
            "time_window": {"start": start, "end": end},
        }

        return {
            "type": "trace_data",
            "service_name": service_name,
            "summary": summary,
            "traces": traces,
        }


class KafkaMLConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.kafka_broker = os.getenv("KAFKA_BROKER", "kafka:9093")
        self.kafka_topic = "ml_prediction"
        self.consumer_task = None
        self.consumer = None
        self.is_running = False
        logger.info(
            f"KafkaML Websocket Connected. Broker: {self.kafka_broker}")

    async def disconnect(self, close_code):
        logger.info("KafkaML Websocket Disconnected")
        await self.stop_consumer_task()

    async def receive_json(self, content):
        action = content.get("action")
        logger.debug(f"KafkaML received action: {action}")

        if action == "start_stream":
            await self.start_consumer_task()
        elif action == "stop_stream":
            await self.stop_consumer_task()
        else:
            logger.warning(f"Unknown action: {action}")
            await self.send_json(
                {"type": "error", "message": "Unknown action"})

    async def start_consumer_task(self):
        if self.consumer_task:
            logger.warning("Kafka consumer task already running")
            return

        try:
            logger.info(
                f"Initializing Kafka consumer for topic: {self.kafka_topic}")
            self.consumer = AIOKafkaConsumer(
                self.kafka_topic,
                bootstrap_servers=self.kafka_broker,
                group_id="ml_prediction_websocket_group",
                auto_offset_reset="latest",
                value_deserializer=lambda v: json.loads(v.decode('utf-8'))
            )

            await self.consumer.start()
            self.is_running = True
            self.consumer_task = asyncio.create_task(self.run_consumer())
            logger.info("Kafka consumer task started")

        except Exception as e:
            logger.exception("Failed to start Kafka consumer")
            await self.send_json({"type": "error", "message":
                                  f"Failed to start consumer: {str(e)}"})

    async def stop_consumer_task(self):
        if not self.consumer_task:
            logger.warning("No Kafka consumer task to stop")
            return

        self.is_running = False
        if self.consumer:
            await self.consumer.stop()

        try:
            self.consumer_task.cancel()
            await self.consumer_task
        except asyncio.CancelledError:
            logger.info("Kafka consumer task successfully cancelled")
        except Exception as e:
            logger.exception(f"Error during consumer task cleanup: {e}")

        self.consumer_task = None
        self.consumer = None
        logger.info("Kafka consumer task stopped")

    async def run_consumer(self):
        try:
            logger.info(f"Consuming from Kafka topic: {self.kafka_topic}")
            while self.is_running:
                result = await self.consumer.getmany(
                    timeout_ms=1000, max_records=10)

                if not self.is_running:
                    break

                for tp, messages in result.items():
                    for msg in messages:
                        if not self.is_running:
                            break

                        # logger.debug(f"Received from Kafka: {msg.value}")
                        try:
                            await self.send_json({
                                "type": "ml_prediction",
                                "data": msg.value
                            })
                        except Exception as send_e:
                            logger.error(
                                f"Failed to send message"
                                f"to websocket: {send_e}")
                    if not self.is_running:
                        break

        except asyncio.CancelledError:
            logger.info("Kafka consumer loop cancelled.")
        except Exception as e:
            logger.exception("Error in Kafka consumer loop")
            try:
                await self.send_json(
                    {"type": "error", "message":
                     f"Kafka consumer error: {str(e)}"})
            except Exception:
                pass
        finally:
            logger.info("Exiting Kafka consumer loop.")
            if self.consumer:
                await self.consumer.stop()


class AmbientAgentLogs(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.polling_tasks = {}
        self.stream_task = None
        self.http_client = httpx.AsyncClient()
        self.instance_id = os.getenv("LOKI_INSTANCE_ID")
        self.access_token = os.getenv("GRAFANA_CLOUD_ACCESS_TOKEN")
        self.api_endpoint = os.getenv("LOKI_ENDPOINT")
        self.auth_string = f"{self.instance_id}:{self.access_token}"

        self.auth_header = {
            "Authorization": "Basic " + base64.b64encode(
                self.auth_string.encode()).decode("utf-8")
        }
        logger.info("Ambient Agent Logs Websocket Connected")

    async def disconnect(
        self,
        close_code
    ):
        await self.http_client.aclose()
        logger.info("Ambient Agent Logs Websocket Disconnected")

    async def receive_json(self, content):
        service_name = content.get("service_name")

        if service_name in self.polling_tasks:
            logger.warning(f"Already polling {service_name}")
            return
        task = asyncio.create_task(self.poll_logs(service_name))
        self.polling_tasks[service_name] = task
        logger.info(f"Subscribed to {service_name}")

    async def poll_logs(self, service_name):
        logger.info(f"Polling started for {service_name}")
        while True:
            try:
                data = await self.fetch_static_logs(service_name)
                await self.send_json({

                    "service_name": service_name,
                    "data": data
                })
                logger.debug(f"Sent data for {service_name}")
                await asyncio.sleep(10)

            except asyncio.CancelledError:
                logger.error(f"Polling stopped for {service_name}")
                break
            except Exception as e:
                logger.error(f"Error in polling {service_name} {e}")
                await asyncio.sleep(10)

    async def fetch_static_logs(self, service_name):
        end = int(time.time())

        logger.info(f"End Time: {end}")
        start = end - 10

        query = f'{{service_name="{service_name}"}}'
        step = "1s"
        params = {
            "query": query,
            "start": start,
            "end": end,
            "step": step
        }
        logger.info(f"Fetch Static Logs Params: {params}")
        complete_url = f"{self.api_endpoint}/loki/api/v1/query_range"
        logger.info(f"Complete URL: {complete_url}")

        try:
            response = await self.http_client.get(
                complete_url, headers=self.auth_header, params=params)
            logger.info(f"Response: {response}")
            response.raise_for_status()
            data = response.json().get("data", {})
            # logger.info(f"Logs Data: {data}")
            cleaned_data = self.clean_static_logs(data)
            logger.info(f"Fetched static data for {service_name}")
            return cleaned_data
        except Exception as e:
            logger.exception(
                f"Error in fetching logs in static mode for {service_name}")
            return {"error": f"Error in fetching static logs {e}"}

    def clean_static_logs(self, data_json):
        logger.info(f"Cleaning Stream Logs: {data_json}")

        result = {}

        for item in data_json.get("result", []):
            stream_info = item.get("stream", {})
            values_list = item.get("values", [])

            otel_service_name = stream_info.get("otelServiceName")
            service_name = stream_info.get("service_name")
            severity_text = stream_info.get("severity_text")
            key = (otel_service_name, service_name)

            if key not in result:
                result[key] = {
                    "otelServiceName": otel_service_name,
                    "service_name": service_name,
                    "values": []
                }
            for val in values_list:
                if len(val) == 2:
                    try:
                        epoch_ns = int(val[0])
                        timestamp = datetime.datetime.fromtimestamp(
                            epoch_ns / 1_000_000_000).isoformat()
                        log_message = val[1]

                        result[key]["values"].append({
                            "timestamp": timestamp,
                            "severity_text": severity_text,
                            "log": log_message
                        })
                    except (ValueError, TypeError):
                        continue

        return list(result.values())


class TransactionTimeData(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.streaming = True

        # Spawn background streaming loop
        self.stream_task = asyncio.create_task(self.stream_transaction_time())

        logger.info("Transaction Time Websocket Connected")
        await self.send_json({"message": "Transaction Time Websocket Connected"})

    async def disconnect(self, close_code):
        self.streaming = False

        # Cancel background stream task cleanly
        if hasattr(self, "stream_task"):
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass

        logger.info("Transaction Time Websocket Disconnected")

    async def receive_json(self, content):
        action = content.get("action")

        if action == "stop_stream":
            self.streaming = False
            if hasattr(self, "stream_task"):
                self.stream_task.cancel()
            return

    async def stream_transaction_time(self):
        from api.models import Enriched

        before_time = 5  # seconds

        while self.streaming:
            now_ms = int(time.time() * 1000)

            ago_ms = now_ms - (4 * before_time * 1000)
            end_ms = now_ms - (3*before_time * 1000)

            count = await database_sync_to_async(
                lambda: Enriched.objects.filter(
                    time__gte=ago_ms, time__lte=end_ms).count()
            )()
            logger.info((f"Bucket is {ago_ms}-{end_ms} : COUNT:{count}"))
            logger.info((f"Sending time is {now_ms}"))

            await self.send_json({
                "type": "reatime_delta_data",
                "timestamp": now_ms,
                "delta": count
            })

            # safe sleep → allows instant cancellation
            try:
                await asyncio.sleep(before_time)
            except asyncio.CancelledError:
                break


class MLHealth(AsyncJsonWebsocketConsumer):

    async def connect(self):
        await self.accept()
        logger.info(f"[MLHealth] WebSocket connected: {self.channel_name}")

        await self.channel_layer.group_add("health_group", self.channel_name)
        logger.info(
            f"[MLHealth] Joined group 'health_group': {self.channel_name}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("health_group", self.channel_name)
        logger.info(
            f"[MLHealth] WebSocket disconnected: {self.channel_name}, code={close_code}")

    async def receive_json(self, content):
        logger.debug(f"[MLHealth] Received message from client: {content}")
        # No-op for now

    async def send_update(self, event):
        logger.info(f"[MLHealth] Sending update to client: {event}")

        try:
            await self.send_json(event["data"])
        except Exception as e:
            logger.error(f"[MLHealth] Failed to send update: {e}")
