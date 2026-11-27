import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

function makePdf(text) {
  const safe = text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const stream = "BT /F1 24 Tf 72 700 Td (" + safe + ") Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Length " + Buffer.byteLength(stream, "utf8") + " >>\nstream\n" + stream + "\nendstream"
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((body, index) => {
    offsets.push(Buffer.byteLength(pdf, "utf8"));
    pdf += (index + 1) + " 0 obj\n" + body + "\nendobj\n";
  });
  const xref = Buffer.byteLength(pdf, "utf8");
  pdf += "xref\n0 " + (objects.length + 1) + "\n0000000000 65535 f \n";
  for (let i = 1; i < offsets.length; i++) pdf += String(offsets[i]).padStart(10, "0") + " 00000 n \n";
  pdf += "trailer\n<< /Size " + (objects.length + 1) + " /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF";
  return Buffer.from(pdf, "utf8");
}

const server = spawn("python", ["-m", "http.server", "4173", "--bind", "127.0.0.1"], { stdio: "ignore" });
let browser;
try {
  const deadline = Date.now() + 15000;
  let ready = false;
  while (Date.now() < deadline) {
    try {
      const response = await fetch("http://127.0.0.1:4173/");
      if (response.ok) { ready = true; break; }
    } catch {}
    await delay(200);
  }
  if (!ready) throw new Error("Local test server did not become ready within 15 seconds.");
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const apiCompareRequests = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.url().includes("/api/pdf/compare")) apiCompareRequests.push(request.url());
  });
  await page.goto("http://127.0.0.1:4173/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.pdfjsLib?.getDocument && window.PDFLib?.PDFDocument, { timeout: 30000 });
  await page.locator("#file").setInputFiles({
    name: "original.pdf",
    mimeType: "application/pdf",
    buffer: makePdf("Version one")
  });
  await page.waitForFunction(() => document.querySelectorAll(".wrap").length > 0, { timeout: 20000 });
  await page.locator("#comparePdfFile").setInputFiles({
    name: "revised.pdf",
    mimeType: "application/pdf",
    buffer: makePdf("Version two plus added")
  });
  await page.getByText("مقارنة بصرية ونصية للملفين", { exact: true }).waitFor({ timeout: 30000 });
  await page.getByText("نصوص أُضيفت أو تغيرت:", { exact: false }).waitFor({ timeout: 30000 });
  const result = await page.evaluate(() => ({
    title: document.body.innerText.includes("مقارنة بصرية ونصية للملفين"),
    overview: document.body.innerText.includes("revised.pdf"),
    previews: [...document.querySelectorAll('img[alt*="موضع الاختلاف"]')].length,
    addedText: document.body.innerText.includes("Version two plus added"),
    localNotice: document.body.innerText.includes("لم يتم رفع الملفين إلى الخادم")
  }));
  if (!result.title || !result.overview || result.previews < 2 || !result.addedText || !result.localNotice) {
    throw new Error("Local PDF comparison assertions failed: " + JSON.stringify(result));
  }
  if (apiCompareRequests.length) throw new Error("Local comparison unexpectedly called the server: " + apiCompareRequests.join(", "));
  if (errors.length) throw new Error("Browser errors: " + errors.join(" | "));
  console.log("LOCAL_PDF_COMPARE=PASS", JSON.stringify(result));
  await context.close();
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
