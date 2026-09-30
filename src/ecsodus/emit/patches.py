"""Retain-patch orchestration across stacks (PLAN §2.4, §13.1).

Nested stacks are patched through their parent: each child template is patched first, uploaded
to S3 under a content-addressed key, and the parent's wrapper ``TemplateURL`` is rewritten to
point at it. The StackSet template is patched for ``update-stack-set``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ecsodus.emit.retain_patch import PatchResult, patch_template, sha256
from ecsodus.model import ADDONS, ENV_ADDONS, Inventory


@dataclass
class StackPatch:
    stack: str
    result: PatchResult
    key: str  # S3 object key of the uploaded patched template (nested and large templates)
    url: str
    already_retained: bool
    children: dict[str, str] = field(default_factory=dict)  # wrapper logical id -> child stack


@dataclass
class PatchSet:
    bucket: str
    metadata_fallback: bool = False
    stacks: dict[str, StackPatch] = field(default_factory=dict)
    stackset: dict[str, PatchResult] = field(default_factory=dict)


def s3_url(bucket: str, region: str, key: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def build_patches(
    inv: Inventory,
    bucket: str,
    metadata_fallback: bool = False,
    only: set[str] | None = None,
) -> PatchSet:
    """Patch every stack in ``only`` (default: all). Kept stacks are never patched or touched,
    so an unpatchable kept stack cannot abort generation."""
    ps = PatchSet(bucket=bucket, metadata_fallback=metadata_fallback)

    # Children before parents: deepest nesting first.
    def depth(name: str) -> int:
        d, s = 0, inv.stacks[name]
        while s.parent and s.parent in inv.stacks:
            d, s = d + 1, inv.stacks[s.parent]
        return d

    for name in sorted(inv.stacks, key=depth, reverse=True):
        if only is not None and name not in only:
            continue
        stack = inv.stacks[name]
        overrides: dict[str, str] = {}
        children: dict[str, str] = {}
        for child in inv.children(name):
            if (
                child.kind in (ADDONS, ENV_ADDONS)
                and child.parent_logical_id
                and (child.name in ps.stacks)
            ):
                overrides[child.parent_logical_id] = ps.stacks[child.name].url
                children[child.parent_logical_id] = child.name
        result = patch_template(stack.template_body, overrides, metadata_fallback)
        key = f"ecsodus/retain-patches/{name}/{result.sha256}.yml"
        ps.stacks[name] = StackPatch(
            stack=name,
            result=result,
            key=key,
            url=s3_url(bucket, inv.region, key),
            already_retained=not result.changed_resources,
            children=children,
        )
    instance_selected = only is None or any(
        n in inv.stacks and inv.stacks[n].kind == "stackset-instance" for n in only
    )
    for name, ss in inv.stacksets.items():
        if ss.template_body and instance_selected:
            ps.stackset[name] = patch_template(ss.template_body, {}, metadata_fallback)
    return ps


def default_patch_bucket(inv: Inventory) -> str | None:
    """Copilot's artifact bucket from the StackSet instance stack, if present."""
    for stack in inv.stacks.values():
        for r in stack.resources:
            if r.type == "AWS::S3::Bucket" and "Pipeline" in r.logical_id and r.physical_id:
                return r.physical_id
    return None


def template_sha(text: str) -> str:
    return sha256(text)
