"""The saved label workflow runs under node with faked agents."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".claude" / "workflows" / "local-label-claude-check.js"

HARNESS = r"""
const fs = require('fs')
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/^export const meta/m, 'const meta')
const mode = process.argv[3]
const calls = []
const agent = async (prompt, opts) => {
  calls.push(opts.label)
  if (opts.label.startsWith('decide --batch')) return { exit_code: 0, body: { items: 3, done: 3, missing: [] } }
  if (opts.label === 'label-select') {
    const inner = { items: 2, fields: 3, out: 'todo' }
    return { exit_code: 0, body: mode === 'envelope' ? { ok: true, verb: 'label-select', body: inner } : inner }
  }
  if (opts.label.startsWith('check')) return { results: [{ id: 'a', answers: {} }, { id: 'b', answers: {} }] }
  return 'report'
}
const parallel = async ts => Promise.all(ts.map(t => t().catch(() => null)))
const phase = () => {}
const log = () => {}
const args = { items: 'i.json', out: 'o' }
const run = new Function('agent', 'parallel', 'phase', 'log', 'args', `return (async () => { ${src} })()`)
run(agent, parallel, phase, log, args).then(r => console.log(JSON.stringify({ r, calls })))
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("mode", ["flat", "envelope"])
def test_the_check_stage_runs_whether_the_runner_returns_the_body_or_the_whole_envelope(tmp_path, mode):
    harness = tmp_path / "h.js"
    harness.write_text(HARNESS, encoding="utf-8")
    out = subprocess.run(["node", str(harness), str(SCRIPT), mode], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert got["r"]["selected"] == 2
    assert got["r"]["checked"] == 2
    assert any(c.startswith("check") for c in got["calls"])
