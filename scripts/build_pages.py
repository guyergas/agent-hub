"""Build the static Agent Hub dashboard from the shared Python rules."""
import ast
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def browser_core(source):
    tree = ast.parse(source)
    constants = {"ROLES", "RULE_OWNERS", "COMPANY_ROLES", "TAKEOVER_ROLES", "DEFAULT_DEVELOPMENT_SLOTS"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "save_state":
            break
        if isinstance(node, ast.FunctionDef) and node.name != "takeover_source":
            nodes.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants:
            nodes.append(ast.get_source_segment(source, node))
    adapter = """
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath

class DisabledRunners:
    @staticmethod
    def enabled():
        return False

runners = DisabledRunners()

def takeover_source(product, data):
    need(product.get("repo"), "נדרשת כתובת מאגר")
    return "", require_commit(data, "revision")

def web_request(path, data_json, state_json):
    data = json.loads(data_json)
    state = json.loads(state_json)
    try:
        if path == "/change":
            apply(state, data)
        elif path == "/packet":
            result = packet(state, *(value(data, key) for key in ("product", "role", "task", "manager", "request", "release", "rule_area")))
            return json.dumps({"payload": {"packet": result}})
        elif path != "/state":
            raise ValueError("פעולה לא מוכרת")
        payload = {**state, "providers": {"enabled": False}, "development_portfolio": development_portfolio(state)}
        return json.dumps({"payload": payload, "state": state}, ensure_ascii=False)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        return json.dumps({"error": str(error)}, ensure_ascii=False)
"""
    return "\n\n".join(nodes) + "\n\n" + adapter


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    html = (ROOT / "index.html").read_text()
    html = html.replace('const token = "__HUB_TOKEN__";', "const token = null;")
    html = html.replace('    field("checkout","נתיב מקומי מוחלט למאגר (להרצת מפתחים)", "text",p?.checkout),\n', "")
    html = html.replace("if(p.checkout && managers.length)", "if(p.repo && managers.length)")
    html = html.replace('area("transcript","הדבק את שיחת המימוש או את הקטעים הרלוונטיים")', 'field("revision","SHA של גרסת המקור (40 תווים)"),\n      area("transcript","הדבק את שיחת המימוש או את הקטעים הרלוונטיים")')
    html = html.replace("הגדר מאגר מקומי ומנהל מוצר", "הגדר כתובת מאגר ומנהל מוצר")
    html = html.replace("כדי לשלוח הודעות, הפעל את החיבור לסוכנים לפי ההוראות.", "בגרסת Pages אפשר להכין דרישה מהשיחה ולהעביר אותה ללוח. שליחה לסוכן דורשת חיבור ריצה.")
    html = html.replace("הרצה אוטומטית כבויה. הפעל את מחברי הסוכנים לפי ההוראות.", "הלוח הזה שומר מידע בדפדפן. להרצת סוכן השתמש בחבילת עבודה עד שיחובר תור ההרצות.")
    html = html.replace('<script>\n"use strict";', '<script src="./runtime/pyodide.js"></script>\n<script src="./vault.js"></script>\n<script>\n"use strict";', 1)
    (DIST / "index.html").write_text(html)
    (DIST / "core.py").write_text(browser_core((ROOT / "hub.py").read_text()))
    shutil.copyfile(ROOT / "pages" / "vault.js", DIST / "vault.js")
    runtime = DIST / "runtime"
    runtime.mkdir()
    for name in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip"):
        shutil.copyfile(ROOT / "node_modules" / "pyodide" / name, runtime / name)
    (DIST / ".nojekyll").touch()


if __name__ == "__main__":
    main()
