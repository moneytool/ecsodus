# Security policy

ecsodus is read-only by design. It never modifies AWS, never applies Terraform and never reads
secret values. It writes files that the operator reviews and runs.

## Handling sensitive output
These files can contain plaintext task-definition environment values:
- `inventory.json`
- the generated Terraform
- `plan.json`
- `state.txt`
- state checkpoints

ecsodus writes them with mode 0600 and lists them in `.gitignore`. Keep Terraform state in an
encrypted, locked S3 backend.

## Reporting a vulnerability
Please report suspected vulnerabilities privately through GitHub Security Advisories on this
repository. Do not open a public issue. Expect an acknowledgement within 7 days.

Reports that would make ecsodus's output **destroy or orphan** a resource are treated as the
highest severity.
