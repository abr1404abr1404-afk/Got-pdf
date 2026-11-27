import { chromium, devices } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const server = spawn("python", ["-m", "http.server", "4173", "--bind", "127.0.0.1"], { stdio: "ignore" });
const base = "http://127.0.0.1:4173/";
try {
  async function waitForServer() {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(base);
      if (response.ok) return;
    } catch {}
    await delay(200);
  }
  throw new Error("Local test server did not become ready within 15 seconds.");
}
await waitForServer();
  const browser = await chromium.launch({ headless: true });
  const profiles = [
    { name: "mobile-small", viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
    { name: "mobile-large", viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 },
    { name: "desktop", viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false, deviceScaleFactor: 1 }
  ];
  const failures = [];
  for (const profile of profiles) {
    const device = profile.isMobile ? devices["iPhone 13"] : {};
    const context = await browser.newContext({
      ...device,
      viewport: profile.viewport,
      isMobile: profile.isMobile,
      hasTouch: profile.hasTouch,
      deviceScaleFactor: profile.deviceScaleFactor,
      locale: "ar-SA",
      colorScheme: "light"
    });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".hybrid-tabs", { timeout: 10000 });
    const tabs = page.locator(".hybrid-tab");
    const count = await tabs.count();
    if (count !== 6) failures.push(profile.name + ": expected 6 tabs, got " + count);
    for (let i = 0; i < count; i++) {
      if (profile.hasTouch) await tabs.nth(i).tap();
      else await tabs.nth(i).click();
      const selected = await tabs.nth(i).getAttribute("aria-selected");
      const panelId = await tabs.nth(i).getAttribute("aria-controls");
      const visible = await page.locator("#" + panelId).isVisible();
      if (selected !== "true" || !visible) failures.push(profile.name + ": tab " + i + " did not activate its panel");
    }
    if (profile.hasTouch) await tabs.first().tap();
    else await tabs.first().click();
    const dimensions = await page.evaluate(() => {
      const toolbar = document.querySelector("header .hr2");
      const tabs = document.querySelector(".hybrid-tabs");
      const panels = document.querySelector(".hybrid-panels");
      const panel = document.querySelector(".hybrid-panel:not([hidden])");
      const tab = document.querySelector(".hybrid-tab");
      const rect = tab?.getBoundingClientRect();
      const hit = rect && document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return {
        viewport: innerWidth,
        visualViewport: visualViewport?.width,
        clientWidth: document.documentElement.clientWidth,
        screenWidth: screen.width,
        devicePixelRatio,
        document: document.documentElement.scrollWidth,
        toolbar: toolbar?.getBoundingClientRect().width,
        tabs: tabs?.getBoundingClientRect().width,
        panels: panels?.getBoundingClientRect().width,
        panel: panel?.getBoundingClientRect().width,
        panelScroll: panel?.scrollWidth,
        panelClient: panel?.clientWidth,
        rtl: getComputedStyle(document.documentElement).direction,
        tabHeight: tab?.getBoundingClientRect().height,
        tabHitTarget: hit?.closest(".hybrid-tab")?.id || hit?.id || hit?.className || null
      };
    });
    const expectedWidth = profile.viewport.width;
    if (Math.abs(dimensions.viewport - expectedWidth) > 1 || Math.abs(dimensions.clientWidth - expectedWidth) > 1) {
      failures.push(profile.name + ": emulated viewport mismatch " + JSON.stringify(dimensions));
    }
    if (dimensions.document > expectedWidth + 2) failures.push(profile.name + ": horizontal page overflow " + JSON.stringify(dimensions));
    if (dimensions.toolbar > expectedWidth + 2 || dimensions.panel > dimensions.toolbar + 2) {
      failures.push(profile.name + ": toolbar/panel escapes viewport " + JSON.stringify(dimensions));
    }
    if (dimensions.tabHeight < 38) failures.push(profile.name + ": tab touch target is too small " + JSON.stringify(dimensions));
    if (profile.hasTouch && dimensions.tabHitTarget !== "hybrid-tab-file") failures.push(profile.name + ": tab center is obstructed " + JSON.stringify(dimensions));
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
