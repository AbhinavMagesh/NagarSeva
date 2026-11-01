import socketio

from app.config import settings

socket_server = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[settings.frontend_url],
    logger=False,
    engineio_logger=False,
)


async def publish(event: str, data: dict) -> None:
    await socket_server.emit(event, data)
