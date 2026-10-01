"""Build the inputs for docs/assets/gates.gif (rendered by docs/assets/gates.tape).

    uv run python tools/visuals/prepare_gates_demo.py /tmp/ecsodus-gates-demo

Creates, from the full hand-off test app: a generated project (infra/), an unsafe Terraform plan
(an import that would also update a database), the pure-import plan, a change set that modifies
a property, and a policy-only change set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ecsodus.cli import main  # noqa: E402
from tests.golden.live_synth import build_app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ecsodus-gates-demo")
out.mkdir(parents=True, exist_ok=True)
inv = build_app("aurora")
inv.save(out / "inventory.json")
assert (
    main(
        [
            "generate",
            str(out / "inventory.json"),
            "--out",
            str(out / "infra"),
            "--patch-bucket",
            "my-app-artifacts",
        ]
    )
    == 0
)
infra = out / "infra"
records = json.loads((infra / "ecsodus-manifest.json").read_text())["imports"]


def plan(changes: list[dict]) -> dict:
    return {"format_version": "1.2", "resource_changes": changes}


def rc(r: dict, actions: list[str]) -> dict:
    return {
        "address": r["address"],
        "mode": "managed",
        "type": r["address"].split(".")[0],
        "provider_name": "registry.terraform.io/hashicorp/aws",
        "change": {"actions": actions, "importing": {"id": r["id"]}},
    }


pure = [rc(r, ["no-op"]) for r in records]
unsafe = [dict(c) for c in pure]
db = next(i for i, r in enumerate(records) if r["type"] == "AWS::RDS::DBCluster")
unsafe[db] = rc(records[db], ["update"])
(infra / "plan-import.json").write_text(json.dumps(plan(pure)))
(infra / "plan-unsafe.json").write_text(json.dumps(plan(unsafe)))


def cs(details: list[dict], replacement: str = "False") -> dict:
    return {
        "StackName": "my-app-test-fe",
        "ChangeSetId": "root",
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "Changes": [
            {
                "Type": "Resource",
                "ResourceChange": {
                    "Action": "Modify",
                    "LogicalResourceId": "Service",
                    "ResourceType": "AWS::ECS::Service",
                    "Replacement": replacement,
                    "Details": details,
                },
            }
        ],
    }


policy = [
    {"Target": {"Attribute": a, "RequiresRecreation": "Never"}, "Evaluation": "Static"}
    for a in ("DeletionPolicy", "UpdateReplacePolicy")
]
prop = [
    {
        "Target": {
            "Attribute": "Properties",
            "Name": "DesiredCount",
            "RequiresRecreation": "Never",
        },
        "Evaluation": "Static",
    }
]
(infra / "cs-retain.json").write_text(json.dumps(cs(policy)))
(infra / "cs-unsafe.json").write_text(json.dumps(cs(policy + prop)))
print(out)
