# VirtualMarketInsight API gateway

This directory defines the intentionally thin public gateway for `api.virtualmarketinsight.com`.

The public gateway is **not** an unrestricted bridge into HDP internal systems. It exposes explicit, allowlisted contracts only. Private orchestration, credentials, service discovery and privileged execution stay on the private side.

## Current architecture

```text
Public VMI
  -> intent router
  -> operator evidence / brief layer
      -> OIE fixed read adapter
      -> Business Analyst loopback read sidecar
  -> Decision Packet
  -> human approval gate
  -> no execution unless a separate approved execution contract exists
```

### Public routing

- `GET /health`
- `GET /api/v1/surfaces`
- `GET /api/v1/capabilities`
- `GET /api/v1/router/capabilities`
- `POST /api/v1/router/resolve`
- `GET /api/v1/graph/sample`

These endpoints classify intent, expose public-safe capability metadata and build execution-graph plans. They do **not** execute private systems.

## Operator layer

Operator routes require the server-side `VMI_OPERATOR_KEY`. The public GitHub Pages application never receives this key.

Current protected routes include:

- `GET /api/v1/operator/capabilities/health`
- `POST /api/v1/operator/evidence/preview`
- `POST /api/v1/operator/brief`
- `GET /api/v1/operator/native/read-plan`
- `POST /api/v1/operator/decision-packet`
- `GET /api/v1/operator/decision-packet/schema`

Anonymous access to operator routes is rejected.

## Opportunity Intelligence adapter

OIE is the first direct evidence adapter. VMI never accepts an arbitrary upstream URL or arbitrary OIE path. The gateway maps a small allowlist of operation names to known GET routes and enforces server-side result limits and timeouts.

The allowlist includes demand status, demand signals, matches, acquisition context, international markets, capabilities, opportunities, partners, integration status and ontologies. Surface-specific evidence plans select only a bounded subset for each request.

## Business Analyst read bus

VMI does not share Business Analyst's admin credentials and does not call its analysis or execution surfaces.

Instead, `integration/business_analyst_vmi_read.js` runs as a separate NSSM service named `HDP-BusinessAnalyst-VMIRead` and binds only to `127.0.0.1:3193`.

The sidecar is intentionally narrow:

- GET only
- no IIS/public binding
- no arbitrary remote paths
- exact agent + surface allowlist
- delegates only to `nativeAgentAdapters.read()`
- no analysis route
- no execution route
- every response remains read-only and reports zero external actions

A downstream agent may be unavailable without taking VMI down. Operator briefs preserve successful reads and report failed/unreachable reads as capability gaps. This is expected graceful-degradation behavior.

## Decision Packets

VMI v0.6 introduces `vmi.decision-packet.v1`.

A Decision Packet packages the current decision state without granting authority. It contains:

- original intent and resolved front door
- execution-graph path
- candidate capability plan
- capability health
- OIE and Business Analyst read evidence
- evidence-provider success/failure summary
- capability/evidence gaps
- prepared next action
- authority boundaries
- approval gates
- allowed review options
- the next human gate

Creating a Decision Packet does not approve or perform an action. Current packet authority explicitly keeps external execution, analysis generation, capital movement, trading and outreach disabled and records `external_actions_executed: 0`.

## Authority boundary

The layers are intentionally separated:

1. **Routing** may classify intent and suggest capability lanes.
2. **Evidence** may perform fixed read-only retrieval.
3. **Briefs and Decision Packets** may assemble evidence, gaps and next steps.
4. **Human review** is required before any consequential action.
5. **Execution** requires a separate bounded contract, applicable approvals and explicit authority.

A service being known to VMI does not mean VMI is authorized to execute it.

## Deployment

On the HDP VPS:

- VMI gateway: `HDP-VMI-API` on `127.0.0.1:3204`
- Business Analyst read sidecar: `HDP-BusinessAnalyst-VMIRead` on `127.0.0.1:3193`
- public API access terminates through IIS/ARR at `api.virtualmarketinsight.com`
- TLS is managed through win-acme

The sidecar has no IIS binding and is not directly reachable from the public internet.
