import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const root = process.cwd();
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const failures = [];
let inlineScripts = 0;

// Confirm that local scripts and stylesheets referenced by the deployed entry point exist.
const resourcePattern = /<(script|link)\b([^>]*?)>/gi;
for (const match of html.matchAll(resourcePattern)) {
  const tag = match[1].toLowerCase();
  const attrs = match[2];
  const rel = (attrs.match(/\brel\s*=\s*["']([^"']+)["']/i) || [])[1] || "";
  const attr = tag === "script" ? "src" :
    rel.toLowerCase().split(/\s+/).includes("stylesheet") ? "href" : null;
  if (!attr) continue;
  const value = (attrs.match(new RegExp("\\b" + attr + "\\s*=\\s*[\"']([^\"']+)[\"']", "i")) || [])[1];
  if (!value || /^(https?:)?\/\//i.test(value) || value.startsWith("data:")) continue;
  const localPath = path.resolve(root, decodeURIComponent(value.split(/[?#]/, 1)[0]));
  if (!localPath.startsWith(root + path.sep) && localPath !== root) {
    failures.push("Blocked local resource path: " + value);
  } else if (!fs.existsSync(localPath)) {
    failures.push("Missing local resource: " + value);
  }
}

// Parse inline scripts without executing browser code.
const scriptPattern = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
for (const match of html.matchAll(scriptPattern)) {
  const code = match[2].trim();
  if (!code) continue;
  inlineScripts += 1;
  try {
    new vm.Script(code, { filename: "index.html:inline-script-" + inlineScripts });
  } catch (error) {
    failures.push("Inline script " + inlineScripts + ": " + error.stack);
  }
}

for (const id of ["main", "file", "fn", "info", "toast", "fcam", "camfinish", "camclear", "cammode", "cammodewrap"]) {
  if (!html.includes('id="' + id + '"') && !html.includes("id='" + id + "'")) {
    failures.push("Required application element is missing: #" + id);
  }
}

for (const feature of ["loadOpenCV", "detectScanCorners", "getPerspectiveTransform", "warpPerspective", "scan-crop-overlay", "reviewScannedPages", "rotateScanImage", "scan-review-overlay"]) {
  if (!html.includes(feature)) failures.push("Smart scanner implementation is missing: " + feature);
}

for (const feature of ["openOcrReview", "ocrReviewText", "ocrReviewSave", "ocrReviewDownload", "مراجعة النص"]) {
  if (!html.includes(feature)) failures.push("OCR text review feature is missing: " + feature);
}

for (const feature of ["ocrReviewPrev", "ocrReviewNext", "ocrReviewCounter", "ocrReviewAllCopy", "ocrReviewAllDownload", "allOcrReviewText", "ocrReviewMove"]) {
  if (!html.includes(feature)) failures.push("Multi-page OCR review feature is missing: " + feature);
}

for (const feature of ['id="exportDocx"', 'id="exportXlsx"', '/api/export/docx', '/api/export/xlsx', 'لن يُرسل ملف PDF الأصلي']) {
  if (!html.includes(feature)) failures.push("Word/Excel export actions are missing: " + feature);
}

for (const feature of ['id="pdfSearchBtn"', 'id="pdfSearchInput"', 'runPdfSearch()', 'getTextContent()', 'لا يرسل ملفاتك إلى الخادم']) {
  if (!html.includes(feature)) failures.push("Local PDF text search is missing: " + feature);
}

for (const feature of ['id="secureRedactPdf"', '/api/pdf/redact', 'regions', 'تطبيق الحجب النهائي', 'لن يتغير الملف الأصلي']) {
  if (!html.includes(feature)) failures.push("Permanent PDF redaction UI is missing: " + feature);
}

for (const feature of ["ocrReviewSaveCurrent()", "v:2", "ocr:Array.isArray(p.ocr)", "tables:Array.isArray(p.tables)", "searchablePdf", "/api/pdf/searchable", "ocr_data", "سيتم إرسال نسخة PDF الحالية"]) {
  if (!html.includes(feature)) failures.push("OCR project persistence is missing: " + feature);
}

for (const feature of ["dsUploadResumable", "uploadType=resumable", "Content-Range", "dsSha256", "alfalqiSha256", "dsFindExisting", "dsGetPublicPermission", "X-Upload-Content-Length"]) {
  if (!html.includes(feature)) failures.push("Google Drive reliability feature is missing: " + feature);
}

for (const feature of ["fontWarmupPromise", "document.fonts.load", "الفلقي PDF ١٢٣ ٠٤٥ abc 123"]) {
  if (!html.includes(feature)) failures.push("Offline font warm-up is missing: " + feature);
}

for (const feature of ['rel="manifest"', 'apple-mobile-web-app-capable', 'pwaInstall', 'serviceWorker.register("./sw.js"', 'beforeinstallprompt']) {
  if (!html.includes(feature)) failures.push("PWA install support is missing: " + feature);
}

for (const feature of ['id="pwaInstallHelp"', 'pwaHelpClose', 'تحميل التطبيق', 'role="dialog"', 'إضافة إلى الشاشة الرئيسية']) {
  if (!html.includes(feature)) failures.push("Accessible PWA install instructions are missing: " + feature);
}
const installButtonAt = html.indexOf('id="pwaInstall"');
const toolbarAt = html.indexOf('<div class="hr2">');
if (installButtonAt < 0 || (toolbarAt >= 0 && installButtonAt > toolbarAt)) {
  failures.push("PWA install action must be placed in the primary header, outside the editing toolbar.");
}

for (const feature of ['scheduleAutosave', 'indexedDB.open(DB_NAME,1)', 'جلسة محفوظة تلقائيًا', 'لن تُرسل الملفات إلى أي خادم', 'MAX_BYTES=80*1024*1024', 'autosaveStatus']) {
  if (!html.includes(feature)) failures.push("Local autosave and recovery is missing: " + feature);
}

for (const feature of ["MAX_PROJECT_FILE_BYTES", "MAX_PROJECT_DECODED_BYTES", "decodeProjectBase64", "data.docs.length>20", "data.pages.length>1000", "PDF-", "p.i<1", "بقي الملف المفتوح كما هو"]) {
  if (!html.includes(feature)) failures.push("AFQ project import protection is missing: " + feature);
}

const manifestPath = path.join(root, "manifest.webmanifest");
try {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (manifest.start_url !== "./" || manifest.scope !== "./" || manifest.display !== "standalone") {
    failures.push("PWA manifest has an unexpected start URL, scope, or display mode.");
  }
  for (const icon of manifest.icons || []) {
    const iconPath = path.resolve(root, icon.src);
    if (!iconPath.startsWith(root + path.sep) || !fs.existsSync(iconPath)) {
      failures.push("PWA manifest icon is missing or outside the project: " + icon.src);
      continue;
    }
    const bytes = fs.readFileSync(iconPath);
    const png = bytes.length >= 24 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    const width = png ? bytes.readUInt32BE(16) : 0;
    const height = png ? bytes.readUInt32BE(20) : 0;
    if (icon.type === "image/png" && (!png || (icon.sizes !== "any" && icon.sizes !== width + "x" + height))) {
      failures.push("PWA icon is not a valid PNG with the declared dimensions: " + icon.src);
    }
  }
} catch (error) {
  failures.push("PWA manifest is missing or invalid JSON: " + error.message);
}

try {
  const sw = fs.readFileSync(path.join(root, "sw.js"), "utf8");
  new vm.Script(sw, { filename: "sw.js" });
  if (!sw.includes("/api") || !sw.includes("alfalqi-pdf-") || !sw.includes("request.method !== \"GET\"")) {
    failures.push("Service worker must exclude API requests and use a versioned cache namespace.");
  }
} catch (error) {
  failures.push("Service worker is missing or has invalid syntax: " + error.message);
}



if (failures.length) {
  console.error("Frontend checks failed:");
  for (const failure of failures) console.error("- " + failure);
  process.exit(1);
}

console.log("Frontend checks passed: " + inlineScripts + " inline scripts parsed; local assets resolved.");