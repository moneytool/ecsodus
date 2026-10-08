"""The inventory model (PLAN §2.1).

``inventory.json`` is the hand-off between ``ecsodus inventory`` (which reads AWS) and every other
command (which only reads the file). Every stack and resource keeps its provenance: which stack,
which account and region, and when it was read.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ecsodus import __version__

SCHEMA_VERSION = 1

# Stack kinds in the Copilot layering (docs/knowledge/copilot-stacks.md).
APP = "app"
STACKSET_INSTANCE = "stackset-instance"
ENV = "env"
WORKLOAD = "workload"
ADDONS = "addons"  # nested addons stack under a workload stack
ENV_ADDONS = "env-addons"  # nested addons stack under an env stack

# Workload types ecsodus can hand off (PLAN §3, ADR-0014). Everything else is detected and
# blocked.
SUPPORTED_WORKLOAD_TYPES = (
    "Load Balanced Web Service",
    "Backend Service",
    "Worker Service",
    "Scheduled Job",
)


@dataclass
class Resource:
    logical_id: str
    type: str
    physical_id: str | None
    status: str = ""


@dataclass
class Stack:
    name: str
    kind: str
    stack_id: str = ""
    status: str = ""
    template_body: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    exports: dict[str, str] = field(default_factory=dict)  # export name -> value
    tags: dict[str, str] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    last_updated: str = ""
    parent: str | None = None  # parent stack name for nested stacks
    parent_logical_id: str | None = None  # logical ID of the wrapper in the parent
    env: str | None = None
    workload: str | None = None
    workload_type: str | None = None
    resources: list[Resource] = field(default_factory=list)

    def resource(self, logical_id: str) -> Resource | None:
        return next((r for r in self.resources if r.logical_id == logical_id), None)


@dataclass
class StackSet:
    name: str
    template_body: str = ""
    administration_role_arn: str = ""
    execution_role_name: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    instances: list[dict[str, str]] = field(default_factory=list)  # account, region, stack_id


@dataclass
class OutOfBand:
    """An object a custom resource created outside CloudFormation (e.g. an ACM certificate)."""

    kind: str  # acm_certificate | route53_record
    id: str
    created_by: str  # "<stack>/<logical id>" of the custom resource
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Workload:
    name: str
    type: str
    env: str
    migrate: bool = True  # False = stays on Copilot (partial migration)


@dataclass
class Inventory:
    app: str
    account: str
    region: str
    captured_at: str
    ecsodus_version: str = __version__
    schema_version: int = SCHEMA_VERSION
    envs: list[str] = field(default_factory=list)
    workloads: list[Workload] = field(default_factory=list)
    stacks: dict[str, Stack] = field(default_factory=dict)
    stacksets: dict[str, StackSet] = field(default_factory=dict)
    live: dict[str, dict[str, Any]] = field(default_factory=dict)  # physical id -> attributes
    out_of_band: list[OutOfBand] = field(default_factory=list)
    ssm_parameters: list[dict[str, str]] = field(default_factory=list)  # name, type (no values)
    # Exports of stacks outside the app that its templates import (Fn::ImportValue), for
    # example a shared EFS file system: export name -> {"value", "stack"}.
    external_exports: dict[str, dict[str, str]] = field(default_factory=dict)
    disputed: list[dict[str, Any]] = field(default_factory=list)
    unavailable: list[dict[str, Any]] = field(default_factory=list)
    # How the inventory was taken, replayed by the runbook (envs, keep_on_copilot, profile...).
    selection: dict[str, Any] = field(default_factory=dict)

    # -- helpers ---------------------------------------------------------------------------
    def stacks_of(self, kind: str) -> list[Stack]:
        return [s for s in self.stacks.values() if s.kind == kind]

    def children(self, stack_name: str) -> list[Stack]:
        return [s for s in self.stacks.values() if s.parent == stack_name]

    def workload(self, name: str, env: str) -> Workload | None:
        return next((w for w in self.workloads if w.name == name and w.env == env), None)

    def age_seconds(self, now: datetime | None = None) -> float:
        captured = datetime.fromisoformat(self.captured_at)
        return ((now or datetime.now(UTC)) - captured).total_seconds()

    # -- serialisation ---------------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Inventory:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"inventory schema {data.get('schema_version')} is not supported "
                f"(expected {SCHEMA_VERSION}); re-run `ecsodus inventory`"
            )
        stacks = {}
        for name, s in data.get("stacks", {}).items():
            s = dict(s)
            s["resources"] = [Resource(**r) for r in s.get("resources", [])]
            stacks[name] = Stack(**s)
        return cls(
            app=data["app"],
            account=data["account"],
            region=data["region"],
            captured_at=data["captured_at"],
            ecsodus_version=data.get("ecsodus_version", ""),
            schema_version=data["schema_version"],
            envs=list(data.get("envs", [])),
            workloads=[Workload(**w) for w in data.get("workloads", [])],
            stacks=stacks,
            stacksets={k: StackSet(**v) for k, v in data.get("stacksets", {}).items()},
            live=dict(data.get("live", {})),
            out_of_band=[OutOfBand(**o) for o in data.get("out_of_band", [])],
            ssm_parameters=list(data.get("ssm_parameters", [])),
            external_exports=dict(data.get("external_exports", {})),
            disputed=list(data.get("disputed", [])),
            unavailable=list(data.get("unavailable", [])),
            selection=dict(data.get("selection", {})),
        )

    @classmethod
    def load(cls, path: str | Path) -> Inventory:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        write_sensitive(path, self.to_json())


def write_sensitive(path: str | Path, text: str) -> None:
    """Write a file that may contain plaintext environment values: mode 0600 (PLAN §2.2)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(p, 0o600)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
