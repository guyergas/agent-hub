"""Headless provider adapters for the local Agent Hub worker."""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path


def enabled():
    return os.environ.get("AGENT_HUB_ENABLE_AGENTS") == "1"


def status():
    return {"enabled": enabled(), "Codex": bool(shutil.which("codex")), "Claude": bool(shutil.which("claude"))}


def cli(args, cwd, prompt=None, timeout=300):
    return subprocess.run(args, cwd=cwd, input=prompt, text=True, capture_output=True, timeout=timeout)


def audit_checkout(root, source):
    target = root / "source"
    target.mkdir()
    archive = root / "source.zip"
    result = cli(["git", "archive", "--format=zip", "-o", str(archive), source["revision"]], source["checkout"], timeout=30)
    if result.returncode:
        raise RuntimeError("לא ניתן לקרוא את גרסת המקור שנקבעה לקליטה")
    with zipfile.ZipFile(archive) as files:
        entries = files.infolist()
        if sum(entry.file_size for entry in entries) > 150_000_000:
            raise RuntimeError("גרסת המקור גדולה מדי לסקירה במסלול הקליטה")
        for entry in entries:
            name = Path(entry.filename)
            if name.is_absolute() or ".." in name.parts or ".git" in name.parts or stat.S_ISLNK(entry.external_attr >> 16):
                continue
            files.extract(entry, target)
    return target


def run(job, directory):
    provider = job["provider"]
    binary = shutil.which(provider.lower())
    if not binary:
        raise RuntimeError(f"{provider} CLI אינו מותקן")
    with tempfile.TemporaryDirectory(prefix="agent-hub-") as tmp:
        root = Path(tmp)
        audit = job.get("audit_source")
        audit_dir = audit_checkout(root, audit) if audit else None
        checkout = job.get("checkout")
        worktree = None
        content_path = job.get("content_path")
        if job["role"] == "developer" or content_path:
            if not checkout or not Path(checkout).is_absolute() or not Path(checkout).is_dir():
                raise RuntimeError("הגדר נתיב מקומי מוחלט למאגר המוצר")
            branch = f"agent-hub/{job['product']}/{job['task']}-{job['id']}"
            worktree = directory / job["id"]
            directory.mkdir(parents=True, exist_ok=True)
            result = cli(["git", "worktree", "add", "-b", branch, str(worktree), "HEAD"], checkout, timeout=30)
            if result.returncode:
                raise RuntimeError("Git לא הצליח ליצור סביבת עבודה מבודדת")
        prompt = job["prompt"]
        if worktree:
            prompt += "\n\nEdit files only in this worktree. Report the files changed and any tests that still need to run. Git commits and remote operations are handled outside this run."
        if content_path:
            base = cli(["git", "rev-parse", "HEAD"], worktree, timeout=30)
            if base.returncode:
                return {"error": "Git לא הצליח לקרוא את גרסת הבסיס", "worktree": str(worktree)}
        try:
            if provider == "Codex":
                output = root / "result.txt"
                sandbox = "workspace-write" if worktree else "read-only"
                result = cli([binary, "exec", "--skip-git-repo-check", "--sandbox", sandbox, "--ignore-user-config", "--ephemeral", "--json", "-o", str(output), "-"], worktree or audit_dir or root, prompt)
                if result.returncode or not output.exists():
                    raise RuntimeError(f"Codex נכשל (קוד {result.returncode}). בדוק התחברות והגדרות CLI")
                usage = {}
                for line in result.stdout.splitlines():
                    event = json.loads(line)
                    if event.get("type") == "turn.completed":
                        usage = event.get("usage", {})
                answer = output.read_text(encoding="utf-8").strip()
                tokens = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens"))
                cents = 0
            else:
                cap = float(os.environ.get("AGENT_HUB_CLAUDE_RUN_USD", "2"))
                if job.get("remaining_cents") is not None:
                    cap = min(cap, job["remaining_cents"] / 100)
                if cap <= 0:
                    raise RuntimeError("תקציב Claude לריצה מוצה")
                tools = "Read,Glob,Grep,Edit,Write" if worktree else ""
                result = cli([binary, "-p", "--bare", "--output-format", "json", "--max-turns", "16",
                              "--max-budget-usd", str(cap), "--tools", tools,
                              "--disallowedTools", "mcp__*", "--strict-mcp-config",
                              *(["--permission-mode", "acceptEdits"] if worktree else [])], worktree or root, prompt)
                if result.returncode and not result.stdout.strip():
                    raise RuntimeError(f"Claude נכשל (קוד {result.returncode}). בדוק התחברות והגדרות CLI")
                response = json.loads(result.stdout)
                usage = response.get("usage", {})
                tokens = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                cents = round(float(response.get("total_cost_usd", 0)) * 100)
                if result.returncode or response.get("is_error"):
                    return {"error": f"Claude נכשל (קוד {result.returncode}). בדוק התחברות ותקציב", "tokens": tokens, "cents": cents, "worktree": str(worktree or "")}
                answer = str(response.get("result", "")).strip()
        except (subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
            return {"error": str(error) if isinstance(error, RuntimeError) else "הריצה חרגה מהזמן או החזירה פלט לא תקין", "worktree": str(worktree or "")}
        if not answer:
            return {"error": "הסוכן החזיר תשובה ריקה", "tokens": tokens, "cents": cents, "worktree": str(worktree or "")}
        if content_path:
            changes = cli(["git", "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"], worktree, timeout=30)
            head = cli(["git", "rev-parse", "HEAD"], worktree, timeout=30)
            current_branch = cli(["git", "symbolic-ref", "--short", "HEAD"], worktree, timeout=30)
            entries = [entry[3:] for entry in changes.stdout.split("\0") if entry]
            if changes.returncode or head.returncode or current_branch.returncode or head.stdout != base.stdout or current_branch.stdout.strip() != branch or any(not name.startswith(content_path + "/") for name in entries):
                return {"error": "הרצת התוכן חרגה מתיקיית התוכן או שינתה את היסטוריית הענף. בדוק את סביבת העבודה", "tokens": tokens, "cents": cents, "worktree": str(worktree)}
        return {"answer": answer[:50000], "tokens": tokens, "cents": cents, "worktree": str(worktree or "")}
