import asyncio

from fastapi import WebSocket


class ConnectionManager:
    """Tracks live dashboard WebSocket connections and fans out alert pushes.

    ``loop`` is captured from ``main.py``'s startup event. It is what lets the
    synchronous pipeline (which runs in a worker thread, not the event loop)
    schedule an async broadcast via ``broadcast_sync`` -> ``run_coroutine_threadsafe``.
    """

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        # Idempotent — never raise if the connection was already removed.
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        # Iterate a COPY: a failed send drops the connection mid-loop, which
        # must not mutate the list we are iterating.
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                # One dead connection must not stop the broadcast to the others.
                self.disconnect(connection)

    def broadcast_sync(self, message: dict) -> None:
        """Entrypoint the synchronous pipeline calls. Fire-and-forget.

        No-op if the app hasn't started (no captured loop) or nobody is
        connected — so headless pipeline runs and tests never crash because
        there is nothing to broadcast to.
        """
        if self.loop is None or not self.active_connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)


manager = ConnectionManager()
