from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from memory import (
    generate_task_recommendation,
    get_memory_bank_snapshot,
    get_memory_status,
    retain_meeting_notes,
    retain_task_update,
    retain_team_member,
)
from utils import (
    generic_assignment,
    normalize_skills,
    sample_meeting_notes,
    sample_tasks,
    sample_team_members,
    slugify,
)


st.set_page_config(page_title="TeamMind AI", layout="wide")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            .teammind-card {
                padding: 1rem 1.1rem;
                border: 1px solid rgba(49, 51, 63, 0.14);
                border-radius: 16px;
                background: linear-gradient(180deg, rgba(248, 250, 252, 0.95), rgba(241, 245, 249, 0.9));
                margin-bottom: 0.8rem;
            }
            .teammind-kicker {
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: #475569;
                margin-bottom: 0.35rem;
            }
            .teammind-title {
                font-size: 1.2rem;
                font-weight: 700;
                color: #0f172a;
                margin-bottom: 0.25rem;
            }
            .teammind-copy {
                color: #334155;
                line-height: 1.45;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    st.session_state.setdefault("team_members", [])
    st.session_state.setdefault("tasks", [])
    st.session_state.setdefault("meeting_notes", [])
    st.session_state.setdefault("seeded_demo", False)
    st.session_state.setdefault("current_page", "Workspace")


def upsert_team_member(member: dict[str, Any]) -> None:
    members = [item for item in st.session_state.team_members if item["name"] != member["name"]]
    members.append(member)
    members.sort(key=lambda item: item["name"])
    st.session_state.team_members = members


def upsert_task(task: dict[str, Any]) -> None:
    tasks = [item for item in st.session_state.tasks if item["title"] != task["title"]]
    tasks.append(task)
    tasks.sort(key=lambda item: item["deadline"])
    st.session_state.tasks = tasks


def add_meeting_note(note: dict[str, Any]) -> None:
    notes = [note, *st.session_state.meeting_notes]
    st.session_state.meeting_notes = notes[:10]


def seed_demo_data() -> None:
    st.session_state.team_members = sample_team_members()
    st.session_state.tasks = sample_tasks()
    st.session_state.meeting_notes = sample_meeting_notes()
    st.session_state.seeded_demo = True

    for member in st.session_state.team_members:
        retain_team_member(
            name=member["name"],
            skills=member["skills"],
            role=member["role"],
            document_id=f"member-{slugify(member['name'])}",
        )

    for task in st.session_state.tasks:
        retain_task_update(
            task_title=task["title"],
            assigned_member=task["assigned_member"],
            deadline=task["deadline"],
            status=task["status"],
            notes=task["notes"],
            required_skills=task["required_skills"],
            document_id=task["document_id"],
        )

    for note in st.session_state.meeting_notes:
        retain_meeting_notes(
            notes=note["summary"],
            document_id=note["document_id"],
        )


def render_sidebar() -> str:
    status = get_memory_status()
    snapshot = get_memory_bank_snapshot()
    st.sidebar.title("TeamMind AI")
    st.sidebar.caption("Hackathon-ready AI group project manager with memory.")
    st.sidebar.info(f"Memory mode: `{status.mode}`\n\nBank: `{status.bank_id}`")
    if status.enabled:
        st.sidebar.success(status.message)
    else:
        st.sidebar.warning(status.message)

    if snapshot.get("available"):
        metric_one, metric_two = st.sidebar.columns(2)
        metric_one.metric("Memories", snapshot.get("total_nodes", 0))
        metric_two.metric("Docs", snapshot.get("total_documents", 0))
        if snapshot.get("pending_operations", 0):
            st.sidebar.caption(
                f"Indexing in progress: {snapshot['pending_operations']} queued operations still being processed."
            )

    if st.sidebar.button("Load Sample Demo Data", use_container_width=True):
        seed_demo_data()
        st.sidebar.success(
            "Loaded sample team, tasks, and meeting notes. Hindsight is processing the demo memories in the background."
        )

    if st.sidebar.button("Reset Local Session", use_container_width=True):
        st.session_state.team_members = []
        st.session_state.tasks = []
        st.session_state.meeting_notes = []
        st.session_state.seeded_demo = False
        st.sidebar.info("Cleared local Streamlit session data.")

    return st.sidebar.radio(
        "Navigate",
        ["Workspace", "AI Suggestions"],
        key="current_page",
        label_visibility="collapsed",
    )


def render_header() -> None:
    snapshot = get_memory_bank_snapshot()
    st.title("TeamMind AI")
    st.write(
        "An AI group project manager that remembers team strengths, recurring blockers, "
        "delivery history, and meeting decisions so task assignment gets smarter over time."
    )
    top_metrics = st.columns(5)
    top_metrics[0].metric("Team Members", len(st.session_state.team_members))
    top_metrics[1].metric("Tasks", len(st.session_state.tasks))
    top_metrics[2].metric("Meeting Notes", len(st.session_state.meeting_notes))
    top_metrics[3].metric("Memory Facts", snapshot.get("total_nodes", 0))
    top_metrics[4].metric("Queued Jobs", snapshot.get("pending_operations", 0))


def show_memory_feedback(result: dict[str, Any], success_message: str) -> None:
    if result.get("ok"):
        st.success(f"{success_message} Hindsight is processing the memory in the background.")
    else:
        st.warning(result.get("message", "Saved locally, but memory is not available right now."))


def render_workspace() -> None:
    st.subheader("Project Workspace")
    st.caption("Capture team context, task updates, and meeting notes that Hindsight can remember and recall later.")
    snapshot = get_memory_bank_snapshot()

    st.markdown(
        f"""
        <div class="teammind-card">
            <div class="teammind-kicker">Memory Health</div>
            <div class="teammind-title">Project Memory Is {('Active' if snapshot.get('available') else 'Offline')}</div>
            <div class="teammind-copy">
                Hindsight currently tracks {snapshot.get('total_nodes', 0)} facts across
                {snapshot.get('total_documents', 0)} documents.
                {f" {snapshot.get('pending_operations', 0)} writes are still indexing in the background." if snapshot.get('pending_operations', 0) else ""}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    team_col, task_col = st.columns(2)

    with team_col:
        st.markdown("### Team Member Form")
        with st.form("team-member-form", clear_on_submit=True):
            member_name = st.text_input("Name", placeholder="Aisha Khan")
            member_role = st.text_input("Role", placeholder="Frontend Lead")
            member_skills = st.text_input("Skills", placeholder="Streamlit, Python, UI")
            add_member = st.form_submit_button("Save Team Member", use_container_width=True)

        if add_member and member_name and member_role:
            member = {
                "name": member_name.strip(),
                "role": member_role.strip(),
                "skills": normalize_skills(member_skills),
            }
            upsert_team_member(member)
            result = retain_team_member(member["name"], member["skills"], member["role"])
            show_memory_feedback(result, f"Saved {member['name']} and retained the update to memory.")

        st.markdown("### Current Team")
        if st.session_state.team_members:
            st.dataframe(st.session_state.team_members, use_container_width=True, hide_index=True)
        else:
            st.info("Load the sample demo data or add your first teammate.")

    with task_col:
        st.markdown("### Task Form")
        member_names = [member["name"] for member in st.session_state.team_members] or ["Unassigned"]
        with st.form("task-form", clear_on_submit=True):
            task_title = st.text_input("Task Title", placeholder="Build recommendation view")
            assigned_member = st.selectbox("Assigned Member", member_names)
            deadline = st.date_input("Deadline", value=date.today() + timedelta(days=2))
            status = st.selectbox("Status", ["Todo", "In Progress", "Blocked", "Delayed", "Completed"])
            required_skills = st.text_input("Required Skills", placeholder="Streamlit, Python")
            task_notes = st.text_area(
                "Task Notes / Blockers",
                placeholder="Add why the task matters, what is blocked, or how it was completed.",
                height=100,
            )
            add_task = st.form_submit_button("Save Task Update", use_container_width=True)

        if add_task and task_title:
            task = {
                "title": task_title.strip(),
                "assigned_member": assigned_member,
                "deadline": deadline.isoformat(),
                "status": status,
                "required_skills": normalize_skills(required_skills),
                "notes": task_notes.strip(),
            }
            upsert_task(task)
            result = retain_task_update(
                task_title=task["title"],
                assigned_member=task["assigned_member"],
                deadline=task["deadline"],
                status=task["status"],
                notes=task["notes"],
                required_skills=task["required_skills"],
            )
            show_memory_feedback(result, f"Saved task update for {task['title']} and retained it to memory.")

        st.markdown("### Active Tasks")
        if st.session_state.tasks:
            st.dataframe(st.session_state.tasks, use_container_width=True, hide_index=True)
        else:
            st.info("No tasks yet. Add one or load the sample data.")

    st.markdown("### Meeting Notes")
    st.caption("Tip: use prefixes like `Decision:`, `Blocker:`, and `Risk:` to create richer memory records.")
    with st.form("meeting-notes-form", clear_on_submit=True):
        meeting_notes = st.text_area(
            "Meeting Notes Input",
            placeholder=(
                "Decision: keep Aisha on demo UI.\n"
                "Blocker: backend reminder API schema still changing.\n"
                "Risk: reminder automation may slip one day."
            ),
            height=140,
        )
        save_notes = st.form_submit_button("Save Meeting Notes", use_container_width=True)

    if save_notes and meeting_notes.strip():
        note = {"summary": meeting_notes.strip()}
        add_meeting_note(note)
        result = retain_meeting_notes(meeting_notes.strip())
        show_memory_feedback(result, "Saved meeting notes and retained them to Hindsight memory.")

    if st.session_state.meeting_notes:
        for note in st.session_state.meeting_notes[:5]:
            st.info(note["summary"])
    else:
        st.info("No meeting notes captured yet.")


def build_suggestion_defaults() -> dict[str, Any]:
    if st.session_state.tasks:
        newest_task = st.session_state.tasks[0]
        return {
            "task_title": newest_task["title"],
            "required_skills": ", ".join(newest_task.get("required_skills", [])),
            "deadline": date.fromisoformat(newest_task["deadline"]),
            "blockers": newest_task.get("notes", ""),
        }
    return {
        "task_title": "Launch demo-ready recommendation screen",
        "required_skills": "Streamlit, Python",
        "deadline": date.today() + timedelta(days=1),
        "blockers": "Need the reminder flow to stay reliable for the demo.",
    }


def render_suggestions() -> None:
    st.subheader("AI Suggestions")
    st.caption("Compare generic assignment logic against Hindsight-backed recommendations that use recalled project memory.")
    snapshot = get_memory_bank_snapshot()

    lead_col, signal_col, queue_col = st.columns(3)
    lead_col.metric("Memory Facts Available", snapshot.get("total_nodes", 0))
    signal_col.metric("Indexed Documents", snapshot.get("total_documents", 0))
    queue_col.metric("Background Jobs", snapshot.get("pending_operations", 0))
    if snapshot.get("pending_operations", 0):
        st.info(
            "Hindsight is still indexing some memories. Recommendations improve as the queue drains, so run the same query again after a short wait."
        )

    defaults = build_suggestion_defaults()
    with st.form("suggestion-form"):
        task_title = st.text_input("Task to Assign", value=defaults["task_title"])
        required_skills = st.text_input("Required Skills", value=defaults["required_skills"])
        deadline = st.date_input("Deadline", value=defaults["deadline"])
        blockers = st.text_area("Known Blockers / Context", value=defaults["blockers"], height=100)
        generate = st.form_submit_button("Generate Recommendation", use_container_width=True)

    if not generate:
        st.info("Load the sample data and generate a recommendation to see the memory effect.")
        return

    required_skill_list = normalize_skills(required_skills)
    generic = generic_assignment(
        task_title=task_title,
        required_skills=required_skill_list,
        team_members=st.session_state.team_members,
        tasks=st.session_state.tasks,
    )
    memory_based = generate_task_recommendation(
        task_title=task_title,
        required_skills=required_skill_list,
        team_members=st.session_state.team_members,
        tasks=st.session_state.tasks,
        deadline=deadline,
        blockers=blockers,
    )

    generic_col, memory_col = st.columns(2)

    with generic_col:
        st.markdown("### Without Memory")
        st.metric("Suggested Assignee", generic["assignee"] or "No suggestion")
        st.write(generic["summary"])
        if generic["score_rows"]:
            st.dataframe(generic["score_rows"], use_container_width=True, hide_index=True)

    with memory_col:
        st.markdown("### With Hindsight Memory")
        st.metric("Suggested Assignee", memory_based["assignee"] or "No suggestion")
        st.write(memory_based["summary"])
        if memory_based["score_rows"]:
            st.dataframe(memory_based["score_rows"], use_container_width=True, hide_index=True)

    if memory_based.get("evidence"):
        st.markdown("### Memory Evidence For The Top Pick")
        for item in memory_based["evidence"]:
            st.write(f"- {item}")

    st.markdown("### Why The Memory Answer Is Different")
    if memory_based["memory_status"].enabled and memory_based["recalled_memories"]:
        if memory_based["decisions"]:
            st.write(f"- Meeting decisions recalled: {memory_based['decisions'][0]}")
        if memory_based["blockers"]:
            st.write(f"- Recurring blocker recalled: {memory_based['blockers'][0]}")
        for reminder in memory_based["reminders"]:
            st.write(f"- Reminder suggestion: {reminder}")
    elif memory_based["memory_status"].enabled:
        st.info(
            "Hindsight is connected, but it has not surfaced relevant memories for this query yet. "
            "If you just loaded demo data, give indexing a few seconds and try again."
        )
    else:
        st.warning("Hindsight is not available, so the recommendation cannot use project memory yet.")

    st.markdown("### Recalled Memory Context")
    st.code(memory_based["query"], language="text")
    if memory_based.get("query_variants"):
        with st.expander("Recall query variants"):
            for item in memory_based["query_variants"]:
                st.write(f"- {item}")
    if memory_based["recalled_memories"]:
        for memory in memory_based["recalled_memories"]:
            st.write(f"- {memory['text']}")
    else:
        st.info("No memory results were recalled for this query yet.")

    if snapshot.get("recent_memories"):
        with st.expander("Recent Memory Feed"):
            for item in snapshot["recent_memories"]:
                st.write(f"- {item.get('text', '')}")


inject_styles()
init_state()
page = render_sidebar()
render_header()

if page == "Workspace":
    render_workspace()
else:
    render_suggestions()
