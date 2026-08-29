from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class Violation(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    correlation_id: str
    retryable: bool = False
    violations: list[Violation] = Field(default_factory=list)


class ApiProblem(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        super().__init__(detail)


def problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unavailable")


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def handle_api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(
            Problem(
                type=f"https://ev2.local/problems/{exc.code.lower().replace('_', '-')}",
                title=exc.title,
                status=exc.status,
                code=exc.code,
                detail=exc.detail,
                correlation_id=_correlation_id(request),
            )
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        violations = [
            Violation(
                field=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return problem_response(
            Problem(
                type="https://ev2.local/problems/request-validation",
                title="Request validation failed",
                status=422,
                code="REQUEST_VALIDATION_FAILED",
                detail="One or more request fields are invalid.",
                correlation_id=_correlation_id(request),
                violations=violations,
            )
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return problem_response(
            Problem(
                title="Resource not found" if exc.status_code == 404 else "Request failed",
                status=exc.status_code,
                code=code,
                detail=str(exc.detail),
                correlation_id=_correlation_id(request),
            )
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, _exc: Exception) -> JSONResponse:
        return problem_response(
            Problem(
                title="Internal server error",
                status=500,
                code="INTERNAL_ERROR",
                detail="The request could not be completed.",
                correlation_id=_correlation_id(request),
                retryable=True,
            )
        )
