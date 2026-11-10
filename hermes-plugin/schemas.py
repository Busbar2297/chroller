"""Tool schemas shown to the Hermes model."""


def _object(properties, required):
    return {"type": "object", "properties": properties, "required": required}


_TAB = {
    "tab_id": {
        "type": "integer",
        "description": "Chrome tab id from chroller_tabs or the last chroller_navigate result.",
    }
}
_REF = {
    "ref": {
        "type": "string",
        "description": "Element ref from the latest chroller_snapshot, such as f0e3.",
    }
}
_METHOD = {
    "method": {
        "type": "string",
        "enum": ["os", "dom"],
        "description": "os sends real mouse and keyboard input and brings Chrome forward. dom runs in the page and can stay in a background tab.",
    }
}

CHROLLER_STATUS = {
    "name": "chroller_status",
    "description": (
        "Check the local Chroller bridge to the user's signed-in Chrome profile. "
        "Returns whether the companion and extension are connected, whether control is armed, "
        "and which tab ids are attached. Call this before other chroller tools."
    ),
    "parameters": _object({}, []),
}

CHROLLER_TABS = {
    "name": "chroller_tabs",
    "description": (
        "List open Chrome tabs in the user's real profile. Each row has tab_id, title, url, "
        "attached, and active. This does not attach a tab. The user attaches tabs in the Chroller side panel."
    ),
    "parameters": _object({}, []),
}

CHROLLER_NAVIGATE = {
    "name": "chroller_navigate",
    "description": (
        "Open a URL in the user's signed-in Chrome. Omit tab_id to open a new background tab; "
        "that new tab starts attached. Pass tab_id to navigate a tab the user already attached. "
        "Use this instead of Hermes browser_navigate when the user wants their real Chrome profile."
    ),
    "parameters": _object({
        **_TAB,
        "url": {"type": "string", "description": "http or https URL to open."},
    }, ["url"]),
}

CHROLLER_READ = {
    "name": "chroller_read",
    "description": (
        "Read visible text from the user's real Chrome window. Use this when they say current tab, "
        "active tab, or the page open in Chrome. Do not use desktop_preview or browser_* for that. "
        "desktop_preview is a separate Hermes pane and is not their Chrome. Omit tab_id to read the "
        "active attached tab. Pass lines to limit how many text lines come back, for example 3."
    ),
    "parameters": _object({
        **_TAB,
        "lines": {
            "type": "integer",
            "description": "How many visible text lines to return. Defaults to 40. Maximum 80.",
        },
    }, []),
}

CHROLLER_COLLECT = {
    "name": "chroller_collect",
    "description": (
        "Scroll a long page, including a Facebook feed, and return the visible text gathered along the way. "
        "Posts leave the page as the feed moves, so one chroller_read is not enough. "
        "Omit tab_id to use the active attached tab. passes is how many times to scroll, from 1 to 15. "
        "Then answer from the returned lines."
    ),
    "parameters": _object({
        **_TAB,
        "passes": {
            "type": "integer",
            "description": "How many times to scroll and collect. Defaults to 8. Maximum 15.",
        },
    }, []),
}

CHROLLER_SNAPSHOT = {
    "name": "chroller_snapshot",
    "description": (
        "Read interactive elements in an attached Chrome tab. Returns refs, roles, names, and boxes. "
        "Password values are omitted. Take a fresh snapshot after every navigation or click before using a ref."
    ),
    "parameters": _object(_TAB, ["tab_id"]),
}

CHROLLER_SCREENSHOT = {
    "name": "chroller_screenshot",
    "description": (
        "Capture the visible pixels of an attached tab. The tab is brought to the front. "
        "Prefer chroller_snapshot for clicking. Use this when layout or images matter."
    ),
    "parameters": _object(_TAB, ["tab_id"]),
}

CHROLLER_CLICK = {
    "name": "chroller_click",
    "description": (
        "Click an element ref in an attached Chrome tab. Clicks run in the page and leave Chrome in the "
        "background. OS mouse clicks are disabled. Refs come from the latest snapshot."
    ),
    "parameters": _object({**_TAB, **_REF, **_METHOD}, ["tab_id", "ref"]),
}

CHROLLER_TYPE = {
    "name": "chroller_type",
    "description": (
        "Type text into an element ref in an attached Chrome tab. Default method os clicks the field and "
        "sends real keystrokes, bringing Chrome forward. method dom sets the field value in the background "
        "and does not move the pointer. Do not use dom for a password. The typed text is not echoed back."
    ),
    "parameters": _object({
        **_TAB,
        **_REF,
        **_METHOD,
        "text": {"type": "string", "description": "Text to type. Do not include this value in your reply."},
    }, ["tab_id", "ref", "text"]),
}

CHROLLER_PRESS = {
    "name": "chroller_press",
    "description": (
        "Send a real key to the attached Chrome tab, such as Enter, Tab, Escape, or Control+A. "
        "Chrome is brought forward. Use this after chroller_type when a form needs Enter."
    ),
    "parameters": _object({
        **_TAB,
        "key": {"type": "string", "description": "Key name or shortcut, for example Enter or Control+A."},
    }, ["tab_id", "key"]),
}

CHROLLER_SCROLL = {
    "name": "chroller_scroll",
    "description": (
        "Scroll an attached tab without moving the mouse. A Facebook feed scrolls with the page. "
        "Pass ref to bring that element into view, or dx and dy to scroll. "
        "To gather the text of a long feed, use chroller_collect instead."
    ),
    "parameters": _object({
        **_TAB,
        "ref": {"type": "string", "description": "Optional element ref to scroll into view."},
        "dx": {"type": "number", "description": "Horizontal scroll in pixels."},
        "dy": {"type": "number", "description": "Vertical scroll in pixels. Positive scrolls down."},
    }, ["tab_id"]),
}

CHROLLER_FILL = {
    "name": "chroller_fill",
    "description": (
        "Fill several fields in an attached tab. Default method is dom, which does not steal the pointer. "
        "Pass method os only when the page ignores programmatic values. Do not put passwords in a dom fill. "
        "Field text is not echoed back."
    ),
    "parameters": _object({
        **_TAB,
        **_METHOD,
        "fields": {
            "type": "array",
            "description": "Fields to fill, in order.",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["ref", "text"],
            },
        },
    }, ["tab_id", "fields"]),
}

CHROLLER_EVALUATE = {
    "name": "chroller_evaluate",
    "description": (
        "Run a JavaScript expression in the main world of an attached tab and return a JSON value. "
        "Use this to read DOM state the snapshot does not show. Do not use it to read cookies, "
        "the password store, or storage the user did not ask for."
    ),
    "parameters": _object({
        **_TAB,
        "expression": {"type": "string", "description": "JavaScript expression. The result must be JSON-serializable."},
    }, ["tab_id", "expression"]),
}

ALL = [
    CHROLLER_STATUS,
    CHROLLER_TABS,
    CHROLLER_NAVIGATE,
    CHROLLER_READ,
    CHROLLER_COLLECT,
    CHROLLER_SNAPSHOT,
    CHROLLER_SCREENSHOT,
    CHROLLER_CLICK,
    CHROLLER_TYPE,
    CHROLLER_PRESS,
    CHROLLER_SCROLL,
    CHROLLER_FILL,
    CHROLLER_EVALUATE,
]
