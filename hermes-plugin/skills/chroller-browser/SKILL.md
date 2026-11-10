---
name: chroller-browser
description: Read or drive the user's signed-in Chrome, including the current Chrome tab and the active tab. Use chroller_read for page text. Never use desktop_preview or browser_* tools for that Chrome window. desktop_preview is a separate pane and is not the user's Chrome.
---

# Chroller browser

Use the `chroller` toolset for the Chrome window the user already has open. Hermes `browser_*` tools drive a separate automation browser and do not see this profile.

1. Call `chroller_status`. If the companion is down, say so. If control is disarmed, tell the user to turn Control on in the Chroller side panel. Do not invent an attach tool.
2. To read the current Chrome tab, call `chroller_read` with `lines` set to how many lines were asked for, and omit `tab_id`. That reads the active attached tab. Do not call `desktop_preview`.
3. When the user wants all the text from a Facebook feed or another long scrolling page, call `chroller_collect`. It scrolls the feed and keeps text that would otherwise disappear. Process those lines into the answer they asked for, and say if collection stopped because the feed stopped adding text. Do not claim posts that were not in the lines.
4. Call `chroller_tabs` when you need a tab id. The active tab has `active: true`. Act only on tabs whose `attached` field is true, or on tabs you opened with `chroller_navigate` without a `tab_id`. Those new tabs start attached.
5. Loop: `chroller_snapshot`, one action, then snapshot again. Refs such as `f0e3` expire after the page changes.
6. A dropdown, account menu, or Sign out item is not on the page until its menu is open. Click the opener, then snapshot again before any other action. Click the new row whose name is Sign out, Subscribe, or the other menu label. A click outside that menu closes it and the row is gone.
7. `chroller_click` always clicks in the page. OS mouse clicks are disabled, so Chrome stays where it is. `chroller_type` still defaults to `method: "os"` and brings Chrome forward to send real keystrokes. Use `method: "dom"` for typing only when the field is not a password.
8. `chroller_fill` defaults to `dom`. Use it for ordinary fields in a background tab.
9. `chroller_press` sends a real key such as `Enter` or `Control+A`.
10. `chroller_screenshot` brings the tab forward. Prefer a snapshot unless the pixels matter.
11. `chroller_evaluate` reads a JSON value from the page. Do not use it to dump cookies or saved passwords.

These calls fail, and the failure is the answer: a disarmed switch, an unattached tab, a `chrome://` page, the Chrome Web Store, another extension, a cross-origin iframe, or a Chrome window that would not take focus. Stop on a focus error instead of guessing a coordinate.
