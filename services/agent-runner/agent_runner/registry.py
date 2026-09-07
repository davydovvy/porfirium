from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from agent_runner.models import RunAdmission, SignedSpecification


class RegistryResolutionError(RuntimeError):
    pass


class ClientCredentialsTokenProvider:
    def __init__(
        self, client: httpx.AsyncClient, token_url: str, client_id: str, client_secret: str
    ) -> None:
        self.client = client
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def __call__(self, _: RunAdmission) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at - 30:
                return self._token
            try:
                response = await self.client.post(
                    self.token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(self.client_id, self.client_secret),
                )
                response.raise_for_status()
                payload = response.json()
                token = payload["access_token"]
                expires_in = int(payload.get("expires_in", 60))
                if not isinstance(token, str) or not token or expires_in < 1:
                    raise ValueError
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise RegistryResolutionError(
                    "Registry identity token acquisition failed"
                ) from error
            self._token = token
            self._expires_at = time.monotonic() + expires_in
            return token


class RegistryClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        token_provider: Callable[[RunAdmission], Awaitable[str]],
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider

    async def resolve(self, admission: RunAdmission, idempotency_key: str) -> SignedSpecification:
        token = await self.token_provider(admission)
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/run-specifications:resolve",
                json=admission.resolution_payload(),
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key},
            )
            response.raise_for_status()
            specification = SignedSpecification.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise RegistryResolutionError("Registry resolution failed") from error
        if specification.run_id != admission.run_id:
            raise RegistryResolutionError("Registry returned a specification for another run")
        return specification
