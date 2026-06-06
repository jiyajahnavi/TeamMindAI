from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any


MEMORY_PREFIXES = {
    "team": "TEAM_MEMBER",
    "task": "TASK_UPDATE",
    "meeting": "MEETING_NOTE",
}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return value.strip("-") or "item"


def normalize_skills(raw_skills: Any) -> list[str]:
    if isinstance(raw_skills, list):
        skills = raw_skills
    else:
        skills = str(raw_skills or "").split(",")

    normalized: list[str] = []
    for skill in skills:
        cleaned = str(skill).strip()
        if cleaned and cleaned.lower() not in {item.lower() for item in normalized}:
            normalized.append(cleaned)
    return normalized


def format_deadline(deadline: date | datetime | str | None) -> str:
    if deadline is None:
        return "No deadline"
    if isinstance(deadline, datetime):
        return deadline.date().isoformat()
    if isinstance(deadline, date):
        return deadline.isoformat()
    return str(deadline)


def memory_line(kind: str, **fields: Any) -> str:
    parts = [kind]
    for key, value in fields.items():
        if value is None:
            continue
        label = key.replace("_", " ")
        if isinstance(value, list):
            clean_value = ", ".join(str(item) for item in value if str(item).strip())
        else:
            clean_value = str(value).strip()
        if clean_value:
            parts.append(f"{label}: {clean_value}")
    return " | ".join(parts)


def parse_memory_line(text: str) -> dict[str, str]:
    pieces = [piece.strip() for piece in str(text or "").split("|") if piece.strip()]
    parsed: dict[str, str] = {}
    if not pieces:
        return parsed

    parsed["kind"] = pieces[0]
    for piece in pieces[1:]:
        if ":" not in piece:
            continue
        key, value = piece.split(":", 1)
        parsed[key.strip().lower().replace(" ", "_")] = value.strip()
    return parsed


def skill_overlap(member_skills: list[str], required_skills: list[str]) -> int:
    if not required_skills:
        return 0

    member_skill_set = {skill.lower() for skill in member_skills}
    required_skill_set = {skill.lower() for skill in required_skills}
    return len(member_skill_set & required_skill_set)


def current_load(member_name: str, tasks: list[dict[str, Any]]) -> int:
    active_statuses = {"todo", "in progress", "blocked", "delayed"}
    load = 0
    for task in tasks:
        if task.get("assigned_member") != member_name:
            continue
        if str(task.get("status", "")).lower() in active_statuses:
            load += 1
    return load


def generic_assignment(
    task_title: str,
    required_skills: list[str],
    team_members: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not team_members:
        return {
            "assignee": None,
            "summary": "Add at least one team member to get an assignment suggestion.",
            "score_rows": [],
        }

    score_rows: list[dict[str, Any]] = []
    for member in team_members:
        name = member["name"]
        skills = normalize_skills(member.get("skills", []))
        overlap = skill_overlap(skills, required_skills)
        load = current_load(name, tasks)
        role_bonus = 1 if any(word.lower() in member.get("role", "").lower() for word in task_title.split()) else 0
        score = overlap * 4 + role_bonus - load
        score_rows.append(
            {
                "member": name,
                "role": member.get("role", ""),
                "score": score,
                "skill_matches": overlap,
                "active_tasks": load,
            }
        )

    score_rows.sort(key=lambda row: (row["score"], row["skill_matches"], -row["active_tasks"]), reverse=True)
    top_choice = score_rows[0]
    explanation = (
        f"Assign to {top_choice['member']} based on current skills and workload only. "
        "This baseline ignores historical delivery patterns and past meeting decisions."
    )
    return {
        "assignee": top_choice["member"],
        "summary": explanation,
        "score_rows": score_rows,
    }


def extract_memory_insights(
    recalled_memories: list[dict[str, Any]],
    team_members: list[dict[str, Any]],
    required_skills: list[str],
) -> dict[str, Any]:
    member_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "completed": 0,
            "delayed": 0,
            "blocked": 0,
            "meeting_mentions": 0,
            "skill_proof": 0,
            "evidence": [],
        }
    )
    decisions: list[str] = []
    blockers: list[str] = []

    known_members = {member["name"] for member in team_members}

    for memory in recalled_memories:
        text = memory.get("text", "")
        context = str(memory.get("context", ""))
        parsed = parse_memory_line(text)
        kind = parsed.get("kind", "")

        if kind == MEMORY_PREFIXES["task"]:
            assignee = parsed.get("assigned_to", "")
            status = parsed.get("status", "").lower()
            task_skills = normalize_skills(parsed.get("required_skills", ""))
            matched_skills = skill_overlap(task_skills, required_skills)

            if assignee in known_members:
                if "complete" in status:
                    member_stats[assignee]["completed"] += 1
                if "delay" in status:
                    member_stats[assignee]["delayed"] += 1
                if "block" in status:
                    member_stats[assignee]["blocked"] += 1
                if matched_skills:
                    member_stats[assignee]["skill_proof"] += matched_skills
                member_stats[assignee]["evidence"].append(text)

        if kind == MEMORY_PREFIXES["meeting"]:
            decisions_text = parsed.get("decisions", "")
            blockers_text = parsed.get("blockers", "")
            if decisions_text:
                decisions.append(decisions_text)
            if blockers_text:
                blockers.append(blockers_text)

            lowered = text.lower()
            for member_name in known_members:
                if member_name.lower() in lowered:
                    member_stats[member_name]["meeting_mentions"] += 1
                    member_stats[member_name]["evidence"].append(text)

        if kind not in MEMORY_PREFIXES.values():
            lowered = text.lower()
            lowered_context = context.lower()

            for member_name in known_members:
                if member_name.lower() not in lowered:
                    continue

                if "complete" in lowered:
                    member_stats[member_name]["completed"] += 1
                if "delay" in lowered or "slip" in lowered:
                    member_stats[member_name]["delayed"] += 1
                if "block" in lowered or "waiting" in lowered:
                    member_stats[member_name]["blocked"] += 1

                skill_hits = sum(1 for skill in required_skills if skill.lower() in lowered)
                if skill_hits:
                    member_stats[member_name]["skill_proof"] += skill_hits

                if "meeting" in lowered_context or "decision" in lowered or "risk" in lowered:
                    member_stats[member_name]["meeting_mentions"] += 1

                member_stats[member_name]["evidence"].append(text)

            if "decision" in lowered:
                decisions.append(text)
            if "blocker" in lowered or "blocked" in lowered or "risk" in lowered:
                blockers.append(text)

    return {
        "member_stats": member_stats,
        "decisions": decisions,
        "blockers": blockers,
    }


def memory_based_assignment(
    task_title: str,
    required_skills: list[str],
    team_members: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    recalled_memories: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline = generic_assignment(task_title, required_skills, team_members, tasks)
    if not team_members:
        return {
            "assignee": None,
            "summary": baseline["summary"],
            "score_rows": [],
            "reminders": [],
            "decisions": [],
            "blockers": [],
            "evidence": [],
        }

    insights = extract_memory_insights(recalled_memories, team_members, required_skills)
    member_stats = insights["member_stats"]
    score_rows: list[dict[str, Any]] = []

    for member in team_members:
        name = member["name"]
        skills = normalize_skills(member.get("skills", []))
        overlap = skill_overlap(skills, required_skills)
        load = current_load(name, tasks)
        stats = member_stats[name]
        score = (
            overlap * 4
            + stats["completed"] * 3
            + stats["skill_proof"] * 2
            + stats["meeting_mentions"]
            - stats["delayed"] * 3
            - stats["blocked"] * 2
            - load
        )
        score_rows.append(
            {
                "member": name,
                "role": member.get("role", ""),
                "score": score,
                "skill_matches": overlap,
                "completed_memories": stats["completed"],
                "delayed_memories": stats["delayed"],
                "blocked_memories": stats["blocked"],
                "meeting_mentions": stats["meeting_mentions"],
                "evidence": stats["evidence"][:3],
            }
        )

    score_rows.sort(
        key=lambda row: (
            row["score"],
            row["completed_memories"],
            row["skill_matches"],
            -row["delayed_memories"],
        ),
        reverse=True,
    )
    top_choice = score_rows[0]

    reasons: list[str] = []
    if top_choice["skill_matches"]:
        reasons.append(f"{top_choice['member']} matches {top_choice['skill_matches']} required skills.")
    if top_choice["completed_memories"]:
        reasons.append(
            f"Hindsight recalled {top_choice['completed_memories']} completed task memory entries for {top_choice['member']}."
        )
    if insights["decisions"]:
        reasons.append("Past meeting decisions were included in the recommendation.")
    if not reasons:
        reasons.append("Hindsight did not find strong historical signals, so the answer stayed close to the baseline.")

    reminders: list[str] = []
    if insights["blockers"]:
        reminders.append(f"Flag recurring blocker early: {insights['blockers'][0]}")
    if top_choice["delayed_memories"]:
        reminders.append(
            f"Set an earlier check-in for {top_choice['member']} because similar work previously slipped."
        )
    else:
        reminders.append(
            f"Send {top_choice['member']} a mid-sprint reminder 24 hours before the deadline to protect demo readiness."
        )

    return {
        "assignee": top_choice["member"],
        "summary": " ".join(reasons),
        "score_rows": score_rows,
        "reminders": reminders,
        "decisions": insights["decisions"],
        "blockers": insights["blockers"],
        "evidence": top_choice["evidence"],
    }


def sample_team_members() -> list[dict[str, Any]]:
    return [
        {"name": "Aisha Khan", "skills": ["Streamlit", "Python", "UI"], "role": "Frontend Lead"},
        {"name": "Ravi Patel", "skills": ["Python", "APIs", "Data"], "role": "Backend Engineer"},
        {"name": "Neha Joshi", "skills": ["Testing", "Planning", "Docs"], "role": "Project Lead"},
    ]


def sample_tasks() -> list[dict[str, Any]]:
    return [
        {
            "title": "Sprint summary dashboard",
            "assigned_member": "Aisha Khan",
            "deadline": "2026-03-19",
            "status": "Completed",
            "required_skills": ["Streamlit", "Python"],
            "notes": "Built ahead of the demo and handled UI polish cleanly.",
            "document_id": "sample-task-dashboard-completed",
        },
        {
            "title": "Reminder API integration",
            "assigned_member": "Ravi Patel",
            "deadline": "2026-03-18",
            "status": "Delayed",
            "required_skills": ["Python", "APIs"],
            "notes": "Blocked by notification schema changes from the backend service.",
            "document_id": "sample-task-reminder-delayed",
        },
        {
            "title": "QA risk checklist",
            "assigned_member": "Neha Joshi",
            "deadline": "2026-03-17",
            "status": "Completed",
            "required_skills": ["Testing", "Docs"],
            "notes": "Captured release blockers and closed follow-ups quickly.",
            "document_id": "sample-task-qa-completed",
        },
        {
            "title": "Notification retry worker",
            "assigned_member": "Ravi Patel",
            "deadline": "2026-03-20",
            "status": "Blocked",
            "required_skills": ["Python", "APIs"],
            "notes": "Still waiting on final event payload examples.",
            "document_id": "sample-task-worker-blocked",
        },
    ]


def sample_meeting_notes() -> list[dict[str, Any]]:
    return [
        {
            "summary": (
                "Decision: keep Aisha focused on demo-facing UI. "
                "Blocker: notification API schema is unstable. "
                "Risk: backend work may slip if the contract changes again."
            ),
            "document_id": "sample-meeting-demo-focus",
        },
        {
            "summary": (
                "Decision: prioritize reliable reminders over analytics depth. "
                "Blocker: Ravi still needs API confirmation. "
                "Risk: final reminder flow depends on backend readiness."
            ),
            "document_id": "sample-meeting-reminders-first",
        },
    ]
