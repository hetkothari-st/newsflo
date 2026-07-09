from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.manager import manager

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # The client never needs to send anything; this just parks the
        # coroutine so a client-initiated close raises WebSocketDisconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
