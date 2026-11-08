import json
from pathlib import Path

from build_pages import browser_core

source = Path(__file__).resolve().parents[1] / "hub.py"
namespace = {}
exec(compile(browser_core(source.read_text()), "core.py", "exec"), namespace)
web_request = namespace["web_request"]
state = {"seq": 0, "products": [], "events": []}


def call(path, **data):
    global state
    response = json.loads(web_request(path, json.dumps(data), json.dumps(state)))
    if "state" in response:
        state = response["state"]
    return response


result = call("/change", action="product", name="Pilot", slots=2, project_status="active",
              repo="https://github.com/example/pilot", site_url="https://example.com")
project = result["payload"]["products"][0]
assert project["site_url"] == "https://example.com"
assert project["project_status"] == "active"
assert result["payload"]["providers"]["enabled"] is False
product = project["id"]
manager = call("/change", action="manager", product=product, scope="product", name="PM", context="Pilot")["payload"]["products"][0]["managers"][0]["id"]
assert "error" in call("/change", action="takeover_open", product=product, manager=manager,
                       transcript="Test transcript", revision="bad")
assert "payload" in call("/change", action="takeover_open", product=product, manager=manager,
                         transcript="Test transcript", revision="a"*40)
task = call("/change", action="task", product=product, manager=manager, title="UI", brief="Test brief", area="ui", priority=1)["payload"]["products"][0]["tasks"][0]["id"]
assert "pre-implementation" in call("/packet", product=product, task=task, role="designer")["payload"]["packet"]
assert "error" in call("/packet", product=product, task=task, role="architect")
assert "payload" in call("/change", action="design_spec", product=product, task=task, design_spec="Test spec")
assert "Test spec" in call("/packet", product=product, task=task, role="architect")["payload"]["packet"]
assert call("/state")["payload"]["development_portfolio"]["slots"] == 2
print("Static dashboard rules passed")
setup = dict(repository_mode="existing",base_branch="main",deployment_mode="pages",
             deployment_status="pending",database_mode="d1",database_status="pending",
             database_reference="Pilot database")
configured = call("/change", action="rules", product=product, slots=2, **setup)["payload"]["products"][0]
assert configured["setup"] == setup
assert "error" in call("/change", action="rules", product=product, slots=2,
                       **{**setup, "database_mode":"invalid"})
browser = call("/change", action="rules", product=product, slots=2,
               **{**setup, "database_mode":"browser"})["payload"]["products"][0]
assert browser["setup"]["database_reference"] == ""
print("Project setup metadata passed")

# Scanned projects may be taken over without a conversation transcript.
new = call("/change", action="product", name="Scanned", slots=2, repo="https://github.com/example/scanned")["payload"]["products"][-1]
pid = new["id"]
new_pm = call("/change", action="manager", product=pid, scope="product", name="PM", context="Intake")["payload"]["products"][-1]["managers"][0]["id"]
result = call("/change", action="takeover_open", product=pid, manager=new_pm, revision="b"*40,
              scan={"summary":"Detected product", "files":["README.md"], "design":"CSS"})
intake = result["payload"]["products"][-1]["takeover"]
assert intake["transcript"] == "" and intake["scan"]["summary"] == "Detected product"
assert intake["scan"]["files"] == ["README.md"] and intake["revision"] == "b"*40
print("Repository scan intake passed")

# Simulate a configured browser and verify the Codex-only dispatch boundary.
def connected(path, **data):
    global state
    result = json.loads(web_request(path, json.dumps(data), json.dumps(state), True))
    if "state" in result:
        state = result["state"]
    return result

result = connected("/change", action="ceo_ai_record", message="Improve the landing page", reply="One proposal",
                   items=[dict(project=product, manager=manager, role="designer", area="ui", title="Landing", brief="Clarify navigation")])
suggestion = result["payload"]["ceo_ai"][0]["items"][0]
assert connected("/change", action="ceo_ai_accept", product=product, suggestion=suggestion["id"])["payload"]
assert "error" in connected("/change", action="ceo_ai_accept", product=product, suggestion=suggestion["id"])
result = connected("/agent_claim")["payload"]["job"]
assert "pre-implementation" in result["prompt"]
result.pop("prompt")
assert "payload" in connected("/agent_finish", **result, answer="Design notes", tokens=30)
assert "error" in connected("/change", action="agent_run", role="lead", product=product)
assert not any(job["provider"]=="Claude" for p in state["products"] for job in p.get("jobs", []))
print("CEO intake and Codex-only browser queue passed")

# Code review is required for both UI and backend changes, and design review
# is requested by the shared reviewer on the specific revision.
state = {"seq": 0, "products": [], "events": []}
project = call("/change", action="product", name="Review", slots=2,
               repo="https://github.com/example/review")["payload"]["products"][0]["id"]
task = call("/change", action="task", product=project, title="UI", brief="Review", area="ui",
            priority=1)["payload"]["products"][0]["tasks"][0]["id"]
assert call("/change", action="design_spec", product=project, task=task, design_spec="Keep layout")["payload"]
assert call("/change", action="plan", product=project, task=task, plan="Refactor UI module")["payload"]
assert call("/change", action="start", product=project, task=task, owner="Developer")["payload"]
review = dict(product=project, task=task, revision="a"*40, pr="https://github.com/example/review/pull/1",
              preview="https://example.com/preview")
assert connected("/change", action="review", **review)["payload"]
jobs = state["products"][0]["jobs"]
assert [j["role"] for j in jobs] == ["reviewer"]
assert "error" in call("/change", action="check", role="designer", result="pass", evidence="Preview", **review)
assert "סוקר קוד" in call("/change", action="done", merged="c"*40, **review)["error"]
job = connected("/agent_claim")["payload"]["job"]
assert job["role"] == "reviewer" and job["pr"] == review["pr"]
assert connected("/agent_finish", **{k:job[k] for k in ("id","product","started")},
                 answer="Layout changes need design", review={"outcome":"pass","design":"required"})["payload"]
assert [j["role"] for j in state["products"][0]["jobs"]] == ["reviewer", "designer"]
assert call("/change", action="check", role="qa", result="pass", evidence="Tests passed", **review)["payload"]
assert "מעצב" in call("/change", action="done", merged="c"*40, **review)["error"]
assert call("/change", action="check", role="designer", result="pass", evidence="Preview checked", **review)["payload"]
new = {**review,"revision":"b"*40}
assert call("/change", action="review", **new)["payload"]
assert state["products"][0]["tasks"][0]["checks"] == {}
assert "error" in call("/change", action="check", role="reviewer", result="pass", evidence="Old", design="not_needed", **review)
assert call("/change", action="check", role="reviewer", result="pass", evidence="Diff reviewed", design="not_needed", **new)["payload"]
assert call("/change", action="check", role="qa", result="pass", evidence="Tests passed", **new)["payload"]
assert call("/change", action="done", merged="c"*40, **new)["payload"]
print("Shared code review, conditional design referral, and revision reset passed")
