from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.deps import authenticate_token
from app.db.session import SessionLocal

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/metrics")
async def metrics_stream(websocket: WebSocket, token: str | None = None) -> None:
    """即時資料推送。瀏覽器 WebSocket 無法帶 header，JWT 以 query 參數 `token` 傳入。"""
    # 先 accept 再驗證：未 accept 就 close，伺服器只會回 HTTP 403，瀏覽器看不到 1008 與原因
    await websocket.accept()
    async with SessionLocal() as session:
        user = await authenticate_token(session, token)
    if user is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="invalid or expired token"
        )
        return

    manager = websocket.app.state.ws_manager
    manager.add(websocket)
    try:
        # 只推不收；持續 receive 是為了偵測用戶端斷線
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(websocket)
