'use strict';

/*
 * VirtualMarketInsight -> Business Analyst read sidecar.
 *
 * Security boundary:
 * - binds only to 127.0.0.1
 * - GET only
 * - exact agent/surface allowlist
 * - delegates only to nativeAgentAdapters.read()
 * - no analyze/execute routes
 * - no IIS/public binding
 */

const http = require('http');
const { URL } = require('url');
const adapters = require('C:\\HDP\\BusinessAnalyst\\src\\nativeAgentAdapters');

const HOST = '127.0.0.1';
const PORT = Number(process.env.VMI_BA_READ_PORT || 3193);

const ALLOWED = Object.freeze({
  markets: Object.freeze([
    Object.freeze(['seoagent', 'operations']),
    Object.freeze(['entrepreneuragent', 'core_overview'])
  ]),
  analyst: Object.freeze([
    Object.freeze(['accountingagent', 'entities']),
    Object.freeze(['entrepreneuragent', 'core_overview'])
  ]),
  opportunities: Object.freeze([
    Object.freeze(['leadwizard', 'contractors']),
    Object.freeze(['leadwizard', 'company_profiles']),
    Object.freeze(['entrepreneuragent', 'core_overview'])
  ]),
  'operational-capital': Object.freeze([
    Object.freeze(['accountingagent', 'entities']),
    Object.freeze(['webdevagent', 'orchestration']),
    Object.freeze(['entrepreneuragent', 'core_overview'])
  ]),
  agents: Object.freeze([
    Object.freeze(['entrepreneuragent', 'agents']),
    Object.freeze(['webdevagent', 'studio']),
    Object.freeze(['leadwizard', 'connector_manifest'])
  ])
});

const allowedPairs = new Set(
  Object.values(ALLOWED).flat().map(([agentId, surface]) => `${agentId}:${surface}`)
);

function json(res, status, body) {
  const payload = Buffer.from(JSON.stringify(body));
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': payload.length,
    'cache-control': 'no-store'
  });
  res.end(payload);
}

function safePlan() {
  return Object.fromEntries(
    Object.entries(ALLOWED).map(([surface, pairs]) => [
      surface,
      pairs.map(([agentId, readSurface]) => ({ agent_id: agentId, surface: readSurface }))
    ])
  );
}

const server = http.createServer(async (req, res) => {
  if (req.method !== 'GET') {
    return json(res, 405, {
      ok: false,
      error: 'method_not_allowed',
      execution_allowed: false,
      external_actions_executed: 0
    });
  }

  const url = new URL(req.url, `http://${HOST}:${PORT}`);

  if (url.pathname === '/health') {
    return json(res, 200, {
      ok: true,
      service: 'vmi-business-analyst-read-sidecar',
      version: '0.1.0',
      bind_host: HOST,
      authority: 'read-only',
      arbitrary_paths_allowed: false,
      analysis_allowed: false,
      execution_allowed: false,
      external_actions_executed: 0
    });
  }

  if (url.pathname === '/read-plan') {
    return json(res, 200, {
      ok: true,
      authority: 'read-only',
      surfaces: safePlan(),
      arbitrary_paths_allowed: false,
      analysis_allowed: false,
      execution_allowed: false,
      external_actions_executed: 0
    });
  }

  const match = url.pathname.match(/^\/read\/([a-z0-9_-]+)\/([a-z0-9_-]+)$/i);
  if (!match) {
    return json(res, 404, { ok: false, error: 'not_found', external_actions_executed: 0 });
  }

  const agentId = match[1].toLowerCase();
  const surface = match[2].toLowerCase();
  if (!allowedPairs.has(`${agentId}:${surface}`)) {
    return json(res, 403, {
      ok: false,
      error: 'read_surface_not_allowed',
      agent_id: agentId,
      surface,
      external_actions_executed: 0
    });
  }

  const query = Object.fromEntries(url.searchParams.entries());
  try {
    const result = await adapters.read(agentId, surface, { query });
    return json(res, result && result.success ? 200 : 502, {
      ...result,
      authority: 'read-only',
      external_actions_executed: 0
    });
  } catch (err) {
    return json(res, 500, {
      ok: false,
      error: 'native_read_failed',
      reason: String((err && err.message) || err || 'unknown_error'),
      external_actions_executed: 0
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`VMI Business Analyst read sidecar listening on http://${HOST}:${PORT}`);
});
