const status = document.querySelector("#status");
const tokenInput = document.querySelector("#token");
const error = document.querySelector("#connection-error");
const arm = document.querySelector("#arm");
const tabs = document.querySelector("#tabs");

function paint(state) {
  const online = state.connected;
  status.textContent = online ? "Connected" : "Offline";
  status.className = "status " + (online ? "ok" : "bad");
  error.textContent = state.connectionError || "";
  error.classList.toggle("error", Boolean(state.connectionError));
  arm.textContent = state.armed ? "On" : "Off";
  arm.classList.toggle("on", state.armed);
  arm.setAttribute("aria-pressed", state.armed ? "true" : "false");
  tabs.replaceChildren();
  const rows = state.tabs || [];
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No open tabs.";
    tabs.appendChild(empty);
    return;
  }
  for (const tab of rows) {
    const item = document.createElement("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = tab.attached;
    box.addEventListener("change", () => {
      chrome.runtime.sendMessage({ type: "set-attached", tab_id: tab.tab_id, attached: box.checked }, refresh);
    });
    const text = document.createElement("div");
    const title = document.createElement("span");
    title.textContent = tab.title || "Untitled";
    const url = document.createElement("span");
    url.className = "url";
    url.textContent = tab.url || "";
    text.append(title, url);
    item.append(box, text);
    tabs.appendChild(item);
  }
}

function refresh() {
  chrome.runtime.sendMessage({ type: "get-state" }, (state) => {
    if (chrome.runtime.lastError || !state) return;
    if (document.activeElement !== tokenInput) tokenInput.value = state.token || "";
    paint(state);
  });
}

document.querySelector("#save").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "set-token", token: tokenInput.value }, refresh);
});

arm.addEventListener("click", () => {
  const next = arm.getAttribute("aria-pressed") !== "true";
  chrome.runtime.sendMessage({ type: "set-armed", armed: next }, refresh);
});

document.querySelector("#refresh").addEventListener("click", refresh);

refresh();
setInterval(refresh, 2000);
