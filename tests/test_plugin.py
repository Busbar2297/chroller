import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


def load_plugin():
    root = Path(__file__).resolve().parents[1] / "hermes-plugin"
    name = "chroller_plugin_under_test"
    spec = importlib.util.spec_from_file_location(
        name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self):
        self.tools = []
        self.skills = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_skill(self, name, path):
        self.skills.append((name, Path(path)))

    def get_config(self):
        return {"companion_url": "http://127.0.0.1:8765"}


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.module = load_plugin()
        self.tmp = tempfile.TemporaryDirectory()
        self.module.profile_skills_dir = lambda: Path(self.tmp.name)
        os.environ.pop("CHROLLER_URL", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_adds_tools_and_visible_skills(self):
        ctx = FakeContext()
        self.module.register(ctx)
        names = [item["name"] for item in ctx.tools]
        self.assertEqual(names, [schema["name"] for schema in self.module.schemas.ALL])
        self.assertEqual(len(names), 13)
        read = next(schema for schema in self.module.schemas.ALL if schema["name"] == "chroller_read")
        self.assertEqual(read["parameters"]["required"], [])
        self.assertIn("desktop_preview", read["description"])
        browser = (Path(self.tmp.name) / "chroller" / "chroller-browser" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("chroller_read", browser)
        self.assertIn("desktop_preview", browser)
        self.assertTrue(all(item["toolset"] == "chroller" for item in ctx.tools))
        self.assertTrue(all(callable(item["handler"]) for item in ctx.tools))
        self.assertEqual([name for name, _path in ctx.skills], ["chroller-browser", "chroller-login"])
        for skill, _path in ctx.skills:
            target = Path(self.tmp.name) / "chroller" / skill / "SKILL.md"
            self.assertTrue(target.exists(), target)
            text = target.read_text(encoding="utf-8")
            self.assertIn("name: " + skill, text)

    def test_handlers_accept_kwargs_and_report_missing_fields(self):
        ctx = FakeContext()
        self.module.register(ctx)
        handlers = {item["name"]: item["handler"] for item in ctx.tools}
        result = json.loads(handlers["chroller_navigate"]({}, surprise=True))
        self.assertFalse(result["ok"])
        self.assertIn("url", result["error"])

    def test_tool_names_match_the_extension_commands(self):
        names = [row["name"] for row in self.module.tools.extension_commands()]
        self.assertEqual([schema["name"] for schema in self.module.schemas.ALL], names)
        manifest = (Path(__file__).resolve().parents[1] / "hermes-plugin" / "plugin.yaml").read_text(encoding="utf-8")
        for name in names:
            self.assertIn("- " + name, manifest)

    def test_companion_url_stays_on_loopback(self):
        self.module.tools.set_companion_url("http://example.com:8765")
        result = json.loads(self.module.tools.dispatch("chroller_status", {}))
        self.assertFalse(result["ok"])
        self.assertIn("127.0.0.1", result["error"])


if __name__ == "__main__":
    unittest.main()
