# TeamMind AI

TeamMind AI is a hackathon-ready web app that acts like an AI group project manager for small teams. It captures team roles, skills, task updates, meeting decisions, blockers, and delivery history, then uses project memory to make better task assignment and reminder suggestions over time.

The app is intentionally simple:

- `Workspace` lets you add team members, task updates, and meeting notes.
- `AI Suggestions` compares a generic assignment recommendation against a memory-aware recommendation.
- Sample demo data is included so the memory effect is visible right away.

## Why this project stands out

This is not just a normal task board. TeamMind AI uses Hindsight as the memory layer so the recommendation engine can recall:

- team member skills and roles
- completed tasks
- delayed or blocked tasks
- meeting decisions
- recurring risks and blockers

That means the app can move from:

- without memory: "Assign based on current skills and workload."
- with memory: "Assign to Aisha because she completed similar Streamlit work successfully, Ravi had repeated API delays, and meeting notes said to keep demo-facing UI with Aisha."

## How Hindsight is used

The app uses one Hindsight memory bank for the whole project team.

### Retained memory events

The following helpers store meaningful events with `retain()`:

- `retain_team_member(...)`
- `retain_task_update(...)`
- `retain_meeting_notes(...)`

Each retained item is written as a structured memory line, for example:

- `TEAM_MEMBER | name: Aisha Khan | role: Frontend Lead | skills: Streamlit, Python, UI`
- `TASK_UPDATE | title: Reminder API integration | assigned to: Ravi Patel | status: Delayed`
- `MEETING_NOTE | summary: Decision: keep Aisha focused on demo-facing UI. ...`

### Recalled memory context

When you generate a suggestion, the app calls:

- `recall_relevant_memories(query)`

That query asks Hindsight for relevant completed tasks, delayed tasks, meeting decisions, and blockers related to the task being assigned.

### Recommendation flow

`generate_task_recommendation(...)` uses recalled memory context to:

- reward members with relevant completed-task history
- penalize repeated delayed or blocked-task history
- factor in meeting decisions and known blockers
- suggest reminder actions based on what slipped before

The UI shows the query and the recalled memory snippets so the Hindsight usage is visible.

## File structure

- `app.py` - Streamlit UI
- `memory.py` - Hindsight setup, retain/recall helpers, recommendation orchestration
- `utils.py` - parsing, scoring, and sample data helpers
- `requirements.txt` - Python dependencies
- `README.md` - project overview and setup instructions

## Local setup

Hindsight's official docs note that local/self-hosted usage requires Python 3.11+, so use Python 3.11 or newer for this project.
On Windows, this starter is set up to use the Hindsight API client path. That means the Streamlit app connects to a running Hindsight API server through `HINDSIGHT_API_URL`.

### 1. Create and activate a virtual environment

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure Hindsight with `.env`

The app now loads environment variables automatically from a local `.env` file.

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and point the app at a running Hindsight API:

```dotenv
HINDSIGHT_API_URL=http://localhost:8888
TEAMMIND_BANK_ID=teammind-ai-project
```

If you already run Hindsight elsewhere, use that URL instead.

### 4. Start Hindsight API

The app needs a live Hindsight API server. The official docs provide multiple deployment options including Docker and pip-based service installs.

Quickest Docker path on Windows PowerShell:

```powershell
$env:GROQ_API_KEY="your-groq-key"
docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 `
  -e HINDSIGHT_API_LLM_PROVIDER=groq `
  -e HINDSIGHT_API_LLM_API_KEY=$env:GROQ_API_KEY `
  -e HINDSIGHT_API_LLM_MODEL=llama-3.3-70b-versatile `
  -v "${HOME}\\.hindsight-docker:/home/hindsight/.pg0" `
  ghcr.io/vectorize-io/hindsight:latest
```

After that:

- API server: `http://localhost:8888`
- Control plane: `http://localhost:9999`

### 5. Run the app

```powershell
streamlit run app.py
```

If you change `.env`, restart Streamlit so the new settings are reloaded.

## Demo flow

1. Open the app.
2. Click `Load Sample Demo Data`.
3. Go to `AI Suggestions`.
4. Generate a recommendation.
5. Compare `Without Memory` vs `With Hindsight Memory`.
6. Review the recalled memory snippets that influenced the answer.

## LLM-ready architecture

The current version uses Hindsight recall plus deterministic scoring so it stays hackathon-friendly and easy to understand. The memory adapter is already separated from the UI, which makes future upgrades straightforward:

- swap in OpenAI or Groq generation for richer reasoning
- add `reflect()` later if you want full memory-grounded answer generation
- keep Hindsight as the long-term memory layer while changing the model provider independently
