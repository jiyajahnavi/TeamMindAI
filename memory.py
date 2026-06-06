from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv

from utils import (
    MEMORY_PREFIXES,
    format_deadline,
    memory_based_assignment,
    memory_line,
    normalize_skills,
    slugify,
)


DEFAULT_BANK_ID = "teammind-ai-project"


# Load environment variables from a local .env file if present.
load_dotenv()


@dataclass
class MemoryStatus:
    enabled: bool
    mode: str
    bank_id: str
    message: str


class NullMemoryService:
    def __init__(self, status: MemoryStatus):
        self.status = status

    def retain_event(
        self,
        kind: str,
        content: str,
        context: str = "",
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "message": self.status.message,
            "kind": kind,
            "document_id": document_id,
            "metadata": metadata or {},
        }

    def recall(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        return []

    def get_bank_snapshot(self) -> dict[str, Any]:
        return {
            "available": False,
            "bank_id": self.status.bank_id,
            "total_nodes": 0,
            "total_documents": 0,
            "pending_operations": 0,
            "failed_operations": 0,
            "total_observations": 0,
            "recent_memories": [],
            "recent_operations": [],
        }


class HindsightMemoryService:
    def __init__(self, base_url: str, status: MemoryStatus):
        self.base_url = base_url.rstrip("/")
        self.status = status
        self._ensure_bank()

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_text = response.read().decode("utf-8")
                return json.loads(response_text) if response_text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Hindsight API error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Hindsight API connection failed: {exc.reason}") from exc

    def _ensure_bank(self) -> None:
        self._request_json(
            "PUT",
            f"/v1/default/banks/{self.status.bank_id}",
            {
                "name": "TeamMind AI",
                "mission": (
                    "Remember how the team delivers work, which blockers repeat, "
                    "what meeting decisions were made, and which assignments are most likely to succeed."
                ),
                "disposition_skepticism": 3,
                "disposition_literalism": 4,
                "disposition_empathy": 4,
            },
        )

    def retain_event(
        self,
        kind: str,
        content: str,
        context: str = "",
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "bank_id": self.status.bank_id,
            "content": content,
        }
        if context:
            payload["context"] = context
        if document_id:
            payload["document_id"] = document_id
        if metadata:
            payload["metadata"] = _stringify_metadata(metadata)

        response = self._request_json(
            "POST",
            f"/v1/default/banks/{self.status.bank_id}/memories",
            {"items": [payload], "async": True},
        )
        return {
            "ok": True,
            "response": response,
            "kind": kind,
            "document_id": document_id,
        }

    def recall(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        response = self._request_json(
            "POST",
            f"/v1/default/banks/{self.status.bank_id}/memories/recall",
            {
                "query": query,
                "budget": "mid",
                "max_tokens": 4096,
                "types": ["world", "experience", "observation"],
            },
        )
        items = response.get("results", []) or []
        normalized: list[dict[str, Any]] = []

        for item in list(items)[:limit]:
            normalized.append(
                {
                    "text": _read_mapping(item, "text") or "",
                    "context": _read_mapping(item, "context") or "",
                    "score": _read_mapping(item, "score"),
                    "document_id": _read_mapping(item, "document_id"),
                }
            )
        return normalized

    def list_recent_memories(self, limit: int = 12, q: str | None = None) -> list[dict[str, Any]]:
        query_suffix = f"&q={urllib.parse.quote(q)}" if q else ""
        response = self._request_json(
            "GET",
            f"/v1/default/banks/{self.status.bank_id}/memories/list?limit={limit}{query_suffix}",
        )
        return response.get("items", []) or []

    def get_bank_snapshot(self) -> dict[str, Any]:
        stats = self._request_json("GET", f"/v1/default/banks/{self.status.bank_id}/stats")
        operations = self._request_json(
            "GET",
            f"/v1/default/banks/{self.status.bank_id}/operations?limit=6",
        )
        recent_memories = self.list_recent_memories(limit=6)
        return {
            "available": True,
            "bank_id": self.status.bank_id,
            "total_nodes": stats.get("total_nodes", 0),
            "total_documents": stats.get("total_documents", 0),
            "pending_operations": stats.get("pending_operations", 0),
            "failed_operations": stats.get("failed_operations", 0),
            "total_observations": stats.get("total_observations", 0),
            "recent_memories": recent_memories,
            "recent_operations": operations.get("operations", []) or [],
        }


def _read_mapping(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return None


def _stringify_metadata(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None

    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            normalized[key] = ", ".join(str(item) for item in value if str(item).strip())
        else:
            normalized[key] = str(value)
    return normalized


def _detect_memory_service() -> NullMemoryService | HindsightMemoryService:
    bank_id = os.getenv("TEAMMIND_BANK_ID", DEFAULT_BANK_ID)
    api_url = os.getenv("HINDSIGHT_API_URL")
    provider = os.getenv("TEAMMIND_LLM_PROVIDER")
    model = os.getenv("TEAMMIND_LLM_MODEL")
    explicit_api_key = os.getenv("TEAMMIND_LLM_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")

    try:
        if api_url:
            return HindsightMemoryService(
                base_url=api_url,
                status=MemoryStatus(
                    enabled=True,
                    mode="external-api",
                    bank_id=bank_id,
                    message=f"Connected to Hindsight API at {api_url}",
                ),
            )

        llm_api_key = explicit_api_key or openai_api_key or groq_api_key
        chosen_provider = provider or ("groq" if groq_api_key and not openai_api_key else "openai")
        chosen_model = model or (
            "llama-3.3-70b-versatile" if chosen_provider == "groq" else "gpt-4o-mini"
        )

        if llm_api_key:
            return NullMemoryService(
                MemoryStatus(
                    enabled=False,
                    mode="external-api-required",
                    bank_id=bank_id,
                    message=(
                        "Embedded Hindsight is not available in this Windows setup. "
                        "Run a Hindsight API server and set HINDSIGHT_API_URL, or use a non-Windows environment "
                        f"for embedded mode. Current provider config: {chosen_provider}/{chosen_model}."
                    ),
                )
            )

        return NullMemoryService(
            MemoryStatus(
                enabled=False,
                mode="disabled",
                bank_id=bank_id,
                message=(
                    "Hindsight is not configured yet. Set HINDSIGHT_API_URL or provide "
                    "TEAMMIND_LLM_PROVIDER plus an OPENAI_API_KEY/GROQ_API_KEY."
                ),
            )
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive setup guard
        package_hint = "hindsight-client"
        version_hint = ""
        if sys.version_info < (3, 11):
            version_hint = f" Hindsight integration needs Python 3.11+ for supported local setups. Current interpreter: {sys.version.split()[0]}."

        return NullMemoryService(
            MemoryStatus(
                enabled=False,
                mode="error",
                bank_id=bank_id,
                message=(
                    f"Hindsight setup failed: missing Python package '{exc.name}'. "
                    f"Install {package_hint} in the same environment that runs Streamlit."
                    f"{version_hint}"
                ),
            )
        )
    except Exception as exc:  # pragma: no cover - defensive setup guard
        return NullMemoryService(
            MemoryStatus(
                enabled=False,
                mode="error",
                bank_id=bank_id,
                message=f"Hindsight setup failed: {exc}",
            )
        )


@lru_cache(maxsize=1)
def get_memory_service() -> NullMemoryService | HindsightMemoryService:
    return _detect_memory_service()


def get_memory_status() -> MemoryStatus:
    return get_memory_service().status


def get_memory_bank_snapshot() -> dict[str, Any]:
    try:
        return get_memory_service().get_bank_snapshot()
    except Exception as exc:
        status = get_memory_status()
        return {
            "available": False,
            "bank_id": status.bank_id,
            "total_nodes": 0,
            "total_documents": 0,
            "pending_operations": 0,
            "failed_operations": 1,
            "total_observations": 0,
            "recent_memories": [],
            "recent_operations": [],
            "error": str(exc),
        }


def retain_team_member(
    name: str,
    skills: list[str] | str,
    role: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    skills_list = normalize_skills(skills)
    content = memory_line(
        MEMORY_PREFIXES["team"],
        name=name,
        role=role,
        skills=skills_list,
        recorded_at=datetime.utcnow().isoformat(),
    )
    return get_memory_service().retain_event(
        kind=MEMORY_PREFIXES["team"],
        content=content,
        context="Team roster and capability update for TeamMind AI.",
        document_id=document_id or f"member-{slugify(name)}",
        metadata={"name": name, "role": role, "skills": skills_list},
    )


def retain_task_update(
    task_title: str,
    assigned_member: str,
    deadline: date | str,
    status: str,
    notes: str = "",
    required_skills: list[str] | str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    skills_list = normalize_skills(required_skills or [])
    content = memory_line(
        MEMORY_PREFIXES["task"],
        title=task_title,
        assigned_to=assigned_member,
        deadline=format_deadline(deadline),
        status=status,
        required_skills=skills_list,
        notes=notes,
        recorded_at=datetime.utcnow().isoformat(),
    )
    default_document_id = (
        document_id
        or f"task-{slugify(task_title)}-{slugify(assigned_member)}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    )
    return get_memory_service().retain_event(
        kind=MEMORY_PREFIXES["task"],
        content=content,
        context="Task assignment or status update for the team project manager.",
        document_id=default_document_id,
        metadata={
            "title": task_title,
            "assigned_member": assigned_member,
            "deadline": format_deadline(deadline),
            "status": status,
            "required_skills": skills_list,
        },
    )


def retain_meeting_notes(notes: str, document_id: str | None = None) -> dict[str, Any]:
    content = memory_line(
        MEMORY_PREFIXES["meeting"],
        summary=notes,
        decisions=extract_prefixed_line(notes, "decision"),
        blockers=extract_prefixed_line(notes, "blocker"),
        risks=extract_prefixed_line(notes, "risk"),
        recorded_at=datetime.utcnow().isoformat(),
    )
    return get_memory_service().retain_event(
        kind=MEMORY_PREFIXES["meeting"],
        content=content,
        context="Meeting decisions, blockers, and project risks.",
        document_id=document_id or f"meeting-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        metadata={"notes": notes},
    )


def extract_prefixed_line(notes: str, prefix: str) -> str:
    import re

    pattern = re.compile(rf"{prefix}\s*:\s*([^\n\.]+)", re.IGNORECASE)
    match = pattern.search(str(notes))
    return match.group(1).strip() if match else ""


def _dedupe_memories(memories: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for memory in memories:
        key = memory.get("document_id") or memory.get("text", "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(memory)
        if len(deduped) >= limit:
            break
    return deduped


def recall_relevant_memories(query: str | list[str], limit: int = 6) -> list[dict[str, Any]]:
    service = get_memory_service()
    queries = [query] if isinstance(query, str) else query
    collected: list[dict[str, Any]] = []

    for item in queries:
        cleaned = str(item).strip()
        if not cleaned:
            continue
        try:
            collected.extend(service.recall(query=cleaned, limit=limit))
        except Exception:
            continue

    if not collected and hasattr(service, "list_recent_memories"):
        try:
            recent_items = service.list_recent_memories(limit=limit * 2)
            for item in recent_items:
                collected.append(
                    {
                        "text": _read_mapping(item, "text") or "",
                        "context": _read_mapping(item, "context") or "",
                        "score": _read_mapping(item, "score"),
                        "document_id": _read_mapping(item, "chunk_id") or _read_mapping(item, "id"),
                    }
                )
        except Exception:
            pass

    return _dedupe_memories(collected, limit)


def generate_task_recommendation(
    task_title: str,
    required_skills: list[str] | str,
    team_members: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    deadline: date | str | None = None,
    blockers: str = "",
) -> dict[str, Any]:
    skills_list = normalize_skills(required_skills)
    query = " ".join(
        part
        for part in [
            f"Task assignment for {task_title}.",
            f"Required skills: {', '.join(skills_list) or 'none specified'}.",
            f"Deadline: {format_deadline(deadline)}." if deadline else "",
            f"Blockers: {blockers}." if blockers else "",
            "Find past completed tasks, delayed tasks, meeting decisions, and recurring blockers.",
        ]
        if part
    )
    blocker_summary = str(blockers).strip().split(".")[0].strip()
    member_names = [member["name"] for member in team_members]
    recall_queries = [
        query,
        f"{task_title}. Skills: {', '.join(skills_list)}. Project decisions and blockers.",
        f"Who completed similar work well for {', '.join(skills_list) or task_title}?",
        f"Who delayed or blocked similar work for {', '.join(skills_list) or task_title}?",
        "Project meeting decisions, delayed tasks, completed tasks, blockers, and risks.",
    ]
    if blocker_summary:
        recall_queries.append(f"Recurring blocker: {blocker_summary}")
    if member_names:
        recall_queries.append(
            f"Team members: {', '.join(member_names)}. Recall delivery patterns, blockers, and demo assignments."
        )

    recalled_memories = recall_relevant_memories(recall_queries)
    recommendation = memory_based_assignment(
        task_title=task_title,
        required_skills=skills_list,
        team_members=team_members,
        tasks=tasks,
        recalled_memories=recalled_memories,
    )
    recommendation["query"] = query
    recommendation["query_variants"] = recall_queries
    recommendation["recalled_memories"] = recalled_memories
    recommendation["memory_status"] = get_memory_status()
    return recommendation
