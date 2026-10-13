// Settings read once at startup.
const TIMEOUT_MS = 45000;
const RETRIES = 2;

function loadConfig(path) {
  const raw = require("fs").readFileSync(path, "utf8");
  return { ...JSON.parse(raw), timeoutMs: TIMEOUT_MS, retries: RETRIES };
}

module.exports = { loadConfig, TIMEOUT_MS, RETRIES };
