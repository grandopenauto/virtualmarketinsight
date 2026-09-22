# VirtualMarketInsight API gateway

This directory defines the intentionally thin public gateway for `api.virtualmarketinsight.com`.

The public gateway is **not** an unrestricted bridge into HDP internal systems. It exposes explicit, allowlisted contracts only. Private orchestration, credentials, service discovery and privileged execution stay on the private side.

## Current gateway layers

### Public routing

- `GET /health`
- `GET /api/v1/surfaces`
- `GET /api/v1/capabilities`
- `GET /api/v1/router/capabilities`
- `POST /api/v1/router/resolve`
- `GET /api/v1/graph/sample`

These endpoints classify intent, expose public-safe capability metadata and build execution-graph plans. They do **not** execute private systems.

### Operator evidence layer

- `POST /api/v1/operator/evidence/preview`

This endpoint requires the server-side `VMI_OPERATOR_KEY` and is not called by the public GitHub Pages application. It may gather evidence only through fixed, read-only adapter operations.

The first live adapter is the HDP Opportunity Intelligence Engine (OIE). VMI never accepts an arbitrary upstream URL or arbitrary OIE path. The gateway maps a small allowlist of operation names to known GET routes and enforces server-side result limits and timeouts.

Current OIE allowlist includes demand status, demand signals, matches, acquisition context, international markets, capabilities, opportunities, partners, integration status and ontologies. Surface-specific evidence plans select only a subset of these operations for a request.

## Authority boundary

The evidence layer is intentionally separate from execution. Current operator evidence responses report:

- `adapter_authority: read-only`
- `execution_state: evidence_gathering_only`
- `external_actions_executed: 0`

Anonymous evidence access is rejected. The operator credential is generated and stored on the VPS and is never committed to GitHub.

Business Analyst, LinkStream, Opportunity Explorer, Shebavonova, Commodity Clarity and AgentForSell are represented in the capability registry at their current integration stage. A service being known to VMI does not mean VMI is authorized to execute it.

## Deployment

On the HDP VPS the gateway binds to `127.0.0.1:3204`. Public access terminates through IIS/ARR at `api.virtualmarketinsight.com` with TLS managed through win-acme. The service runs under NSSM as `HDP-VMI-API`.
