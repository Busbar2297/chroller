let port = null;
let socket = null;
let token = "";
let stopped = false;

function bridge() {
  port = chrome.runtime.connect({ name: "chroller" });
  port.onMessage.addListener((message) => {
    if (message.type === "reauth") {
      token = message.token || "";
      reconnect();
      return;
    }
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (message.type === "needs_input" || message.type === "result") {
      socket.send(JSON.stringify(message));
    }
  });
  port.onDisconnect.addListener(() => {
    port = null;
    setTimeout(bridge, 500);
  });
  port.postMessage({ type: "offscreen-hello" });
}

function reconnect() {
  if (socket) {
    socket.onclose = null;
    try { socket.close(); } catch (err) { /* already closed */ }
    socket = null;
  }
  if (!token || stopped) {
    if (port) port.postMessage({ type: "connection", connected: false, error: token ? "" : "Paste the pairing token." });
    return;
  }
  const ws = new WebSocket("ws://127.0.0.1:8766");
  socket = ws;
  let failure = "";
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "auth", token }));
  };
  ws.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (err) { return; }
    if (!port) return;
    if (message.type === "auth_ok") {
      port.postMessage({ type: "connection", connected: true, error: "" });
      return;
    }
    if (message.type === "auth_fail") {
      failure = "Pairing token was rejected. Paste only the token from the companion window, then click Save.";
      port.postMessage({ type: "connection", connected: false, error: failure });
      try { ws.close(); } catch (err) { /* close follows */ }
      return;
    }
    if (message.type === "command" || message.type === "input_done") {
      port.postMessage(message);
    }
  };
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    if (failure) return;
    if (port) port.postMessage({ type: "connection", connected: false, error: "Companion is not reachable on 127.0.0.1:8766." });
    setTimeout(reconnect, 1000);
  };
  ws.onerror = () => {
    try { ws.close(); } catch (err) { /* close follows */ }
  };
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "reauth") {
    token = message.token || "";
    reconnect();
  }
});

bridge();
