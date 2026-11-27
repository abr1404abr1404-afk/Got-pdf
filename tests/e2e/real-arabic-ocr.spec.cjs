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
    const ocrConfig = await page.evaluate(() => ({
      ocrBaseType: typeof window.ALFALQI_OCR_API_BASE,
      ocrBaseValue: String(window.ALFALQI_OCR_API_BASE ?? "")
    }));
    await page.locator("#hybrid-tab-smart").click();
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
      cer_vs_embedded_pdf_text: pdfCer, edit_persisted: true,
      extracted_text: originalPdfText.slice(0, 12000)});
    await pdfPage.close();

    // Path B: real page image upload -> image-to-PDF -> browser OCR -> review/edit/save.
    const imagePage = await context.newPage();
    activePage = imagePage;
    imagePage.setDefaultTimeout(timeout);
    imagePage.on("dialog", dialog => dialog.accept());
    imagePage.on("pageerror", error => failures.push("image pageerror: " + error.message));
    await imagePage.goto(base, {waitUntil: "domcontentloaded", timeout: 60000});
    await imagePage.locator("#hybrid-tab-smart").click();
    await imagePage.locator("#ocb").click();
    await imagePage.locator("#focr").setInputFiles(path.join(fixture, "real-dubai-law-page1.png"));
    await imagePage.getByRole("button", {name: "مراجعة النص"}).first().waitFor({state: "visible", timeout});
    // Validate the visual replacement layer before opening the review modal,
    // which intentionally covers the page and intercepts pointer events.
    await imagePage.locator(".det").first().waitFor({state:"visible",timeout});
    await imagePage.locator(".det").first().click();
    const imageOverlay=imagePage.locator(".ov.ocr-line").first();
    await imageOverlay.waitFor({state:"visible",timeout});
    const overlayText=imageOverlay.locator(".t");
    const beforeBox=await imageOverlay.boundingBox();
    const beforeFont=await overlayText.evaluate(el=>getComputedStyle(el).fontSize);
    const shaping=await overlayText.evaluate(el=>({
      direction:getComputedStyle(el).direction,
      textAlign:getComputedStyle(el).textAlign,
      unicodeBidi:getComputedStyle(el).unicodeBidi,
      ligatures:getComputedStyle(el).fontVariantLigatures
    }));
    if(shaping.direction!=="rtl"||shaping.textAlign!=="right"||shaping.unicodeBidi==="normal")
      throw new Error("Arabic OCR replacement is not explicitly RTL-shaped: "+JSON.stringify(shaping));
    await overlayText.fill("اختبار استبدال النص العربي مع الحفاظ على اتجاه الكتابة والتنسيق");
    const after=await imageOverlay.evaluate(el=>({
      width:el.getBoundingClientRect().width,
      textWidth:el.querySelector(".t").getBoundingClientRect().width,
      fontSize:getComputedStyle(el).fontSize,
      direction:getComputedStyle(el.querySelector(".t")).direction
    }));
    if(!beforeBox||!Number.isFinite(after.width)||after.width<8||after.direction!=="rtl")
      throw new Error("Arabic replacement box or direction is invalid: "+JSON.stringify(after));
    if(Math.abs(after.width-beforeBox.width)>2)
      throw new Error("Editing Arabic text unexpectedly changed the original line box width");
    results.push({case:"arabic_image_text_replacement_shaping_and_width",status:"passed",
      original_box_width:beforeBox.width,edited_box_width:after.width,
      original_font_size:beforeFont,edited_font_size:after.fontSize,shaping});
    await imageOverlay.locator(".t").evaluate(el=>{el.blur();});
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
      cer_vs_embedded_pdf_text: imageCer, edit_persisted: true,
      extracted_text: originalImageText.slice(0, 12000)});

    fs.writeFileSync("browser-ocr-e2e-results.json", JSON.stringify({
      engine: "Tesseract.js in browser",
      source: "Public Dubai government legal PDF, page 1 and rasterized image",
      ocr_config: ocrConfig, results, failures
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
