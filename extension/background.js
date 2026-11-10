importScripts("page_actions.js");

const state = {
  armed: false,
  attached: {},
  token: "",
  connected: false,
  connectionError: "Paste the pairing token."
};

let companionPort = null;
const inputWaiters = new Map();

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadState() {
  const stored = await chrome.storage.local.get(["armed", "attached", "token"]);
  state.armed = Boolean(stored.armed);
  state.token = stored.token || "";
  state.attached = {};
  for (const id of stored.attached || []) state.attached[id] = true;
  if (!state.token) state.connectionError = "Paste the pairing token.";
}

async function saveState() {
  await chrome.storage.local.set({
    armed: state.armed,
    token: state.token,
    attached: Object.keys(state.attached).map(Number)
  });
}

function normalizeToken(raw) {
  let text = String(raw || "").trim();
  const label = text.toLowerCase();
  const prefix = "pairing token:";
  if (label.startsWith(prefix)) text = text.slice(prefix.length).trim();
  return text.replace(/\s+/g, "");
}

function publicState() {
  return {
    armed: state.armed,
    token: state.token,
    attached: Object.keys(state.attached).map(Number),
    connected: state.connected,
    connectionError: state.connectionError
  };
}

function blockedUrl(url) {
  if (!url) return true;
  let parsed;
  try { parsed = new URL(url); } catch (err) { return true; }
  if (["chrome:", "chrome-extension:", "edge:", "about:", "devtools:", "view-source:"].includes(parsed.protocol)) {
    return true;
  }
  if (parsed.hostname === "chrome.google.com" && parsed.pathname.startsWith("/webstore")) return true;
  if (parsed.hostname === "chromewebstore.google.com") return true;
  return false;
}

function guard(tabId) {
  if (!state.armed) return "Chroller is disarmed. Arm it in the side panel.";
  if (!state.attached[tabId]) return "Tab " + tabId + " is not attached.";
  return "";
}

function parseRef(ref) {
  const match = /^f(\d+)e(\d+)$/.exec(ref || "");
  if (!match) return null;
  return { frameId: Number(match[1]), local: "e" + match[2] };
}

async function inject(tabId, frameId, func, args, world) {
  const target = frameId == null ? { tabId } : { tabId, frameIds: [frameId] };
  const base = { target };
  if (world) base.world = world;
  try {
    await chrome.scripting.executeScript({ ...base, files: ["page_actions.js"] });
    const results = await chrome.scripting.executeScript({ ...base, func, args });
    const first = results && results[0];
    if (!first || first.result == null) return { ok: false, error: "The page did not return a result." };
    return first.result;
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
}

async function showTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const win = await chrome.windows.get(tab.windowId);
  if (win.state === "minimized") {
    await chrome.windows.update(tab.windowId, { state: "normal", focused: true });
  } else if (!win.focused) {
    await chrome.windows.update(tab.windowId, { focused: true });
  }
  if (!tab.active) await chrome.tabs.update(tabId, { active: true });
  if (!win.focused || !tab.active || win.state === "minimized") await delay(180);
  return tab;
}

async function windowBounds(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const win = await chrome.windows.get(tab.windowId);
  return { left: win.left, top: win.top, width: win.width, height: win.height };
}

function requestOsInput(commandId, input) {
  if (!companionPort) return Promise.resolve({ ok: false, error: "Companion connection is gone." });
  companionPort.postMessage({ type: "needs_input", id: commandId, input });
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      inputWaiters.delete(commandId);
      resolve({ ok: false, error: "OS input timed out." });
    }, 10000);
    inputWaiters.set(commandId, (message) => {
      clearTimeout(timer);
      resolve(message);
    });
  });
}

let commandsByName = null;
const commandsReady = fetch(chrome.runtime.getURL("commands.json"))
  .then((response) => response.json())
  .then((rows) => {
    commandsByName = {};
    for (const row of rows) commandsByName[row.name] = row;
  });

async function runCommand(message) {
  const op = message.op;
  const args = message.args || {};
  const tabId = Number(args.tab_id);

  try {
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    const tab = await chrome.tabs.get(tabId);
    if (blockedUrl(tab.url)) {
      return { ok: false, error: "This tab cannot be scripted. chrome:// pages, the Web Store, and other extensions are blocked." };
    }

    if (op === "chroller_click") {
      const parsed = parseRef(args.ref);
      if (!parsed) return { ok: false, error: "Ref is invalid. Take a new snapshot." };
      const clicked = await inject(tabId, parsed.frameId, chrollerDomClick, [parsed.local]);
      if (!clicked.ok) return clicked;
      return { ok: true, data: { tab_id: tabId, ref: args.ref, method: "dom" } };
    }

    if (op === "chroller_type") {
      if (typeof args.text !== "string" || args.text.length === 0) {
        return { ok: false, error: "text is required." };
      }
      const method = args.method === "dom" ? "dom" : "os";
      const parsed = parseRef(args.ref);
      if (!parsed) return { ok: false, error: "Ref is invalid. Take a new snapshot." };
      if (method === "dom") {
        const filled = await inject(tabId, parsed.frameId, chrollerDomFill, [parsed.local, args.text]);
        if (!filled.ok) return filled;
        return { ok: true, data: { tab_id: tabId, ref: args.ref, method } };
      }
      await showTab(tabId);
      const focused = await inject(tabId, parsed.frameId, chrollerDomClick, [parsed.local]);
      if (!focused.ok) return focused;
      const metrics = await inject(tabId, 0, chrollerMetrics, []);
      const typed = await requestOsInput(message.id, {
        kind: "type",
        text: args.text,
        window: await windowBounds(tabId),
        dpr: metrics.dpr || 1
      });
      if (!typed.ok) return { ok: false, error: typed.error || "OS input failed." };
      return { ok: true, data: { tab_id: tabId, ref: args.ref, method } };
    }

    if (op === "chroller_press") {
      if (!args.key) return { ok: false, error: "key is required." };
      await showTab(tabId);
      const metrics = await inject(tabId, 0, chrollerMetrics, []);
      const done = await requestOsInput(message.id, {
        kind: "key",
        key: String(args.key),
        window: await windowBounds(tabId),
        dpr: metrics.dpr || 1
      });
      if (!done.ok) return { ok: false, error: done.error || "OS input failed." };
      return { ok: true, data: { tab_id: tabId, key: args.key } };
    }

    if (op === "chroller_scroll") {
      const parsed = args.ref ? parseRef(args.ref) : null;
      if (args.ref && !parsed) return { ok: false, error: "Ref is invalid. Take a new snapshot." };
      const frameId = parsed ? parsed.frameId : 0;
      const local = parsed ? parsed.local : "";
      const moved = await inject(tabId, frameId, chrollerScroll, [local, args.dx || 0, args.dy || 0]);
      if (!moved.ok) return moved;
      return { ok: true, data: { tab_id: tabId, ref: args.ref || "", dx: args.dx || 0, dy: args.dy || 0 } };
    }

    if (op === "chroller_fill") {
      const fields = Array.isArray(args.fields) ? args.fields : [];
      if (!fields.length) return { ok: false, error: "fields is required." };
      const method = args.method === "os" ? "os" : "dom";
      for (const field of fields) {
        if (!field || typeof field.text !== "string") return { ok: false, error: "Each field needs ref and text." };
        const parsed = parseRef(field.ref);
        if (!parsed) return { ok: false, error: "Ref is invalid. Take a new snapshot." };
        if (method === "dom") {
          const filled = await inject(tabId, parsed.frameId, chrollerDomFill, [parsed.local, field.text]);
          if (!filled.ok) return filled;
          continue;
        }
        await showTab(tabId);
        const focused = await inject(tabId, parsed.frameId, chrollerDomClick, [parsed.local]);
        if (!focused.ok) return focused;
        const metrics = await inject(tabId, 0, chrollerMetrics, []);
        const typed = await requestOsInput(message.id, {
          kind: "type",
          text: field.text,
          window: await windowBounds(tabId),
          dpr: metrics.dpr || 1
        });
        if (!typed.ok) return { ok: false, error: typed.error || "OS input failed." };
      }
      return { ok: true, data: { tab_id: tabId, method, count: fields.length } };
    }

    if (op === "chroller_evaluate") {
      if (!args.expression) return { ok: false, error: "expression is required." };
      const result = await inject(tabId, 0, chrollerEvaluate, [String(args.expression)], "MAIN");
      if (!result.ok) return result;
      return { ok: true, data: { tab_id: tabId, value: result.value } };
    }

    return { ok: false, error: "Unknown command " + op + "." };
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
}

async function handleListed(message) {
  const op = message.op;
  const args = message.args || {};
  const tabId = Number(args.tab_id);
  if (op === "chroller_status") {
    return { ok: true, data: { connected: true, armed: state.armed, attached: Object.keys(state.attached).map(Number) } };
  }
  if (op === "chroller_tabs") {
    const tabs = await chrome.tabs.query({});
    return {
      ok: true,
      data: {
        tabs: tabs.map((tab) => ({
          tab_id: tab.id,
          title: tab.title || "",
          url: tab.url || "",
          attached: Boolean(state.attached[tab.id]),
          active: Boolean(tab.active),
          window_id: tab.windowId
        }))
      }
    };
  }
  if (op === "chroller_navigate") {
    if (!state.armed) return { ok: false, error: "Chroller is disarmed. Arm it in the side panel." };
    const url = args.url;
    if (!url || blockedUrl(url)) {
      return { ok: false, error: "That address cannot be opened. chrome:// pages, the Web Store, and other extensions are blocked." };
    }
    if (!args.tab_id) {
      const created = await chrome.tabs.create({ url, active: false });
      state.attached[created.id] = true;
      await saveState();
      return { ok: true, data: { tab_id: created.id, url, attached: true } };
    }
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    await chrome.tabs.update(tabId, { url });
    return { ok: true, data: { tab_id: tabId, url, attached: true } };
  }
  if (op === "chroller_read") {
    let tabId = Number(args.tab_id);
    if (!args.tab_id) {
      if (!state.armed) return { ok: false, error: "Chroller is disarmed. Arm it in the side panel." };
      const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      if (!active) return { ok: false, error: "No active Chrome tab." };
      if (!state.attached[active.id]) {
        return { ok: false, error: "The active tab is not attached. Check it in the Chroller side panel." };
      }
      tabId = active.id;
    }
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    const tab = await chrome.tabs.get(tabId);
    if (blockedUrl(tab.url)) {
      return { ok: false, error: "This tab cannot be scripted. chrome:// pages, the Web Store, and other extensions are blocked." };
    }
    const result = await inject(tabId, 0, chrollerReadText, [Number(args.lines) || 40]);
    if (!result.ok) return result;
    return {
      ok: true,
      data: {
        tab_id: tabId,
        url: result.url || tab.url || "",
        title: result.title || tab.title || "",
        lines: result.lines || []
      }
    };
  }
  if (op === "chroller_collect") {
    let tabId = Number(args.tab_id);
    if (!args.tab_id) {
      if (!state.armed) return { ok: false, error: "Chroller is disarmed. Arm it in the side panel." };
      const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      if (!active) return { ok: false, error: "No active Chrome tab." };
      if (!state.attached[active.id]) {
        return { ok: false, error: "The active tab is not attached. Check it in the Chroller side panel." };
      }
      tabId = active.id;
    }
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    const tab = await chrome.tabs.get(tabId);
    if (blockedUrl(tab.url)) {
      return { ok: false, error: "This tab cannot be scripted. chrome:// pages, the Web Store, and other extensions are blocked." };
    }
    const result = await inject(tabId, 0, chrollerCollectFeed, [Number(args.passes) || 8]);
    if (!result.ok) return result;
    return {
      ok: true,
      data: {
        tab_id: tabId,
        url: result.url || tab.url || "",
        title: result.title || tab.title || "",
        lines: result.lines || [],
        passes: result.passes || 0,
        stopped: result.stopped || ""
      }
    };
  }
  if (op === "chroller_snapshot") {
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    const tab = await chrome.tabs.get(tabId);
    if (blockedUrl(tab.url)) {
      return { ok: false, error: "This tab cannot be scripted. chrome:// pages, the Web Store, and other extensions are blocked." };
    }
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ["page_actions.js"]
    });
    const frames = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => chrollerSnapshot()
    });
    const elements = [];
    let url = tab.url;
    let title = tab.title || "";
    for (const frame of frames) {
      const body = frame.result;
      if (!body || body.skip) continue;
      url = body.url || url;
      if (frame.frameId === 0 && body.title) title = body.title;
      for (const item of body.elements || []) {
        const row = {
          ref: "f" + frame.frameId + item.local,
          role: item.role,
          name: item.name,
          tag: item.tag,
          x: item.x,
          y: item.y,
          width: item.width,
          height: item.height
        };
        if (item.value) row.value = item.value;
        elements.push(row);
      }
    }
    return { ok: true, data: { tab_id: tabId, url, title, elements } };
  }
  if (op === "chroller_screenshot") {
    const reason = guard(tabId);
    if (reason) return { ok: false, error: reason };
    await showTab(tabId);
    const current = await chrome.tabs.get(tabId);
    const image = await chrome.tabs.captureVisibleTab(current.windowId, { format: "jpeg", quality: 50 });
    if (image.length > 900000) return { ok: false, error: "Screenshot is too large. Use chroller_snapshot." };
    return { ok: true, data: { tab_id: tabId, mime: "image/jpeg", image_data_url: image } };
  }
  return { ok: false, error: "Unknown command " + op + "." };
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "chroller") return;
  companionPort = port;
  port.onDisconnect.addListener(() => {
    if (companionPort === port) {
      companionPort = null;
      state.connected = false;
    }
  });
  port.onMessage.addListener((message) => {
    if (message.type === "offscreen-hello") {
      port.postMessage({ type: "reauth", token: state.token });
      return;
    }
    if (message.type === "connection") {
      state.connected = Boolean(message.connected);
      state.connectionError = message.error || "";
      return;
    }
    if (message.type === "input_done") {
      const waiter = inputWaiters.get(message.id);
      if (waiter) {
        inputWaiters.delete(message.id);
        waiter(message);
      }
      return;
    }
    if (message.type === "command") {
      commandsReady.then(() => {
        const spec = commandsByName && commandsByName[message.op];
        if (!spec) {
          return { ok: false, error: "Unknown command " + message.op + "." };
        }
        const runner = spec.route === "input" ? runCommand : handleListed;
        return runner(message);
      }).then((result) => {
        port.postMessage({ type: "result", id: message.id, ok: Boolean(result.ok), data: result.data || null, error: result.error || "" });
      }).catch((err) => {
        port.postMessage({ type: "result", id: message.id, ok: false, data: null, error: String(err && err.message ? err.message : err) });
      });
    }
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "get-state") {
    chrome.tabs.query({}).then((tabs) => {
      sendResponse({
        ...publicState(),
        tabs: tabs.map((tab) => ({
          tab_id: tab.id,
          title: tab.title || "",
          url: tab.url || "",
          attached: Boolean(state.attached[tab.id]),
          active: Boolean(tab.active)
        }))
      });
    });
    return true;
  }
  if (message.type === "set-token") {
    state.token = normalizeToken(message.token);
    saveState().then(() => {
      if (companionPort) companionPort.postMessage({ type: "reauth", token: state.token });
      sendResponse(publicState());
    });
    return true;
  }
  if (message.type === "set-armed") {
    state.armed = Boolean(message.armed);
    saveState().then(() => sendResponse(publicState()));
    return true;
  }
  if (message.type === "set-attached") {
    if (message.attached) state.attached[message.tab_id] = true;
    else delete state.attached[message.tab_id];
    saveState().then(() => sendResponse(publicState()));
    return true;
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (!state.attached[tabId]) return;
  delete state.attached[tabId];
  saveState();
});

async function ensureOffscreen() {
  const exists = await chrome.offscreen.hasDocument();
  if (exists) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["WORKERS"],
    justification: "Keep the localhost connection to the Chroller companion open."
  });
}

chrome.alarms.create("chroller-keepalive", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(() => { ensureOffscreen(); });

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

loadState().then(() => ensureOffscreen());
