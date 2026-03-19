from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import uuid

app = FastAPI()
templates = Jinja2Templates(directory="templates")

sessions = {}

# -----------------------------
# Create Session
# -----------------------------
def new_session():
    sid = str(uuid.uuid4())
    sessions[sid] = {
        "trigger": "PPE Violation Detected",
        "history": [],

        "selected_actions": [],
        "action_queue": [],
        "configured_actions": {},

        "monitor_enabled": None,

        # Escalation rules (policy statements)
        "escalation_rules": {
            "repeat": {"enabled": False, "count": 3, "hours": 24},
            "score": {"enabled": False, "threshold": 60},
            "duration": {"enabled": False, "minutes": 5}
        },
        "logic_type": None,

        "escalation_actions": [],
        "escalation_queue": [],
        "configured_escalation": {}
    }
    return sid


def add_history(session, q, a):
    session["history"].append({"question": q, "answer": a})


# -----------------------------
# Decision Engine
# -----------------------------
def get_next_question(session):

    # STEP 1: Immediate Response
    if not session["selected_actions"]:
        return {
            "type": "multi",
            "question": "When a worker violates PPE policy, how should the system respond?",
            "options": [
                "Inform worker",
                "Inform supervisor",
                "Announce on nearby PA system",
                "Subtract safety score",
                "Just keep a record"
            ],
            "field": "selected_actions"
        }

    # STEP 2: Configure Selected Actions
    if session["action_queue"]:
        current = session["action_queue"][0]

        if current == "Inform worker":
            if "channel" not in session["configured_actions"].get(current, {}):
                return {
                    "type": "multi",
                    "question": "How should the worker be informed?",
                    "options": [
                        "Mobile app notification",
                        "Smart hat voice alert"
                    ],
                    "field": "worker_channel"
                }

            if "message" not in session["configured_actions"][current]:
                return {
                    "type": "text",
                    "question": "What message should the worker receive?",
                    "default": "You are not wearing required PPE. Please correct immediately.",
                    "field": "worker_message"
                }

            if "audio_mode" not in session["configured_actions"][current]:
                return {
                    "type": "multi",
                    "question": "How should this message be delivered?",
                    "options": [
                        "Send as text",
                        "Convert text to speech",
                        "Upload recorded voice message"
                    ],
                    "field": "worker_audio_mode"
                }

            session["action_queue"].pop(0)
            return get_next_question(session)

        if current == "Inform supervisor":
            if "channel" not in session["configured_actions"].get(current, {}):
                return {
                    "type": "multi",
                    "question": "How should the supervisor be notified?",
                    "options": ["Email", "WhatsApp", "Slack"],
                    "field": "supervisor_channel"
                }

            session["action_queue"].pop(0)
            return get_next_question(session)

        if current == "Subtract safety score":
            if "points" not in session["configured_actions"].get(current, {}):
                return {
                    "type": "number",
                    "question": "How many safety points should be deducted?",
                    "field": "score_points"
                }

            session["action_queue"].pop(0)
            return get_next_question(session)

        if current == "Announce on nearby PA system":
            if "message" not in session["configured_actions"].get(current, {}):
                return {
                    "type": "text",
                    "question": "What announcement should be played on the PA system?",
                    "field": "pa_message"
                }

            session["action_queue"].pop(0)
            return get_next_question(session)

        if current == "Just keep a record":
            session["action_queue"].pop(0)
            return get_next_question(session)

    # STEP 3: Monitoring
    if session["monitor_enabled"] is None:
        return {
            "type": "toggle",
            "question": "Should this escalate if the same worker repeats the violation?",
            "field": "monitor_enabled"
        }

    # STEP 4: Escalation Rules (Policy Statements)
    if session["monitor_enabled"] and session["logic_type"] is None:
        return {
            "type": "policy",
            "question": "Define escalation rules:",
        }

    # STEP 5: Logic Type
    if session["monitor_enabled"] and session["logic_type"] is None:
        return {
            "type": "logic",
            "question": "When should escalation trigger?",
            "options": [
                "Only when ALL selected rules are true",
                "When ANY selected rule is true"
            ],
            "field": "logic_type"
        }

    # STEP 6: Escalation Actions
    if session["monitor_enabled"] and not session["escalation_actions"]:
        return {
            "type": "multi",
            "question": "If escalation conditions are met, what should happen?",
            "options": [
                "Notify management",
                "Suspend access",
                "Refer for safety training"
            ],
            "field": "escalation_actions"
        }

    if session["escalation_queue"]:
        current = session["escalation_queue"][0]

        if current == "Notify management":
            if "channel" not in session["configured_escalation"].get(current, {}):
                return {
                    "type": "multi",
                    "question": "How should management be notified?",
                    "options": ["Email", "Slack"],
                    "field": "management_channel"
                }

        if current == "Refer for safety training":
            if "assigned_to" not in session["configured_escalation"].get(current, {}):
                return {
                    "type": "text",
                    "question": "Who should conduct the safety training?",
                    "field": "training_officer"
                }

        session["escalation_queue"].pop(0)
        return get_next_question(session)

    return None

# -----------------------------
# FLOW BUILDER (FOR SUMMARY)
# -----------------------------
def build_flow(session):

    flow = []

    # 1. Event Node
    flow.append({
        "type": "event",
        "label": session["trigger"]
    })

    # 2. Operation Nodes (Immediate)
    for action, config in session["configured_actions"].items():
        flow.append({
            "type": "operation",
            "label": action,
            "details": config
        })

    # 3. Check Node (If monitoring enabled)
    if session["monitor_enabled"]:
        flow.append({
            "type": "check",
            "label": "Escalation Rules",
            "details": session["escalation_rules"],
            "logic": session["logic_type"]
        })

        # 4. Escalation Operations
        for action, config in session["configured_escalation"].items():
            flow.append({
                "type": "operation",
                "label": action,
                "details": config
            })

    return flow

# -----------------------------
# ROUTES
# -----------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/start")
def start():
    sid = new_session()
    return RedirectResponse(f"/configure/{sid}", status_code=302)


@app.get("/configure/{sid}", response_class=HTMLResponse)
def configure(request: Request, sid: str):
    session = sessions[sid]
    question = get_next_question(session)
    return templates.TemplateResponse("configure.html", {
        "request": request,
        "session": session,
        "question": question,
        "sid": sid
    })


@app.post("/answer/{sid}")
async def answer(sid: str, request: Request):
    session = sessions[sid]
    form = await request.form()
    question = get_next_question(session)

    if not question:
        return RedirectResponse(f"/summary/{sid}", status_code=302)

    field = question.get("field")

    if question["type"] == "multi":
        selected = form.getlist(field)

        if field == "selected_actions":
            session["selected_actions"] = selected
            session["action_queue"] = selected.copy()

        elif field == "worker_channel":
            session["configured_actions"].setdefault("Inform worker", {})["channel"] = selected

        elif field == "worker_audio_mode":
            session["configured_actions"].setdefault("Inform worker", {})["audio_mode"] = selected
            session["action_queue"].pop(0)

        elif field == "supervisor_channel":
            session["configured_actions"].setdefault("Inform supervisor", {})["channel"] = selected
            session["action_queue"].pop(0)

        elif field == "escalation_actions":
            session["escalation_actions"] = selected
            session["escalation_queue"] = selected.copy()

        elif field == "management_channel":
            session["configured_escalation"].setdefault("Notify management", {})["channel"] = selected
            session["escalation_queue"].pop(0)

        add_history(session, question["question"], ", ".join(selected))

    elif question["type"] == "toggle":
        val = form.get(field)
        session["monitor_enabled"] = (val == "yes")
        add_history(session, question["question"], "Yes" if val == "yes" else "No")

    elif question["type"] == "number":
        val = form.get(field)
        session["configured_actions"].setdefault("Subtract safety score", {})["points"] = val
        session["action_queue"].pop(0)
        add_history(session, question["question"], val)

    elif question["type"] == "text":
        val = form.get(field)

        if field == "worker_message":
            session["configured_actions"].setdefault("Inform worker", {})["message"] = val

        elif field == "pa_message":
            session["configured_actions"].setdefault("Announce on nearby PA system", {})["message"] = val
            session["action_queue"].pop(0)

        elif field == "training_officer":
            session["configured_escalation"].setdefault("Refer for safety training", {})["assigned_to"] = val
            session["escalation_queue"].pop(0)

        add_history(session, question["question"], val)

    elif question["type"] == "policy":
        session["escalation_rules"]["repeat"]["enabled"] = "repeat" in form
        session["escalation_rules"]["repeat"]["count"] = int(form.get("repeat_count", 3))
        session["escalation_rules"]["repeat"]["hours"] = int(form.get("repeat_hours", 24))

        session["escalation_rules"]["score"]["enabled"] = "score" in form
        session["escalation_rules"]["score"]["threshold"] = int(form.get("score_threshold", 60))

        session["escalation_rules"]["duration"]["enabled"] = "duration" in form
        session["escalation_rules"]["duration"]["minutes"] = int(form.get("duration_minutes", 5))

        add_history(session, "Escalation rules defined", "Policy statements configured")
        session["logic_type"] = "pending"

    elif question["type"] == "logic":
        session["logic_type"] = form.get(field)
        add_history(session, question["question"], session["logic_type"])

    return RedirectResponse(f"/configure/{sid}", status_code=302)


@app.get("/summary/{sid}", response_class=HTMLResponse)
def summary(request: Request, sid: str):
    session = sessions[sid]

    nodes = []
    edges = []

    # 1️⃣ Event Node
    nodes.append({
        "id": "event",
        "type": "Event",
        "label": session["trigger"]
    })

    last_node_id = "event"

    # 2️⃣ Immediate Operation Nodes
    for i, action in enumerate(session["selected_actions"]):
        node_id = f"op_{i}"
        nodes.append({
            "id": node_id,
            "type": "Operation",
            "label": action
        })
        edges.append({"from": last_node_id, "to": node_id})
        last_node_id = node_id

    # 3️⃣ If escalation enabled → add Check node
    if session["monitor_enabled"]:

        check_id = "check_escalation"

        nodes.append({
            "id": check_id,
            "type": "Check",
            "label": "Escalation Conditions"
        })

        edges.append({"from": last_node_id, "to": check_id})

        # YES branch
        yes_last = check_id
        for i, action in enumerate(session["escalation_actions"]):
            node_id = f"esc_{i}"
            nodes.append({
                "id": node_id,
                "type": "Operation",
                "label": action
            })
            edges.append({
                "from": yes_last,
                "to": node_id,
                "label": "YES"
            })
            yes_last = node_id

        nodes.append({
            "id": "end_yes",
            "type": "End",
            "label": "Escalation Complete"
        })

        edges.append({"from": yes_last, "to": "end_yes"})

        # NO branch
        nodes.append({
            "id": "end_no",
            "type": "End",
            "label": "No Escalation"
        })

        edges.append({
            "from": check_id,
            "to": "end_no",
            "label": "NO"
        })

    else:
        nodes.append({
            "id": "end_simple",
            "type": "End",
            "label": "Process Complete"
        })
        edges.append({"from": last_node_id, "to": "end_simple"})

    return templates.TemplateResponse("summary.html", {
        "request": request,
        "nodes": nodes,
        "edges": edges
    })




if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
