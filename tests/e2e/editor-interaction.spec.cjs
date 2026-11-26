const { chromium } = require("playwright");
const path = require("node:path");

const base = process.env.APP_URL || "http://127.0.0.1:4173";
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({
      viewport:{width:390,height:844}, deviceScaleFactor:2,
      isMobile:true, hasTouch:true, acceptDownloads:true
    });
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    const errors=[];
    page.on("pageerror",e=>errors.push(e.message));
    await page.goto(base,{waitUntil:"domcontentloaded"});
    await page.locator("#file").setInputFiles(path.join(process.cwd(),"tests/e2e/fixtures/real-dubai-law.pdf"));
    await page.locator(".wrap").first().waitFor({state:"visible",timeout:90000});
    const wrap=page.locator(".wrap").first();
    await page.locator("#txt").click();
    const wr=await wrap.boundingBox();
    await wrap.click({position:{x:Math.round(wr.width*.35),y:Math.round(wr.height-70)}});
    const overlay=page.locator(".ov").last();
    await overlay.waitFor({state:"visible"});
    const text=overlay.locator(".t");
    await text.fill("اختبار تحريك النص أسفل الصفحة");
    await text.press("End");
    await page.locator("body").click({position:{x:8,y:8},force:true}).catch(()=>{});
    await overlay.click({force:true});
    const toolbar=overlay.locator(".tb");
    await toolbar.waitFor({state:"visible"});
    const checkToolbar=async()=>{
      const r=await toolbar.boundingBox();
      const vp=page.viewportSize();
      if(!r||r.x < -1||r.y < -1||r.x+r.width>vp.width+1||r.y+r.height>vp.height+1)
        throw new Error("Text toolbar is outside the visible mobile viewport: "+JSON.stringify({r,vp}));
      const pos=await toolbar.evaluate(el=>getComputedStyle(el).position);
      if(pos!=="fixed") throw new Error("Toolbar is not viewport-anchored: "+pos);
    };
    await checkToolbar();
    for(let i=0;i<6;i++) await page.locator("#zi").click();
    await page.waitForTimeout(400);
    await page.locator(".ov").last().click({force:true});
    const zoomedToolbar=page.locator(".ov.sel .tb").first();
    await zoomedToolbar.waitFor({state:"visible"});
    const r=await zoomedToolbar.boundingBox(),vp=page.viewportSize();
    if(!r||r.x < -1||r.y < -1||r.x+r.width>vp.width+1||r.y+r.height>vp.height+1)
      throw new Error("Zoomed toolbar overlaps/leaves viewport: "+JSON.stringify({r,vp}));
    const move=page.locator(".ov.sel .m").first();
    await move.waitFor({state:"visible"});
    const mr=await move.boundingBox();
    const wr2=await wrap.boundingBox();
    await page.mouse.move(mr.x+mr.width/2,mr.y+mr.height/2);
    await page.mouse.down();
    await page.mouse.move(wr2.x+wr2.width-25,wr2.y+wr2.height-12,{steps:12});
    await page.mouse.up();
    const moved=await overlay.boundingBox();
    const finalWrap=await wrap.boundingBox();
    if(!moved||moved.x<finalWrap.x-1||moved.y<finalWrap.y-1||
       moved.x+moved.width>finalWrap.x+finalWrap.width+2||
       moved.y+moved.height>finalWrap.y+finalWrap.height+2)
      throw new Error("Dragged text escaped the PDF page bounds near the bottom: "+JSON.stringify({moved,finalWrap}));
    if(errors.length) throw new Error("Browser errors: "+errors.join(" | "));
    console.log(JSON.stringify({status:"passed",viewport:page.viewportSize(),toolbar_fixed:true,
      toolbar_inside_viewport:true,zoom_test:"passed",bottom_drag_clamped:true,errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
