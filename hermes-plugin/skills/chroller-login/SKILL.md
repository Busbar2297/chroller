---
name: chroller-login
description: Sign in on a Chrome tab the user attached to Chroller. Type only a secret the user supplied in chat. Do not read Chrome's password store.
---

# Chroller login

Sign in only on an attached tab in the user's real Chrome profile. Load `chroller-browser` first if you have not already used the chroller tools in this turn.

1. `chroller_status`. Stop if control is disarmed or the extension is disconnected.
2. `chroller_snapshot` on the attached tab. Find the identifier field and the password field from roles and names. Password values are omitted on purpose.
3. `chroller_click` the identifier field, then `chroller_type` the username. The click runs in the page. Leave typing on the OS method.
4. `chroller_click` the password field, then `chroller_type` the secret the user supplied in this chat. Leave `method` as `os` for the password.
5. `chroller_press` `Enter`, or `chroller_click` the submit control from a fresh snapshot.
6. Snapshot again and say whether the page moved past the login form.

Do not repeat the password in the reply. Do not call a tool that reads Chrome's password store, cookies, or `localStorage` to find it. If OS focus fails, stop and tell the user to click the Chrome window once. Do not fall through to `method: "dom"` for the password.
