from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from alinea_contracts.errors import AlineaError
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db.database import init_db
from app.jobs.runner import initialize_dispatcher, shutdown_dispatcher
from app.routers import documents, inspections, projects, repairs, resources, rules
from app.services.common import isoformat, utc_now, validated_request_id
from app.services.jobs import recover_jobs
from app.services.maintenance import start_maintenance

logger = logging.getLogger("alinea.api")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or validated_request_id(None)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
                "retryable": retryable,
                "details": details or {},
            }
        },
        headers={"X-Request-ID": _request_id(request)},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_db(settings.database_url)
        initialize_dispatcher(settings)
        recover_jobs(settings)
        maintenance_task = start_maintenance(settings)
        try:
            yield
        finally:
            maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task
            shutdown_dispatcher()

    application = FastAPI(
        title="Alinea API",
        version="0.2.0",
        description="Verifiable DOCX formatting inspection and approved repair",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Request-ID",
        ],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        request.state.request_id = validated_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(AlineaError)
    async def alinea_error_handler(request: Request, exc: AlineaError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        codes = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            413: "FILE_TOO_LARGE",
            415: "UNSUPPORTED_FILE_FORMAT",
            422: "VALIDATION_ERROR",
            429: "TOO_MANY_JOBS",
        }
        messages = {
            400: "请求内容有误，请检查后重试。",
            401: "访问凭证不存在或已失效，请重新验证。",
            403: "当前操作没有访问权限。",
            404: "请求的内容不存在或已过期。",
            405: "当前接口不支持此操作。",
            409: "当前状态已变化，请刷新后重试。",
            413: "文件超过大小限制，请选择较小的文件。",
            415: "文件格式不受支持，请更换文件。",
            422: "提交内容不符合要求，请检查后重试。",
            429: "操作过于频繁，请稍后重试。",
        }
        return _error_response(
            request,
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "HTTP_ERROR"),
            message=messages.get(exc.status_code, "请求未能完成，请稍后重试。"),
            retryable=exc.status_code >= 500,
        )

    async def validation_handler(request: Request, exc: Exception) -> JSONResponse:
        raw_errors = (
            exc.errors() if isinstance(exc, (RequestValidationError, ValidationError)) else []
        )
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", "Invalid value"),
                "type": error.get("type", "validation_error"),
            }
            for error in raw_errors
        ]
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="提交内容未通过校验，请检查后重试。",
            details={"errors": errors},
        )

    application.add_exception_handler(RequestValidationError, validation_handler)
    application.add_exception_handler(ValidationError, validation_handler)

    @application.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error request_id=%s", _request_id(request), exc_info=exc)
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="服务器暂时无法完成请求，请稍后重试。",
            retryable=True,
        )

    @application.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": "0.2.0",
            "job_mode": "rq" if settings.redis_url else "local",
            "time": isoformat(utc_now()),
        }

    application.include_router(projects.router, prefix="/api/v1")
    application.include_router(documents.router, prefix="/api/v1")
    application.include_router(rules.router, prefix="/api/v1")
    application.include_router(inspections.router, prefix="/api/v1")
    application.include_router(repairs.router, prefix="/api/v1")
    application.include_router(resources.router, prefix="/api/v1")
    return application


app = create_app()
