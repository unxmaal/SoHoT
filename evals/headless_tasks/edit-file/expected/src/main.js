const { loadConfig } = require("./config");

const cfg = loadConfig(process.argv[2] || "settings.json");
console.log(`timeout ${cfg.timeoutMs} ms, ${cfg.retries} retries`);
