# Chroller

Control the Chrome profile you are already signed into, from a local [Hermes](https://github.com/NousResearch/hermes-agent) agent.

Chroller is a Chrome extension, a Windows companion, and a Hermes plugin. The agent reads and drives tabs in your normal Chrome window: the same profile, the same cookies, the same open pages. It does not launch a second browser, and it does not use the Chrome DevTools Protocol, `chrome.debugger`, or `--remote-debugging-port`.

Use it when an agent needs the browser session you already use, and a fresh automation profile would be signed out.

## What it does

- Reads the current Chrome tab, including a long feed that virtualizes as it scrolls.
- Clicks, types, scrolls, and fills fields in tabs you explicitly attach.
- Opens new tabs from the agent and keeps those tabs attached.
- Leaves Chrome in the background for in-page clicks. Real keystrokes bring the window forward.
- Refuses the Chrome password store and does not return password field values.

## How it is built

| Piece | Role |
| --- | --- |
| `extension/` | Manifest V3 extension. Side panel to arm control and attach tabs. An offscreen document holds the WebSocket, because a service worker would sleep. |
| `companion/` | Local Python process. HTTP on `127.0.0.1:8765`, WebSocket on `127.0.0.1:8766`. Loopback only. |
| `hermes-plugin/` | Hermes tools named `chroller_*`. The names match `extension/commands.json` and are not renamed on the wire. |

The companion accepts a command only from a paired extension. The extension runs it only while Control is on, and only in an attached tab or a tab the agent just opened.

## Requirements

- Windows, for real keystrokes. In-page clicks do not use the OS mouse.
- Google Chrome 116 or newer.
- Python 3.
- A local Hermes profile, if you want the `chroller_*` tools.

## Install

### 1. Load the extension

1. Open `chrome://extensions`.
2. Turn on Developer mode.
3. Choose **Load unpacked** and select the `extension` folder in this repository.

Chrome 157 ignores `--load-extension`. Load the folder from that page.

### 2. Start the companion

From the repository root:

```powershell
python -m companion
```

The window prints a pairing token and keeps running. Leave it open.

In the Chroller side panel, paste only the token and save. The status pill should show that the companion is connected. A rejected token is an authentication failure, not a sign that the process is down.

The token is stored at `%USERPROFILE%\.chroller\token`. It is not part of this repository.

### 3. Arm control and attach tabs

Turn **Control** on in the side panel, then check the tabs the agent may use. Unchecked tabs stay out of reach. Tabs the agent opens with `chroller_navigate` start attached.

### 4. Install the Hermes plugin

Hermes reads `plugin.yaml` from the plugin directory, which in this repository is `hermes-plugin/`:

```powershell
hermes plugins install Busbar2297/chroller/hermes-plugin
hermes plugins enable chroller
```

Add `chroller` to the profile's `platform_toolsets` for the platform you chat from. Desktop chat uses the `cli` list. Enabling the plugin alone does not put the tools in that list.

Quit Hermes completely and open it again. A new chat inside an already running backend keeps the tool list from the last startup. After a restart, the tool list includes `chroller_read` and `chroller_collect`.

Ask Hermes to use `chroller_*` for the Chrome window you have open. `browser_*` and `desktop_preview` drive a different browser and cannot see this profile.

## Tools

| Tool | Use |
| --- | --- |
| `chroller_status` | Companion, arm state, and connection. Call this first. |
| `chroller_tabs` | Tab ids. Act only on attached tabs. |
| `chroller_navigate` | Open a URL. Omit `tab_id` to open a new attached tab. |
| `chroller_read` | Visible text of the active attached tab. |
| `chroller_collect` | Scroll a long page or feed and keep text that would otherwise leave the DOM. |
| `chroller_snapshot` | Interactive elements and refs such as `f0e3`. Take a fresh snapshot after every navigation or click. |
| `chroller_click` | In-page click. OS mouse clicks are disabled. |
| `chroller_type` | Type into a ref. The default sends real keystrokes and brings Chrome forward. |
| `chroller_press` | A real key, such as `Enter` or `Control+A`. |
| `chroller_scroll` | Scroll the page or a feed without moving the mouse. |
| `chroller_fill` | Fill several ordinary fields in the page. |
| `chroller_screenshot` | Visible pixels of an attached tab. |
| `chroller_evaluate` | A JSON result from the page's main world. |

For a menu, account dropdown, or a Sign out row: click the opener, snapshot immediately, then click the new row. A click outside the menu closes it.

## Security boundary

- The companion binds to `127.0.0.1` only. It rejects a non-loopback URL from the plugin.
- One Control switch. Off means no commands run.
- Only attached tabs, plus tabs the agent opens.
- Password input values are omitted. There is no tool for the Chrome password store or the cookie jar.
- `chrome://` pages, the Chrome Web Store, other extensions, and cross-origin iframes are not read.
- Typed text is not written to the companion log.

## Development

```powershell
python -m unittest tests.test_plugin companion.test_bridge
```

Command names in `extension/commands.json`, `hermes-plugin/plugin.yaml`, and `hermes-plugin/schemas.py` are the same list, in the same order.

## License

[MIT](LICENSE)
