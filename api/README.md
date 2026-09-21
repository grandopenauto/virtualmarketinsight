# VMI API gateway skeleton

This directory defines the intentionally thin public gateway for `api.virtualmarketinsight.com`.

The public gateway is **not** an unrestricted bridge into HDP internal systems. It exposes explicit, allowlisted contracts only. Private orchestration, credentials, service discovery and privileged execution stay on the private side.

Initial contracts: `GET /health`, `GET /api/v1/surfaces`, `GET /api/v1/graph/sample`.

The sample graph is illustrative and contains no live internal data. On the HDP VPS, bind only to `127.0.0.1`; public access should terminate through IIS/ARR with the approved hostname and TLS.
