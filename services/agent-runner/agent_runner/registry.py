from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from agent_runner.models import RunAdmission, SignedSpecification


class RegistryResolutionError(RuntimeError):
    pass


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

