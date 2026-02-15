"""Home Assistant WebSocket API client."""

import asyncio
import contextlib
import json
import logging
from typing import Any

import websockets

logger = logging.getLogger(__name__)


class HAWebSocketClient:
    """Simple synchronous request-response WS client for HA."""

    def __init__(self, url: str, token: str, timeout: float = 30.0):
        self.url = url
        self.token = token
        self.timeout = timeout
        self._ws: Any | None = None
        self._msg_id = 1

    async def connect(self) -> None:
        """Connect and authenticate to HA WebSocket."""
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

        if not self.token:
            raise ConnectionError(
                "No authentication token. "
                "Ensure 'hassio_api: true' in config.json and addon was installed."
            )

        logger.info("Connecting to Home Assistant at %s", self.url)

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.url, ping_interval=None, max_size=2**24),
                timeout=10.0,
            )

            # auth_required
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            msg = json.loads(raw)
            if msg.get("type") != "auth_required":
                raise ConnectionError(f"Expected auth_required, got: {msg.get('type')}")

            # Send auth
            await self._ws.send(
                json.dumps(
                    {
                        "type": "auth",
                        "access_token": self.token,
                    }
                )
            )

            # auth response
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            resp = json.loads(raw)
            if resp.get("type") != "auth_ok":
                raise ConnectionError(f"Auth failed: {resp.get('message', 'unknown')}")

            logger.info("Connected to Home Assistant successfully")

        except TimeoutError:
            await self._close_ws()
            raise ConnectionError("Timeout connecting to Home Assistant") from None
        except ConnectionError:
            await self._close_ws()
            raise
        except Exception as e:
            await self._close_ws()
            raise ConnectionError(f"Failed to connect: {e}") from e

    async def _close_ws(self) -> None:
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

    async def send(self, msg_type: str, **kwargs: Any) -> Any:
        """Send command and read response directly (no background reader)."""
        if self._ws is None:
            await self.connect()

        msg_id = self._msg_id
        self._msg_id += 1

        msg = {"id": msg_id, "type": msg_type, **kwargs}

        try:
            await self._ws.send(json.dumps(msg))

            # Read responses until we get our result
            while True:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
                data = json.loads(raw)

                if data.get("type") == "result" and data.get("id") == msg_id:
                    if data.get("success"):
                        return data.get("result")
                    error = data.get("error", {})
                    raise RuntimeError(
                        f"HA error {error.get('code', '?')}: {error.get('message', '?')}"
                    )
                # Skip events and other messages
        except TimeoutError:
            raise RuntimeError(f"Timeout waiting for {msg_type}") from None
        except Exception as e:
            # Connection lost - reset and raise
            await self._close_ws()
            raise RuntimeError(f"WS error during {msg_type}: {e}") from e

    # Registry API wrappers
    async def area_list(self) -> list[dict]:
        return await self.send("config/area_registry/list")

    async def area_create(self, name: str) -> dict:
        return await self.send("config/area_registry/create", name=name)

    async def area_update(self, area_id: str, name: str) -> dict:
        return await self.send("config/area_registry/update", area_id=area_id, name=name)

    async def entity_list(self) -> list[dict]:
        return await self.send("config/entity_registry/list")

    async def entity_update(self, entity_id: str, **kwargs: Any) -> dict:
        # Build payload manually so None values are sent as JSON null (to clear fields)
        payload = {"entity_id": entity_id}
        payload.update(kwargs)
        return await self.send("config/entity_registry/update", **payload)

    async def entity_remove(self, entity_id: str) -> Any:
        return await self.send("config/entity_registry/remove", entity_id=entity_id)

    async def device_list(self) -> list[dict]:
        return await self.send("config/device_registry/list")

    async def device_update(self, device_id: str, **kwargs: Any) -> dict:
        return await self.send("config/device_registry/update", device_id=device_id, **kwargs)

    async def get_states(self) -> list[dict]:
        return await self.send("get_states")
