# ADR-0011: Import Service Connect as deployed in adopt-in-place

- Status: accepted
- Date: 2026-09-30
- Deciders: maintainer (AWS end-to-end run)

## Context
PLAN §3 lists "Service Connect consumers" as blocked in v0.1. The compute mapper had read that as
blocking *any* service with Service Connect enabled. The AWS end-to-end run showed that Copilot
v1.34.1 enables Service Connect on every Load Balanced Web Service by default. Under that reading,
every real Copilot app would have been blocked.

## Decision
In adopt-in-place, nothing moves, so the service's existing Service Connect configuration is
imported exactly as it is. The `service_connect_configuration` block is built from the live
PRIMARY deployment's configuration. Unknown keys, TLS settings and log secret options still block
the service. Service Connect *consumers* only matter for rebuild mode (v0.2), and the PLAN §3
restriction stays in place for that mode.

## Consequences
Real Copilot LBWS apps can be handed off. The end-to-end run's import plan is 44/44 pure imports.
