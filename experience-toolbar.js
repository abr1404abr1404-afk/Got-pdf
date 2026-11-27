(() => {
  "use strict";
  const init = () => {
    const toolbar = document.querySelector("header .hr2");
    if (!toolbar || toolbar.dataset.hybridReady === "1") return;
    toolbar.dataset.hybridReady = "1";

    const groups = [
      { id: "file", label: "ملف", ids: ["ud","rd","dshare","save","file","fimg","fcam","camfinish","camclear","cammodewrap","ocb","imgfit","info"] },
      { id: "edit", label: "تحرير", ids: ["txt","edt","img","sig","bcb","ann"] },
      { id: "pages", label: "الصفحات", ids: ["pn","spl","thumbs","mrg","compress"] },
      { id: "smart", label: "OCR والذكاء", ids: ["ocb","ai","pdfSearchBtn","pdfAutoFill"] },
      { id: "view", label: "العرض", ids: ["zo","zv","zi"] },
      { id: "more", label: "المزيد", ids: ["tls","hlpb"] }
    ];
    const idOf = el => el.id || el.querySelector?.("input[id],select[id]")?.id || "";
    const flat = [];
    [...toolbar.children].forEach(node => {
      if (node.classList.contains("grp")) flat.push(...node.children);
      else flat.push(node);
    });
    const byId = new Map(flat.map(el => [idOf(el), el]).filter(([id]) => id));
    const used = new Set();
    const nav = document.createElement("div");
    nav.className = "hybrid-tabs";
    nav.setAttribute("role", "tablist");
    nav.setAttribute("aria-label", "أقسام أدوات الفلقي");
    const panels = document.createElement("div");
    panels.className = "hybrid-panels";

    groups.forEach((group, index) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "hybrid-tab";
      tab.id = "hybrid-tab-" + group.id;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "hybrid-panel-" + group.id);
      tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
      tab.tabIndex = index === 0 ? 0 : -1;
      tab.textContent = group.label;
      nav.append(tab);

      const panel = document.createElement("div");
      panel.className = "hybrid-panel";
      panel.id = "hybrid-panel-" + group.id;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.hidden = index !== 0;
      group.ids.forEach(id => {
        const el = byId.get(id);
        if (el && !used.has(el)) {
          panel.append(el);
          used.add(el);
        }
      });
      panels.append(panel);
      tab.addEventListener("click", () => activate(index));
    });

    const overflow = flat.filter(el => !used.has(el));
    if (overflow.length) {
      const morePanel = panels.querySelector("#hybrid-panel-more");
      overflow.forEach(el => morePanel.append(el));
    }
    toolbar.replaceChildren(nav, panels);

    function activate(index) {
      [...nav.children].forEach((tab, i) => {
        const active = i === index;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      [...panels.children].forEach((panel, i) => { panel.hidden = i !== index; });
    }
    nav.addEventListener("keydown", event => {
      if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
      event.preventDefault();
      const current = [...nav.children].findIndex(tab => tab.getAttribute("aria-selected") === "true");
      const next = event.key === "Home" ? 0 : event.key === "End" ? groups.length - 1 :
        (current + (event.key === "ArrowLeft" ? 1 : -1) + groups.length) % groups.length;
      activate(next);
      nav.children[next].focus();
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
