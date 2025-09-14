from typing import Callable, Union

import httpx


class ResendTransport:
    """
    Unified wrapper for sending data to the cloud.
    - Supports dict (automatically sent as JSON) or str (sent as JSON string with Content-Type).
    - Returns (ok, status_code, text) for convenient logging by upper layers.
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient, is_ok: Callable[[httpx.Response], bool]):
        self.base_url = base_url
        self.client = client
        self._is_ok = is_ok

    async def send(self, payload: Union[dict, str]) -> tuple[bool, int, str]:
        if isinstance(payload, dict):
            resp = await self.client.post(self.base_url, json=payload)
        else:
            resp = await self.client.post(self.base_url, data=payload, headers={"Content-Type": "application/json"})
        try:
            ok = self._is_ok(resp)
        except Exception:
            ok = False
        return ok, resp.status_code, (resp.text or "")
