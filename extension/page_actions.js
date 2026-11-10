/* Injected into an attached tab. Must stay free of extension globals. */

function chrollerFrameSkipped() {
  if (window.top === window) return false;
  try {
    void window.parent.document;
    return false;
  } catch (err) {
    return true;
  }
}

function chrollerVisible(el) {
  const style = getComputedStyle(el);
  if (style.visibility === "hidden" || style.display === "none") return false;
  const rect = el.getBoundingClientRect();
  return rect.width >= 1 && rect.height >= 1;
}

function chrollerName(el) {
  try {
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const text = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.innerText || "")
        .join(" ")
        .trim();
      if (text) return text.slice(0, 120);
    }
  } catch (err) {
    /* ignore broken labelled-by ids */
  }
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.slice(0, 120);
  try {
    if (el.labels && el.labels.length) {
      const label = (el.labels[0].innerText || "").trim();
      if (label) return label.slice(0, 120);
    }
  } catch (err) {
    /* labels can throw for detached nodes */
  }
  if (el.getAttribute("placeholder")) return el.getAttribute("placeholder").slice(0, 120);
  const text = (el.innerText || el.getAttribute("title") || "").replace(/\s+/g, " ").trim();
  return text.slice(0, 120);
}

function chrollerRole(el) {
  const explicit = el.getAttribute("role");
  if (explicit) return explicit;
  const tag = el.tagName.toLowerCase();
  if (tag === "a") return "link";
  if (tag === "button") return "button";
  if (tag === "textarea") return "textbox";
  if (tag === "select") return "combobox";
  if (tag === "summary") return "button";
  if (el.isContentEditable) return "textbox";
  if (tag === "input") {
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (type === "submit" || type === "button" || type === "reset") return "button";
    if (type === "password") return "password";
    return "textbox";
  }
  return tag;
}

function chrollerCollect(root, out) {
  const selector = [
    "a",
    "button",
    "input",
    "textarea",
    "select",
    "summary",
    "[role='button']",
    "[role='link']",
    "[role='textbox']",
    "[role='checkbox']",
    "[role='radio']",
    "[role='combobox']",
    "[role='tab']",
    "[role='menuitem']",
    "[role='menuitemcheckbox']",
    "[role='menuitemradio']",
    "[role='option']",
    "[role='switch']",
    "[contenteditable='true']"
  ].join(",");
  root.querySelectorAll(selector).forEach((el) => out.push(el));
  root.querySelectorAll("*").forEach((el) => {
    if (el.shadowRoot) chrollerCollect(el.shadowRoot, out);
  });
}

function chrollerSnapshot() {
  if (chrollerFrameSkipped()) return { skip: true };
  document.querySelectorAll("[data-chroller-ref]").forEach((el) => {
    el.removeAttribute("data-chroller-ref");
  });
  const found = [];
  chrollerCollect(document, found);
  const elements = [];
  const seen = new Set();
  for (const el of found) {
    if (seen.has(el) || !chrollerVisible(el)) continue;
    seen.add(el);
    if (elements.length >= 200) break;
    const local = "e" + (elements.length + 1);
    el.setAttribute("data-chroller-ref", local);
    const rect = el.getBoundingClientRect();
    const password = el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "password";
    const item = {
      local,
      role: chrollerRole(el),
      name: chrollerName(el),
      tag: el.tagName.toLowerCase(),
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    };
    if (!password && "value" in el && el.value) item.value = String(el.value).slice(0, 80);
    elements.push(item);
  }
  return {
    skip: false,
    url: location.href,
    title: document.title,
    elements
  };
}

function chrollerFind(local) {
  if (!/^e\d+$/.test(local)) return null;
  const selector = `[data-chroller-ref="${local}"]`;
  function walk(root) {
    const found = root.querySelector(selector);
    if (found) return found;
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) {
        const inner = walk(el.shadowRoot);
        if (inner) return inner;
      }
    }
    return null;
  }
  return walk(document);
}

function chrollerInsets(outerWidth, innerWidth, outerHeight, innerHeight) {
  const extraX = Math.max(0, outerWidth - innerWidth);
  const extraY = Math.max(0, outerHeight - innerHeight);
  // A wide horizontal gap is the side panel or docked tools on the right, not a centered border.
  const sideUi = extraX > 80;
  const border = sideUi ? Math.min(16, extraY) : extraX / 2;
  return {
    x: sideUi ? border : extraX / 2,
    y: Math.max(0, extraY - border)
  };
}

function chrollerPoint(el) {
  el.scrollIntoView({ block: "center", inline: "center" });
  const rect = el.getBoundingClientRect();
  if (rect.width < 1 || rect.height < 1) return { ok: false, error: "Element has no box on screen." };
  const inset = chrollerInsets(window.outerWidth, window.innerWidth, window.outerHeight, window.innerHeight);
  return {
    ok: true,
    x: window.screenX + inset.x + rect.left + rect.width / 2,
    y: window.screenY + inset.y + rect.top + rect.height / 2,
    dpr: window.devicePixelRatio || 1
  };
}

function chrollerPrepare(local) {
  if (chrollerFrameSkipped()) return { ok: false, error: "Ref is in a cross-origin frame." };
  const el = chrollerFind(local);
  if (!el) return { ok: false, error: "Ref not found. Take a new snapshot." };
  return chrollerPoint(el);
}

function chrollerDomClick(local) {
  if (chrollerFrameSkipped()) return { ok: false, error: "Ref is in a cross-origin frame." };
  const el = chrollerFind(local);
  if (!el) return { ok: false, error: "Ref not found. Take a new snapshot." };
  el.scrollIntoView({ block: "center", inline: "center" });
  if (typeof el.focus === "function") el.focus();
  const opts = { bubbles: true, cancelable: true, view: window, button: 0, buttons: 1 };
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.indexOf("pointer") === 0 && window.PointerEvent ? PointerEvent : MouseEvent;
    el.dispatchEvent(new Ctor(type, opts));
  }
  const form = el.form || (el.closest && el.closest("form"));
  const typeAttr = (el.getAttribute && el.getAttribute("type") || "").toLowerCase();
  const submits = form && (typeAttr === "submit" || (el.tagName === "BUTTON" && typeAttr !== "button"));
  if (submits && typeof form.requestSubmit === "function") form.requestSubmit(el);
  return { ok: true };
}

function chrollerSetValue(el, text) {
  const proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, "value");
  if (desc && desc.set) desc.set.call(el, text);
  else el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function chrollerDomFill(local, text) {
  if (chrollerFrameSkipped()) return { ok: false, error: "Ref is in a cross-origin frame." };
  const el = chrollerFind(local);
  if (!el) return { ok: false, error: "Ref not found. Take a new snapshot." };
  el.scrollIntoView({ block: "center", inline: "center" });
  if (typeof el.focus === "function") el.focus();
  if (el.isContentEditable) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    return { ok: true };
  }
  if (!("value" in el)) return { ok: false, error: "Element is not a field." };
  chrollerSetValue(el, text);
  return { ok: true };
}

function chrollerFeedScroller() {
  const feed = document.querySelector("[role='feed']");
  let node = feed;
  while (node && node !== document.documentElement) {
    if (node.scrollHeight > node.clientHeight + 80) return node;
    node = node.parentElement;
  }
  const main = document.querySelector("[role='main']");
  if (main && main.scrollHeight > main.clientHeight + 80) return main;
  return document.scrollingElement || document.documentElement;
}

function chrollerScroll(local, dx, dy) {
  if (chrollerFrameSkipped()) return { ok: false, error: "Ref is in a cross-origin frame." };
  if (local) {
    const el = chrollerFind(local);
    if (!el) return { ok: false, error: "Ref not found. Take a new snapshot." };
    el.scrollIntoView({ block: "center", inline: "center" });
    return { ok: true };
  }
  const distanceY = Number(dy) || 0;
  const distanceX = Number(dx) || 0;
  const scroller = chrollerFeedScroller();
  if (scroller) scroller.scrollBy(distanceX, distanceY);
  window.scrollBy(distanceX, distanceY);
  return { ok: true };
}

function chrollerTakeLines(seen, lines, total) {
  const raw = (document.body && document.body.innerText) || "";
  for (const piece of raw.split(/\r?\n/)) {
    const line = piece.replace(/\s+/g, " ").trim();
    if (line.length < 2 || seen.has(line)) continue;
    const clipped = line.slice(0, 300);
    if (total.value + clipped.length > 24000) return false;
    seen.add(line);
    lines.push(clipped);
    total.value += clipped.length;
  }
  return true;
}

async function chrollerCollectFeed(maxPasses) {
  const passes = Math.max(1, Math.min(Number(maxPasses) || 8, 15));
  const seen = new Set();
  const lines = [];
  const total = { value: 0 };
  const scroller = chrollerFeedScroller();
  let stale = 0;
  let used = 0;
  chrollerTakeLines(seen, lines, total);
  for (let i = 0; i < passes; i += 1) {
    const before = lines.length;
    const step = Math.max(500, Math.floor((scroller.clientHeight || window.innerHeight || 700) * 0.8));
    scroller.scrollBy(0, step);
    window.scrollBy(0, step);
    used += 1;
    await new Promise((resolve) => setTimeout(resolve, 800));
    const room = chrollerTakeLines(seen, lines, total);
    if (lines.length === before) stale += 1;
    else stale = 0;
    if (!room || stale >= 2) break;
  }
  return {
    ok: true,
    url: location.href,
    title: document.title || "",
    lines,
    passes: used,
    stopped: stale >= 2 ? "no-new-text" : "limit"
  };
}

function chrollerMetrics() {
  return { dpr: window.devicePixelRatio || 1 };
}

function chrollerReadText(maxLines) {
  const raw = (document.body && document.body.innerText) || "";
  const lines = [];
  let total = 0;
  const limit = Math.max(1, Math.min(Number(maxLines) || 40, 80));
  for (const piece of raw.split(/\r?\n/)) {
    const line = piece.replace(/\s+/g, " ").trim();
    if (!line) continue;
    const clipped = line.slice(0, 300);
    if (total + clipped.length > 12000) break;
    lines.push(clipped);
    total += clipped.length;
    if (lines.length >= limit) break;
  }
  return { ok: true, url: location.href, title: document.title || "", lines };
}

function chrollerEvaluate(expression) {
  if (chrollerFrameSkipped()) return { ok: false, error: "Ref is in a cross-origin frame." };
  try {
    const value = (0, eval)(expression);
    const encoded = JSON.parse(JSON.stringify(value === undefined ? null : value));
    return { ok: true, value: encoded };
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
}
