#!/bin/sh

node <<'NODE'
const fs = require("fs");

function safePatch(file, label, skipToken, search, replace) {
  let code;
  try { code = fs.readFileSync(file, "utf8"); } catch(e) { console.log("[patch] AVISO - arquivo nao encontrado:", file); return; }
  if (code.includes(skipToken)) { console.log("[patch] ja aplicado:", label); return; }
  const next = code.split(search).join(replace);
  if (next === code) { console.log("[patch] AVISO - padrao nao encontrado:", label); }
  else { fs.writeFileSync(file, next); console.log("[patch] OK:", label); }
}

// 1. index.js: desativa interceptor res.send duplicado
safePatch(
  "/home/user/wppconnect-server/dist/index.js",
  "index: desativar interceptor res.send",
  "return next(); res.send = async function",
  "res.send = async function (data)",
  "return next(); res.send = async function (data)"
);

// 2. messageController.js: guard returnError
safePatch(
  "/home/user/wppconnect-server/dist/controller/messageController.js",
  "messageController: returnError guard",
  "if (res.headersSent) return;",
  "function returnError(req, res, error) {",
  "function returnError(req, res, error) { if (res.headersSent) return;"
);

// 3. messageController.js: results empty guard
safePatch(
  "/home/user/wppconnect-server/dist/controller/messageController.js",
  "messageController: results empty guard",
  "return res.status(400)",
  "if (results.length === 0) res.status(400)",
  "if (results.length === 0) return res.status(400)"
);

// 4. statusConnection.js: return antes de res.status(4xx)
(function patchStatusConnection() {
  const file = "/home/user/wppconnect-server/dist/middleware/statusConnection.js";
  let code;
  try { code = fs.readFileSync(file, "utf8"); } catch(e) { console.log("[patch] AVISO - arquivo nao encontrado:", file); return; }
  if (code.includes("// WPPFIX_STATUS_CONN")) { console.log("[patch] ja aplicado: statusConnection return guard"); return; }
  let patched = code.replace(/([^a-zA-Z])res\.status\((4\d\d)\)\.json\(/g, "$1return res.status($2).json(");
  patched += "\n// WPPFIX_STATUS_CONN";
  fs.writeFileSync(file, patched);
  console.log("[patch] OK: statusConnection return guard");
})();

// 5. sessionController.js: logout() seguro + headersSent guard
(function patchSessionController() {
  const file = "/home/user/wppconnect-server/dist/controller/sessionController.js";
  let code;
  try { code = fs.readFileSync(file, "utf8"); } catch(e) { console.log("[patch] AVISO - arquivo nao encontrado:", file); return; }
  let changed = false;

  if (!code.includes("typeof req.client.logout === 'function'")) {
    code = code.split("await req.client.logout();").join(
      "if (req.client && typeof req.client.logout === 'function') { await req.client.logout(); }" +
      " else if (req.client && typeof req.client.close === 'function') { await req.client.close(); }"
    );
    changed = true;
    console.log("[patch] OK: sessionController logout guard");
  } else {
    console.log("[patch] ja aplicado: sessionController logout guard");
  }

  if (changed) fs.writeFileSync(file, code);
})();

// 6. create-config.js: aumenta autoClose e deviceSyncTimeout para 5 minutos (300000ms)
safePatch(
  "/home/user/wppconnect-server/node_modules/@wppconnect-team/wppconnect/dist/config/create-config.js",
  "create-config: autoClose 60s -> 300s",
  "autoClose: 300000",
  "autoClose: 60000",
  "autoClose: 300000"
);
safePatch(
  "/home/user/wppconnect-server/node_modules/@wppconnect-team/wppconnect/dist/config/create-config.js",
  "create-config: deviceSyncTimeout 3min -> 5min",
  "deviceSyncTimeout: 300000",
  "deviceSyncTimeout: 180000",
  "deviceSyncTimeout: 300000"
);

console.log("[patch] Todos os patches concluidos.");
NODE

echo "=== WPP Connect patches aplicados. Iniciando servidor... ==="
exec node /home/user/wppconnect-server/dist/server.js
