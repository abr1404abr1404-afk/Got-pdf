import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const root = process.cwd();
const htmlPath = path.join(root, "index.html");
const html = fs.readFileSync(htmlPath, "utf8");
const failures = [];
let inlineScripts = 0;

// Validate every local script and stylesheet referenced by the deployed entry point.
const resourcePattern = /<(script|link)\\b([^>]*?)>/gi;
for (const match of html.matchAll(resourcePattern)) {
  const tag = match[1].toLowerCase();
  const attrs = match[2];
  const rel = (attrs.match(/\\brel\\s*=\\s*["']([^"']+)["']/i) || [])[1] || "";
  const attr = tag === "script" ? "src" : rel.toLowerCase().split(/\\s+/).includes("stylesheet") ? "href" : null;
  if (!attr) continue;
  const value = (attrs.match(new RegExp("\\\\b" + attr + "\\\\s*=\\\\s*[\"']([^\"']+)[\"']", "i")) || [])[1];
  if (!value || /^(https?:)?\\/\\//i.test(value) || value.startsWith("data:")) continue;
  const localPath = path.resolve(root, decodeURIComponent(value.split(/[?#]/, 1)[0]));
  if (!localPath.startsWith(root + path.sep) && localPath !== root) {
    failures.push(`Blocked local resource path: ${value}`);
  } else if (!fs.existsSync(localPath)) {
    failures.push(`Missing local resource: ${value}`);
  }
}

// Compile inline scripts without executing browser code. This catches syntax errors
// before they reach GitHub Pages while keeping the check dependency-free.
const scriptPattern = /<script\\b([^>]*)>([\\s\\S]*?)<\\/script\\s*>/gi;
for (const match of html.matchAll(scriptPattern)) {
  const attrs = match[1];
  const code = match[2].trim();
  if (!code) continue;
  inlineScripts += 1;
  try {
    new vm.Script(code, { filename: `index.html:inline-script-${inlineScripts}` });
  } catch (error) {
    failures.push(`Inline script ${inlineScripts}: ${error.message}`);
  }
}

for (const id of ["main", "file", "fn", "info", "toast"]) {
  const escaped = id.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
  if (!new RegExp(`\\\\bid\\\\s*=\\\\s*["']${escaped}["']`, "i").test(html)) {
    failures.push(`Required application element is missing: #${id}`);
  }
}

if (failures.length) {
  console.error("Frontend checks failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Frontend checks passed: ${inlineScripts} inline scripts parsed; local assets resolved.`);
