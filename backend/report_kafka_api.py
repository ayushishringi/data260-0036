"""HW8 FastAPI wrapper: HTTP in, Kafka request/response out. Runs on PORT_BASE 8036.

POST /api/kafka/reports            -> CREATE_REPORT over Kafka
GET  /api/kafka/reports/{report_id} -> GET_REPORT over Kafka
POST /api/kafka/requests           -> any operation (used to show the Unknown operation error)

An optional X-Correlation-ID header is used unchanged; otherwise the API creates one.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from src.kafka_common import PORT_BASE, log, wait_for_kafka
from src.kafka_rpc import ReportRpcClient
from src.report_service import CREATE_OPERATION, GET_OPERATION

COMPONENT = "api"
state: dict[str, ReportRpcClient] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    wait_for_kafka()
    state["client"] = ReportRpcClient(component=COMPONENT)
    log(COMPONENT, f"FastAPI service started at http://127.0.0.1:{PORT_BASE}")
    yield
    state["client"].close()


app = FastAPI(title="s0036 HW8 report service over Kafka", lifespan=lifespan)


class RawRequest(BaseModel):
    operation: str
    data: Any = None


async def call(operation: str, data: Any, correlation_id: str | None) -> dict[str, Any]:
    client = state["client"]
    cid = correlation_id or client.new_correlation_id()
    log(COMPONENT, "HTTP request received", correlation_id=cid, operation=operation)
    response = await run_in_threadpool(client.request, operation, data, cid)
    log(COMPONENT, "HTTP response returned to caller", correlation_id=cid, success=response.get("success"))
    return response


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "port": PORT_BASE, "service": "s0036 report service over Kafka"}


@app.post("/api/kafka/reports")
async def create_report(data: dict[str, Any], x_correlation_id: str | None = Header(default=None)) -> dict:
    return await call(CREATE_OPERATION, data, x_correlation_id)


@app.get("/api/kafka/reports/{report_id}")
async def get_report(report_id: str, x_correlation_id: str | None = Header(default=None)) -> dict:
    return await call(GET_OPERATION, {"report_id": report_id}, x_correlation_id)


@app.post("/api/kafka/requests")
async def raw_request(body: RawRequest, x_correlation_id: str | None = Header(default=None)) -> dict:
    return await call(body.operation, body.data, x_correlation_id)
