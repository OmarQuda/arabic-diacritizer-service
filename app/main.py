import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import require_key
from app.config import ROOT, Settings, load_settings
from app.corrections import Corrections
from app.errors import ServiceError
from app.logging import logger
from app.providers import Provider
from app.validation import validate


class DiacritizeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    request_id: str | None = Field(default=None, max_length=128)
    simulate: Literal["added_word", "removed_word", "translation", "markdown"] | None = None


class CorrectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, max_length=128)
    input: str = Field(min_length=1)
    model_output: str
    corrected: str
    note: str | None = Field(default=None, max_length=2000)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    cfg = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not cfg.service_key:
            raise RuntimeError("SERVICE_KEY must be configured in this repo's .env")
        if not cfg.fake and (not cfg.primary.api_key or not cfg.primary.model):
            raise RuntimeError("Configure LLM_API_KEY and LLM_MODEL")
        if not cfg.fake and cfg.fallback and (not cfg.fallback.api_key or not cfg.fallback.model):
            raise RuntimeError("Configure FALLBACK_API_KEY and FALLBACK_MODEL, or clear FALLBACK_BASE_URL")
        app.state.corrections.initialize()
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            app.state.provider = Provider(cfg, client)
            yield

    app = FastAPI(title="Arabic diacritizer demo", lifespan=lifespan)
    app.state.settings = cfg
    app.state.corrections = Corrections(cfg.db_path)

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        transport_id = str(uuid.uuid4())
        request.state.request_id = transport_id
        start = time.perf_counter()
        response = await call_next(request)
        # Caller IDs can contain arbitrary Unicode. HTTP header values cannot.
        caller_id = request.state.request_id
        response.headers["X-Request-ID"] = caller_id if caller_id.isascii() and caller_id.isprintable() else transport_id
        logger.info("request", extra={"fields": {
            "request_id": request.state.request_id, "method": request.method,
            "path": request.url.path, "status": response.status_code,
            "latency_ms": round((time.perf_counter() - start) * 1000),
        }})
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo Pydantic's raw input (which can contain source text).
        if request.url.path == "/v1/corrections":
            return JSONResponse({"error": "invalid_correction", "reason": "base_text_mismatch"}, status_code=422)
        return JSONResponse({"error": "validation_failed", "reason": "empty", "attempts": 0,
                             "detail": "Invalid request body or parameters."}, status_code=422)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        return {"status": "ready", "fake_provider": cfg.fake,
                "provider": "fake" if cfg.fake else cfg.primary.name,
                "model": "dictionary-v1" if cfg.fake else cfg.primary.model}

    def check_length(*texts: str):
        if any(len(text) > cfg.max_chars for text in texts):
            raise ServiceError(413, "text_too_long", max_chars=cfg.max_chars)

    @app.post("/v1/diacritize", dependencies=[Depends(require_key)])
    async def diacritize(body: DiacritizeBody, request: Request):
        check_length(body.text)
        request.state.request_id = body.request_id or request.state.request_id
        if not body.text.strip():
            raise ServiceError(422, "validation_failed", reason="empty", attempts=0, detail="Input text is empty.")
        start = time.perf_counter()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        for attempt in (1, 2):
            result = await app.state.provider.complete(body.text, repair=attempt == 2, simulate=body.simulate)
            usage["prompt_tokens"] += result.prompt_tokens
            usage["completion_tokens"] += result.completion_tokens
            usage["cost_usd"] += result.cost_usd
            verdict = validate(body.text, result.text)
            fields = {"request_id": request.state.request_id, "attempt": attempt,
                      "provider": result.provider, "model": result.model, "valid": verdict.valid,
                      "reason": verdict.reason, "prompt_tokens": result.prompt_tokens,
                      "completion_tokens": result.completion_tokens, "cost_usd": result.cost_usd}
            if cfg.log_text:
                fields.update(input=body.text, output=result.text)
            logger.info("completion", extra={"fields": fields})
            if verdict.valid:
                return {"request_id": request.state.request_id, "input": body.text, "output": result.text,
                        "valid": True, "attempts": attempt, "provider": result.provider, "model": result.model,
                        "usage": usage, "latency_ms": round((time.perf_counter() - start) * 1000)}
        raise ServiceError(422, "validation_failed", reason=verdict.reason, attempts=2, detail=verdict.detail)

    @app.post("/v1/corrections", status_code=201, dependencies=[Depends(require_key)])
    def correction(body: CorrectionBody, request: Request):
        check_length(body.input, body.model_output, body.corrected)
        request.state.request_id = body.request_id or request.state.request_id
        return app.state.corrections.store(request_id=request.state.request_id, input=body.input,
                                          model_output=body.model_output, corrected=body.corrected, note=body.note or "")

    @app.get("/v1/corrections", dependencies=[Depends(require_key)])
    def list_corrections(limit: int = Query(default=20, ge=1, le=100)):
        return {"items": app.state.corrections.list(limit)}

    return app


app = create_app()
