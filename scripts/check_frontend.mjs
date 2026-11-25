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

for (const feature of ['id="dshare" class="hb share-action"', 'مشاركة PDF', 'aria-label="مشاركة ملف PDF"', 'showToolHint.h=setTimeout(()=>{h.classList.remove("on");h.textContent=""},1800)', 'toast.h=setTimeout(()=>{t.style.display="none";t.textContent=""},2000)']) {
  if (!html.includes(feature)) failures.push("PDF sharing styling or two-second tool hints are missing: " + feature);
}

for (const feature of [
  'id="pdfVersionModal"',
  'id="pdfVersionSnapshot"',
  'id="pdfVersionAutoToggle"',
  'indexedDB.open("alfalqi-pdf-versions",1)',
  'requestPdfHistoryConsent()',
  'restorePdfVersion(id)',
  'downloadPdfVersion(id)',
  'تنزيل نسخة احتياطية',
  'size>limit',
  'keep=rows.slice(0,4)',
  'لن تُرفع هذه النسخ إلى الخادم'
]) {
  if (!html.includes(feature)) failures.push("Local PDF version history is missing: " + feature);
}
for (const feature of [
  'id="pdfVersionCompare"',
  'id="pdfVersionCompareStatus"',
  'id="pdfVersionCompareResult"',
  'compareSelectedPdfVersions()',
  'selectedPdfCompareIds',
  'sharedScale=Math.min(1,Math.sqrt(1500000/',
  'pdfCompareLineDifference(a.lines,b.lines)',
  'pdfCompareThumbnail(a,box)',
  'معاينة منطقة الاختلاف',
  'استعادة النسخة الأولى',
  'استعادة النسخة الثانية',
  'المقارنة المرئية محدودة إلى 30 صفحة'
]) {
  if (!html.includes(feature)) failures.push("Local PDF version comparison is missing or incomplete: " + feature);
}
const compareStart = html.indexOf("async function compareSelectedPdfVersions()");
const compareEnd = html.indexOf('async function downloadPdfVersion', compareStart);
if (compareStart < 0 || compareEnd < 0) {
  failures.push("Local PDF comparison implementation is missing.");
} else {
  const compareCode = html.slice(compareStart, compareEnd);
  if (compareCode.includes("fetch(") || compareCode.includes("XMLHttpRequest")) {
    failures.push("Local PDF version comparison must not upload the saved PDFs.");
  }
  if (!compareCode.includes("pdfjsLib.getDocument") || !compareCode.includes("pdfVersionDB.all()")) {
    failures.push("Local PDF comparison must read saved versions from IndexedDB with PDF.js.");
  }
}
const versionModalAt = html.indexOf('<div id="pdfVersionModal"');
const nextModalAt = html.indexOf('<div id="pdfObjectInspector"', versionModalAt);
if (versionModalAt < 0 || nextModalAt < 0) {
  failures.push("PDF version history dialog is missing or misplaced.");
} else {
  const modalMarkup = html.slice(versionModalAt, nextModalAt);
  const openDivs = (modalMarkup.match(/<div\b/gi) || []).length;
  const closeDivs = (modalMarkup.match(/<\/div\s*>/gi) || []).length;
  if (openDivs !== closeDivs) failures.push("PDF version history dialog has unbalanced div elements.");
}

for (const feature of ['id="ann" type="button" title="يفتح لوحة مستقلة للرموز والعلامات والقلم، ثم اختر الأداة المطلوبة"', 'id="annToolsClose"', 'id="toolHint"', 'role="toolbar" aria-label="لوحة الرموز والعلامات والقلم"', 'body.ann-tools-open #anp{display:flex}', 'const menuHelp=new Map(MENU.map', 'showToolHint(description)', 'id="ack"', 'id="axx"', 'id="aci"', 'id="acif"', 'id="asq"', 'id="asqf"', 'id="pdfAutoFill"', 'id="pdfFillModal"', 'id="aw"', 'id="awv"', 'id="pdfFillImportBtn"', 'id="pdfFillTemplateBtn"', "function annNode", "drawEllipse", "field.setText", "pdfFieldAutocomplete", "JSON.parse(await file.text())"]) {
  if (!html.includes(feature)) failures.push("PDF answer marks, drawing tools, or form autofill are missing: " + feature);
}

for (const feature of ["ocrReviewConfidence", "متوسط ثقة المحرك", "أسطر منخفضة الثقة"]) {
  if (!html.includes(feature)) failures.push("OCR confidence review guidance is missing: " + feature);
}

for (const feature of ["X-Conversion-Text-Order", "quality.order", "ترتيب الكلمات", "orderWarning"]) {
  if (!html.includes(feature)) failures.push("PDF-to-Word reading-order quality feedback is missing: " + feature);
}

for (const feature of ["pdfToDocxLayout", "pdfImageAnalyze", "pdfImageManager", "/api/pdf/unlock", "/api/convert/pdf-to-docx", "/api/pdf/images/list", "/api/pdf/images/edit", "openedPdfBytes"]) {
  if (!html.includes(feature)) failures.push("PDF password, layout conversion, or image editing UI is missing: " + feature);
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



if (!html.includes("ann-tools-head")) failures.push("Annotation panel must keep its close control in a dedicated header.");

if (!html.includes("function setAnnotationPanelOpen") || !html.includes('menu.classList.toggle("on",open)')) failures.push("Menu panels must toggle open and closed from their trigger buttons.");
if (!html.includes("return true;") || !html.includes("return false;") || !html.includes("restored!==true")) failures.push("Project recovery must verify successful project import before reporting success.");

if (failures.length) {
  console.error("Frontend checks failed:");
  for (const failure of failures) console.error("- " + failure);
  process.exit(1);
}

console.log("Frontend checks passed: " + inlineScripts + " inline scripts parsed; local assets resolved.");