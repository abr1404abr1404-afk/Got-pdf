import { chromium, devices } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const server = spawn("python", ["-m", "http.server", "4173", "--bind", "127.0.0.1"], { stdio: "ignore" });
const base = "http://127.0.0.1:4173/";
try {
  await delay(900);
  const browser = await chromium.launch({ headless: true });
  const profiles = [
    { name: "mobile-small", viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
    { name: "mobile-large", viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 },
    { name: "desktop", viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 }
  ];
  const failures = [];
  for (const profile of profiles) {
    const context = await browser.newContext({ ...profile, locale: "ar-SA", colorScheme: "light" });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".hybrid-tabs", { timeout: 10000 });
    const tabs = page.locator(".hybrid-tab");
    const count = await tabs.count();
    if (count !== 6) failures.push(profile.name + ": expected 6 tabs, got " + count);
    for (let i = 0; i < count; i++) {
      await tabs.nth(i).evaluate(el => el.click());
      const selected = await tabs.nth(i).getAttribute("aria-selected");
      const panelId = await tabs.nth(i).getAttribute("aria-controls");
      const visible = await page.locator("#" + panelId).isVisible();
      if (selected !== "true" || !visible) failures.push(profile.name + ": tab " + i + " did not activate its panel");
    }
    await tabs.first().evaluate(el => el.click());
    const dimensions = await page.evaluate(() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth,
      toolbar: document.querySelector("header .hr2")?.getBoundingClientRect().width,
      tabs: document.querySelector(".hybrid-tabs")?.getBoundingClientRect().width,
      panel: document.querySelector(".hybrid-panel:not([hidden])")?.getBoundingClientRect().width,
      rtl: getComputedStyle(document.documentElement).direction,
      tabHeight: document.querySelector(".hybrid-tab")?.getBoundingClientRect().height,
      tabHitTarget: (() => { const el = document.querySelector(".hybrid-tab"); const r = el?.getBoundingClientRect(); const hit = r && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return hit?.closest(".hybrid-tab")?.id || hit?.id || hit?.className || null; })()
    }));
    if (dimensions.document > dimensions.viewport + 2) failures.push(profile.name + ": horizontal page overflow " + JSON.stringify(dimensions));
    if (dimensions.tabHeight < 38) failures.push(profile.name + ": tab touch target is too small " + JSON.stringify(dimensions));
    if (pageErrors.length) failures.push(profile.name + ": browser errors " + pageErrors.join(" | "));
    await page.screenshot({ path: "artifacts/ui-" + profile.name + ".png", fullPage: true });
    console.log(profile.name, JSON.stringify(dimensions));
    await context.close();
  }
  await browser.close();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
  } else {
    console.log("HYBRID_UI_EMULATION=PASS");
  }
} finally {
  server.kill("SIGTERM");
}
