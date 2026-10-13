const { loadCfg } = require("./config");

const cfg = loadCfg(process.argv[2] || "settings.json");
console.log(`timeout ${cfg.timeoutMs} ms, ${cfg.retries} retries`);
