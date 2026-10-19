from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import ConflictError, NotFoundError, register_exception_handlers


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def not_found() -> None:
        raise NotFoundError("record", 42)

    @app.get("/conflict")
    async def conflict() -> None:
        raise ConflictError("username already exists")

    @app.get("/http-error")
    async def http_error() -> None:
        raise HTTPException(status_code=401, detail="token expired")

    @app.get("/validated")
    async def validated(size: int) -> dict[str, int]:
        return {"size": size}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    return app


def make_client() -> AsyncClient:
    # 500 handler 回應後 Starlette 仍會把例外往外拋，測試要關掉 raise_app_exceptions 才看得到回應
    transport = ASGITransport(app=build_app(), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_app_error_uses_unified_format() -> None:
    async with make_client() as c:
        resp = await c.get("/not-found")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "not_found", "message": "record 42 not found", "details": None}
    }


async def test_conflict_error_returns_409() -> None:
    async with make_client() as c:
        resp = await c.get("/conflict")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_http_exception_uses_unified_format() -> None:
    async with make_client() as c:
        resp = await c.get("/http-error")
    assert resp.status_code == 401
    assert resp.json()["error"] == {
        "code": "unauthorized",
        "message": "token expired",
        "details": None,
    }


async def test_unknown_route_uses_unified_format() -> None:
    async with make_client() as c:
        resp = await c.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_validation_error_uses_unified_format() -> None:
    async with make_client() as c:
        resp = await c.get("/validated", params={"size": "abc"})
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["query", "size"]


async def test_unexpected_error_returns_500_without_leaking_details() -> None:
    async with make_client() as c:
        resp = await c.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "secret" not in resp.text
