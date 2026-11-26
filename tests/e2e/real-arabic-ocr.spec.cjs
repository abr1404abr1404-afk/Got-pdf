const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const base = process.env.APP_URL || "http://127.0.0.1:4173";
const fixture = path.join(process.cwd(), "tests/e2e/fixtures");
const timeout = 240000;

function normalize(s) {
  return (s || "").normalize("NFC")
    .replace(/[\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/\s+/g, "");
}
function editDistance(a, b) {
  let prev = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(cur[j-1] + 1, prev[j] + 1, prev[j-1] + (a[i-1] === b[j-1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}
function cer(reference, actual) {
  const a = normalize(reference), b = normalize(actual);
  return a.length ? Number((editDistance(a, b) / a.length).toFixed(4)) : null;
}

let activePage = null;
const results = [];
const failures = [];
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({acceptDownloads: true});
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    page.on("dialog", dialog => dialog.accept());
    page.on("pageerror", error => failures.push("pageerror: " + error.message));
    page.on("console", message => {
      if (message.type() === "error") failures.push("console: " + message.text().slice(0, 500));
    });
    await page.goto(base, {waitUntil: "domcontentloaded", timeout: 60000});
    await page.locator("#ocb").waitFor({state: "visible"});

    // Path A: real PDF upload -> render page -> browser OCR -> review/edit/save.
    const pdfPage = await context.newPage();
    activePage = pdfPage;
    pdfPage.setDefaultTimeout(timeout);
    pdfPage.on("dialog", dialog => dialog.accept());
    pdfPage.on("pageerror", error => failures.push("PDF pageerror: " + error.message));
    await pdfPage.goto(base, {waitUntil: "domcontentloaded", timeout: 60000});
    await pdfPage.locator("#file").setInputFiles(path.join(fixture, "real-dubai-law.pdf"));
    await pdfPage.locator(".wrap").first().waitFor({state: "visible", timeout: 90000});
    await pdfPage.getByRole("button", {name: /OCR\s*\/\s*تحليل النص/}).first().click();
    await pdfPage.getByRole("button", {name: "مراجعة النص"}).first().waitFor({state: "visible", timeout});
    await pdfPage.getByRole("button", {name: "مراجعة النص"}).first().click();
    const pdfText = pdfPage.locator("#ocrReviewText");
    await pdfText.waitFor({state: "visible"});
    const originalPdfText = await pdfText.inputValue();
    if (normalize(originalPdfText).length < 10) throw new Error("PDF OCR returned too little Arabic text");
    const pdfReference = fs.readFileSync(path.join(fixture, "real-dubai-law-page1.txt"), "utf8");
    const pdfCer = cer(pdfReference, originalPdfText);
    const editedPdfText = originalPdfText.replace(/\S/, "$& [UI-EDIT-VERIFIED]");
    await pdfText.fill(editedPdfText);
    await pdfPage.locator("#ocrReviewSave").click();
    await pdfPage.getByRole("button", {name: "مراجعة النص"}).first().click();
    const persistedPdfText = await pdfPage.locator("#ocrReviewText").inputValue();
    if (!persistedPdfText.includes("[UI-EDIT-VERIFIED]")) throw new Error("PDF OCR review edit did not persist");
    results.push({case: "real_pdf_upload_browser_ocr_review_edit", status: "passed",
      extracted_chars: originalPdfText.length, arabic_chars: (originalPdfText.match(/[\u0600-\u06ff]/g)||[]).length,
      cer_vs_embedded_pdf_text: pdfCer, edit_persisted: true});
    await pdfPage.close();

    // Path B: real page image upload -> image-to-PDF -> browser OCR -> review/edit/save.
    const imagePage = await context.newPage();
    activePage = imagePage;
    imagePage.setDefaultTimeout(timeout);
    imagePage.on("dialog", dialog => dialog.accept());
    imagePage.on("pageerror", error => failures.push("image pageerror: " + error.message));
    await imagePage.goto(base, {waitUntil: "domcontentloaded", timeout: 60000});
    await imagePage.locator("#ocb").click();
    await imagePage.locator("#focr").setInputFiles(path.join(fixture, "real-dubai-law-page1.png"));
    await imagePage.getByRole("button", {name: "مراجعة النص"}).first().waitFor({state: "visible", timeout});
    await imagePage.getByRole("button", {name: "مراجعة النص"}).first().click();
    const imageText = imagePage.locator("#ocrReviewText");
    await imageText.waitFor({state: "visible"});
    const originalImageText = await imageText.inputValue();
    if (normalize(originalImageText).length < 10) throw new Error("Image OCR returned too little Arabic text");
    const imageCer = cer(pdfReference, originalImageText);
    const editedImageText = originalImageText.replace(/\S/, "$& [IMAGE-EDIT-VERIFIED]");
    await imageText.fill(editedImageText);
    await imagePage.locator("#ocrReviewSave").click();
    await imagePage.getByRole("button", {name: "مراجعة النص"}).first().click();
    const persistedImageText = await imagePage.locator("#ocrReviewText").inputValue();
    if (!persistedImageText.includes("[IMAGE-EDIT-VERIFIED]")) throw new Error("Image OCR review edit did not persist");
    results.push({case: "real_image_upload_browser_ocr_review_edit", status: "passed",
      extracted_chars: originalImageText.length, arabic_chars: (originalImageText.match(/[\u0600-\u06ff]/g)||[]).length,
      cer_vs_embedded_pdf_text: imageCer, edit_persisted: true});

    fs.writeFileSync("browser-ocr-e2e-results.json", JSON.stringify({
      engine: "Tesseract.js in browser",
      source: "Public Dubai government legal PDF, page 1 and rasterized image",
      results, failures
    }, null, 2));
    console.log(JSON.stringify({results, failures}, null, 2));
    if (failures.length) throw new Error("Browser console/page errors detected: " + failures.join(" | "));
  } finally {
    await browser.close();
  }
})().catch(async error => {
  console.error(error);
  try {
    if (activePage && !activePage.isClosed()) {
      await activePage.screenshot({ path: "browser-ocr-failure.png", fullPage: true }).catch(() => {});
    }
    fs.writeFileSync("browser-ocr-e2e-results.json", JSON.stringify({
      engine: "Tesseract.js in browser",
      results,
      failures,
      fatal_error: { name: error.name, message: error.message, stack: error.stack }
    }, null, 2));
  } catch (reportError) { console.error("Could not write failure report:", reportError); }
  process.exitCode = 1;
});
