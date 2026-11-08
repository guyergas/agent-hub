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
