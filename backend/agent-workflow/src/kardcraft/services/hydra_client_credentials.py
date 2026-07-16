"""OAuth2 client-credentials support for internal service calls."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ClientCredentialsConfig:
    token_url: str
    client_id: str
    client_secret: str
    audience: str
    scope: str


class ClientCredentialsTokenProvider:
    def __init__(self, config: ClientCredentialsConfig) -> None:
        if not all(
            [
                config.token_url.strip(),
                config.client_id.strip(),
                config.client_secret.strip(),
                config.audience.strip(),
                config.scope.strip(),
            ]
        ):
            raise ValueError("Hydra client credentials configuration is incomplete")
        self._config = config
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            response = await client.post(
                self._config.token_url,
                auth=(self._config.client_id, self._config.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": self._config.scope,
                    "audience": self._config.audience,
                },
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload.get("access_token") or "").strip()
            expires_in = int(payload.get("expires_in") or 0)
            if not token or expires_in <= 30:
                raise ValueError("Hydra token response is missing a usable access token")
            self._token = token
            self._expires_at = time.monotonic() + expires_in - 30
            return token
