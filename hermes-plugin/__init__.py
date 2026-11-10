"""Register Chroller tools and install skills into the active Hermes profile."""

import shutil
from pathlib import Path

from . import schemas, tools

_SKILL_NAMES = ("chroller-browser", "chroller-login")


def profile_skills_dir():
    try:
        from tools.skills_tool import skill_search_dirs
        _roots, active = skill_search_dirs()
        if active:
            return Path(active)
    except Exception:
        pass
    import os
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home) / "skills"
    return Path.home() / ".hermes" / "skills"


def install_skills(dest_root=None):
    root = Path(dest_root) if dest_root is not None else profile_skills_dir()
    category = root / "chroller"
    source = Path(__file__).resolve().parent / "skills"
    category.mkdir(parents=True, exist_ok=True)
    for name in _SKILL_NAMES:
        skill_md = source / name / "SKILL.md"
        if not skill_md.exists():
            continue
        target = category / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, target / "SKILL.md")
    return category


def register(ctx):
    try:
        config = ctx.get_config() or {}
    except Exception:
        config = {}
    url = ""
    if isinstance(config, dict):
        url = config.get("companion_url") or ""
    if url:
        tools.set_companion_url(url)
    try:
        install_skills()
    except OSError:
        pass
    for schema in schemas.ALL:
        ctx.register_tool(
            name=schema["name"],
            toolset="chroller",
            schema=schema,
            handler=tools.make_handler(schema["name"]),
        )
    skills_dir = Path(__file__).resolve().parent / "skills"
    for name in _SKILL_NAMES:
        skill_md = skills_dir / name / "SKILL.md"
        if skill_md.exists():
            ctx.register_skill(name, skill_md)
