// Settings read once at startup.
const TIMEOUT_MS = 30000;
const RETRIES = 2;

function loadCfg(path) {
  const raw = require("fs").readFileSync(path, "utf8");
  return { ...JSON.parse(raw), timeoutMs: TIMEOUT_MS, retries: RETRIES };
}

module.exports = { loadCfg, TIMEOUT_MS, RETRIES };
