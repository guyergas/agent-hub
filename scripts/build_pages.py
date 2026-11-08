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
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath

class BrowserRunners:
    connected = False

    def enabled(self):
        return self.connected

    @staticmethod
    def supports(role, task):
        return role in ROLES and ROLES[role][0] == "Codex"

runners = BrowserRunners()

def takeover_source(product, data):
    need(product.get("repo"), "נדרשת כתובת מאגר")
    return "", require_commit(data, "revision")

def browser_claim(state):
    now = time.time()
    changed = False
    for product in state["products"]:
        intake = product.get("takeover")
        if intake and intake.get("scan"):
            for role in TAKEOVER_ROLES.get(intake["status"], ()):
                if not any(j.get("takeover") == intake["id"] and j["role"] == role for j in product.get("jobs", [])):
                    queue_job(state, product, role, manager=intake["manager"], takeover=intake["id"])
                    changed = True
        for job in product.get("jobs", []):
            if job["status"] == "running" and now - job["started"] > 100:
                job.update(status="failed", error="הרצת הדפדפן נקטעה. אפשר להריץ שוב.")
                changed = True
            if job["status"] != "queued" or job["provider"] != "Codex":
                continue
            try:
                limit = product["token_limit"]
                need(not limit or sum(r["tokens"] for r in product["runs"]) < limit, "מכסת הטוקנים של המוצר מוצתה")
                prompt = job_prompt(state, product, job)
            except ValueError as error:
                job.update(status="failed", error=str(error))
                changed = True
                continue
            job.update(status="running", started=now)
            return {"payload": {"job": {"id": job["id"], "product": product["id"], "started": now, "prompt": prompt}}, "state": state}
    return {"payload": {"job": None}, **({"state": state} if changed else {})}

def browser_finish(state, data):
    product = lookup(state["products"], required(data, "product"))
    job = lookup(product["jobs"], required(data, "id"))
    need(job["provider"] == "Codex" and job["status"] == "running" and job["started"] == data.get("started"),
         "הרצת הסוכן כבר הסתיימה")
    error, answer = value(data, "error")[:1000], value(data, "answer")[:50000]
    need(bool(error or answer), "נדרשת תוצאת הרצה")
    tokens = number(data, "tokens", 0, 10000000)
    job.update(status="failed" if error else "done", error=error, answer=answer, tokens=tokens)
    if job["chat"]:
        chat = lookup(product["chats"], job["chat"])
        chat["messages"].append({"role": "system" if error else "manager", "text": error or answer})
    if answer and job["task"] and job["role"] in ("architect", "designer"):
        task = lookup(product["tasks"], job["task"])
        area = "architecture" if job["role"] == "architect" else "design"
        source = task["id"] + ("@" + job["revision"] if job["revision"] else "")
        submit_domain_conclusion(state, product, area, task["title"], answer, source, task["manager"])
    if tokens:
        product["runs"].append({"role": job["role"], "tokens": tokens, "cents": 0, "reference": job["id"]})

def web_request(path, data_json, state_json, connected=False):
    data = json.loads(data_json)
    state = json.loads(state_json)
    runners.connected = connected
    try:
        if path == "/change":
            apply(state, data)
        elif path == "/agent_claim":
            need(connected, "חבר Codex כדי להריץ סוכנים")
            return json.dumps(browser_claim(state), ensure_ascii=False)
        elif path == "/agent_finish":
            browser_finish(state, data)
        elif path == "/packet":
            result = packet(state, *(value(data, key) for key in ("product", "role", "task", "manager", "request", "release", "rule_area")))
            return json.dumps({"payload": {"packet": result}})
        elif path != "/state":
            raise ValueError("פעולה לא מוכרת")
        payload = {**state, "providers": {"enabled": connected, "Codex": connected, "Claude": False, "browser": True},
                   "development_portfolio": development_portfolio(state)}
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
    html = html.replace("כדי לשלוח הודעות, הפעל את החיבור לסוכנים לפי ההוראות.", "בגרסת Pages אפשר להכין דרישה מהשיחה ולהעביר אותה ללוח. שליחה לסוכן דורשת חיבור ריצה.")
    html = html.replace("הרצה אוטומטית כבויה. הפעל את מחברי הסוכנים לפי ההוראות.", "הלוח הזה שומר מידע בדפדפן. להרצת סוכן השתמש בחבילת עבודה עד שיחובר תור ההרצות.")
    html = html.replace('<script>\n"use strict";', '<script src="./runtime/pyodide.js"></script>\n<script src="./vault.js"></script>\n<script src="./repository-scan.js"></script>\n<script src="./ceo-ai.js"></script>\n<script>\n"use strict";', 1)
    (DIST / "index.html").write_text(html)
    (DIST / "core.py").write_text(browser_core((ROOT / "hub.py").read_text()))
    for name in ("vault.js", "repository-scan.js", "repository-reviews.json", "ceo-ai.js"):
        shutil.copyfile(ROOT / "pages" / name, DIST / name)
    runtime = DIST / "runtime"
    runtime.mkdir()
    for name in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip"):
        shutil.copyfile(ROOT / "node_modules" / "pyodide" / name, runtime / name)
    (DIST / ".nojekyll").touch()


if __name__ == "__main__":
    main()
