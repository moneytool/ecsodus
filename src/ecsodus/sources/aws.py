"""Read-only AWS access.

Every client ecsodus uses is wrapped in :class:`ReadOnlyClient`, which refuses any operation
whose name does not start with describe/list/get/lookup. ecsodus never changes AWS; this makes
that a property of the code, not a promise.

Two read operations are additionally forbidden because they return secret material:
``ssm:GetParameter(s)`` with decryption and ``secretsmanager:GetSecretValue`` (PLAN §2.2).
"""

from __future__ import annotations

from typing import Any

READ_PREFIXES = ("describe_", "list_", "get_", "lookup_")
FORBIDDEN = {
    ("secretsmanager", "get_secret_value"),
    ("secretsmanager", "batch_get_secret_value"),
}
NEUTRAL = {"get_paginator", "get_waiter", "can_paginate", "meta", "exceptions"}


class ReadOnlyViolation(RuntimeError):
    pass


class ReadOnlyClient:
    def __init__(self, client: Any, service: str):
        self._client = client
        self._service = service

    def __getattr__(self, name: str) -> Any:
        if name in NEUTRAL:
            if name == "get_paginator":
                return self._paginator
            return getattr(self._client, name)
        if not name.startswith(READ_PREFIXES):
            raise ReadOnlyViolation(f"{self._service}:{name} is not a read operation")
        if (self._service, name) in FORBIDDEN:
            raise ReadOnlyViolation(f"{self._service}:{name} returns secret values; forbidden")
        fn = getattr(self._client, name)
        if self._service == "ssm" and name in ("get_parameter", "get_parameters",
                                               "get_parameters_by_path"):
            def guarded(**kwargs: Any) -> Any:
                if kwargs.get("WithDecryption"):
                    raise ReadOnlyViolation("ssm WithDecryption=True is forbidden")
                return fn(**kwargs)
            return guarded
        return fn

    def _paginator(self, operation: str) -> Any:
        if not operation.startswith(READ_PREFIXES):
            raise ReadOnlyViolation(f"{self._service}:{operation} paginator is not a read")
        return self._client.get_paginator(operation)


class Clients:
    """Lazily created read-only clients from one boto3 session."""

    def __init__(self, session: Any):
        self._session = session
        self._cache: dict[str, ReadOnlyClient] = {}

    @property
    def region(self) -> str:
        return self._session.region_name or ""

    def __call__(self, service: str) -> ReadOnlyClient:
        if service not in self._cache:
            self._cache[service] = ReadOnlyClient(self._session.client(service), service)
        return self._cache[service]


def paginate(client: ReadOnlyClient, operation: str, key: str, **kwargs: Any) -> list[Any]:
    out: list[Any] = []
    for page in client.get_paginator(operation).paginate(**kwargs):
        out.extend(page.get(key) or [])
    return out
