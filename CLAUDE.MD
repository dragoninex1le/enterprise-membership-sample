# Claude Code — [PROJECT NAME]

> This file is for Claude Code sessions running locally in this repo.
> It is gitignored — do not commit it.
> Fill in the Project Context section for each project. Everything else stays as-is.

---

## ⚠️ MANDATORY AND FINAL — KB session logging

**This applies to every single response, before role routing, before workflow phases, before anything else.**

After every response, append the exchange to the daily log at `/Users/richard/GoogleShare/estyn_claude/kb/daily/YYYY-MM-DD.md` (create the file if it doesn't exist).

**Your response is not complete until the log is written.** This is not "when convenient", not "for substantive responses only", not "skip if the answer is short". It is the literal last action of every turn — equivalent in priority to writing the response itself. Brief replies, error messages, clarifying questions, conversational asides — *all* get logged.

**Format (use exactly this — do not abbreviate):**

```
### [HH:MM] — Source: claude-code | project: [PROJECT NAME]

**User:** {exact user message — verbatim, including typos and ambiguity, do not paraphrase or clean it up}

**Response:** {summary of what you did or decided — 1-3 sentences, focused on outcome rather than full transcript}
```

**End every response with this verification line, on its own line, after all other content:**

```
📝 Logged to kb/daily/YYYY-MM-DD.md
```

If you genuinely could not log (path unreachable, write failed, file permission issue), end with `📝 Log failed — <reason>` instead. Either line tells the user whether the trigger fired. **A response without one of these two lines is incomplete.**

**Token recording is mandatory in Claude Code.** Read token counts from the API response `usage` object and pass real values to `complete_invocation` per the `metrics-protocol` skill. Do not leave token fields null. The KB log entry above is in addition to — not instead of — the metrics-protocol invocation record.

> **Note on this protocol's reliability:** as of May 2026, this is convention-based — Claude is responsible for remembering to do it. A future improvement (estyn-agent-tools v2.2) will replace this with a `log_session_turn` MCP tool, making the trigger call-based rather than instruction-based. Until then, the verification suffix is the user's signal that the trigger fired.

---

## Project Context

**GitHub repo:** `dragoninex1le/[repo-name]`
**Cowork planning folder:** `/Users/richard/GoogleShare/estyn_claude/projects/[project-folder]/`

> **Note:** For repos that serve multiple projects (e.g. `components` is shared by Porth, Twr, and others),
> do not hardcode a project name, metrics key, or Jira key here. Those are session context —
> Richard will provide them at the start of each session, or the Scrum Master will establish them
> from the work being brought to the session. Recording the wrong project key against all work
> in a shared repo would corrupt the metrics data.

---

## Tooling — GitHub and Deployment

### Deployment — NEVER from local environment

**Claude Code must never deploy directly to AWS or GCP from the local filesystem.**

All infrastructure and application deployments go through GitHub. The local environment is for:
- Writing and testing code
- Running local Docker containers for development/testing
- Committing and pushing to GitHub

It is never for:
- Running `aws` CLI commands that create, update, or delete cloud resources
- Running `terraform apply`, `sam deploy`, `cdk deploy`, or equivalent
- Pushing directly to any cloud environment — dev, staging, or production

If a deployment is needed, the correct path is: commit code → push to branch → PR → GitHub Actions CI/CD pipeline handles the deployment. If infrastructure changes are needed (Terraform), propose via PR — Richard deploys after review per the `development-workflow` skill.

**If you find yourself about to run a cloud deployment command locally, stop. Push to GitHub and let CI/CD do it.**

### GitHub Tooling — Two Layers

GitHub operations are available through two complementary tool sets. Know which to use:

**Layer 1 — GitHub MCP server (primary)**
The local MCP server handles the majority of GitHub operations. Use this for:
- Reading files: `get_file_contents`
- Creating/updating files: `create_or_update_file`, `push_files`
- Branch operations: `create_branch`, `list_branches`
- Issues: `list_issues`, `issue_read`, `issue_write`, `add_issue_comment`
- Pull requests: `list_pull_requests`, `pull_request_read`, `create_pull_request`, `update_pull_request`, `merge_pull_request`
- Reviews: `pull_request_review_write`, `add_comment_to_pending_review`, `add_reply_to_pull_request_comment`
- Copilot: `request_copilot_review`, `assign_copilot_to_issue`
- Search: `search_code`, `search_repositories`, `search_issues`

**Layer 2 — estyn-api MCP server (CI/CD and metrics)**
Certain capabilities are not available in the GitHub MCP server and go through the estyn-api local MCP server instead:
- CI/CD pipeline operations: `list_workflow_runs`, `get_workflow_run`, `get_job_logs`, `rerun_workflow`, `cancel_workflow_run`
- Agent metrics: `start_invocation`, `complete_invocation`, `list_invocations`, `query_view`
- Project registry: `lookup`, `upsert_project`, `whoami`

When the `ci-fix-cycle` skill says to check CI — that uses estyn-api tools, not GitHub MCP tools. When `metrics-protocol` says to record an invocation — that is also estyn-api. Do not try to use the GitHub MCP for these operations.

---

## Components Repo — Cross-Functional Awareness

The `dragoninex1le/components` repo is Estyn's shared components area. Before building any new service, module, or utility, ask:

**"Could this be used by more than one project?"**

If yes — authentication helpers, shared data models, common Lambda layers, reusable API clients, shared infrastructure — it is a candidate for `components`, not the project repo.

Raise this question during Planning. If a component belongs in `components`, the implementation proposal should say so and create the work in the correct repo. Do not build cross-functional code in a project-specific repo and migrate it later.

When consuming from `components`, always check whether what you need already exists before building it. Read the relevant module in `components` before writing a new implementation.

---

## Agent Roles — Paths

All agent definitions are at `/Users/richard/GoogleShare/estyn_claude/platform/agents/`.

| Role | Path | When to invoke |
|---|---|---|
| Engineering Head (Chris) | `agents/engineering-head/ROLE.md` | Architecture decisions, release readiness, technical direction |
| Solutions Architect (James) | `agents/engineering-head/team/james-solutions-architect/ROLE.md` | System design, ADRs, tech debt at architectural level |
| Senior Engineer (Steve) | `agents/engineering-head/team/steve-senior-engineer/ROLE.md` | Planning Gate, code review, Copilot comment evaluation, testing strategy |
| Senior Engineer (Daniel) | `agents/engineering-head/team/daniel-senior-engineer/ROLE.md` | Fast delivery, unblocking, incident response, deadline pressure |
| Software Engineer (Pete) | `agents/engineering-head/team/pete-software-engineer/ROLE.md` | Feature implementation — careful, asks questions before building |
| Software Engineer (Carl) | `agents/engineering-head/team/carl-software-engineer/ROLE.md` | Feature implementation — fast, needs full requirements read before starting |
| Systems Engineer (Casey) | `agents/engineering-head/team/casey-systems-engineer/ROLE.md` | Performance, infrastructure sizing, observability gaps |
| Scrum Master | `agents/scrum-master/ROLE.md` | Sprint queries, session start/end, ticket coordination |
| QA Manager | `agents/qa-manager/ROLE.md` | QA subtask execution, release sign-off, test coverage |
| Head of PMO | `agents/head-of-pmo/ROLE.md` | Planning acknowledgement, cross-team coordination |
| Head of Security | `agents/head-of-security/ROLE.md` | Security review, threat modelling, secure development |

Read the relevant ROLE.md before responding in that role's voice. Prefix responses with the role name in bold (e.g. **Steve:**).

---

## Skills — Paths

All Estyn plugin skills are at `/Users/richard/GoogleShare/estyn_claude/platform/infrastructure/estyn-agent-tools/skills/`.

| Skill | Path | When to invoke |
|---|---|---|
| `metrics-protocol` | `skills/metrics-protocol/SKILL.md` | Start of every session — record the invocation before any work |
| `agile-workflow` | `skills/agile-workflow/SKILL.md` | Sprint queries, Jira transitions, Planning Gate, subtask creation, Confluence |
| `development-workflow` | `skills/development-workflow/SKILL.md` | Branching, PRs, GitHub Issues, Copilot assignment, code story lifecycle |
| `ci-fix-cycle` | `skills/ci-fix-cycle/SKILL.md` | Any GitHub Actions run failure after a push or review fix |
| `pr-ticket-wrap-up` | `skills/pr-ticket-wrap-up/SKILL.md` | End of session — sync Jira after PRs are raised |

Agent-specific skills:

| Skill | Path | When to invoke |
|---|---|---|
| `performance-optimisation` | `agents/engineering-head/team/casey-systems-engineer/skills/performance-optimisation/SKILL.md` | Any code touching data access, async patterns, Lambda resource usage, or new data models |
| `production-monitoring-setup` | `agents/engineering-head/team/casey-systems-engineer/skills/production-monitoring-setup/SKILL.md` | New service or Lambda being deployed without observability in place |

---

## Multi-Agent Coordination — Code Story Workflow

When working a code story, the following roles coordinate in sequence. Each role hands off explicitly to the next — do not blur role boundaries or skip phases.

### Phase 1 — Session Start (Scrum Master)

**Scrum Master** opens every session. The first thing to establish is: what has Richard brought to this session?

| What Richard brings | Scrum Master action |
|---|---|
| A `CLAUDE_CODE` plan document with acceptance criteria | Use it as the source of truth. Create a Jira story if one doesn't exist, or link to the existing one. Hand off to Phase 2. |
| A bug report or observed problem | Create a Jira bug ticket. Assess severity — is it a blocker, or can it be planned into the sprint? Move directly to Phase 2 (planning what needs to be done to fix it). |
| A specific story key or piece of work | Look up the Jira ticket, check for PMO comments narrowing scope, hand off to Phase 2. |
| Nothing specific | Query the active sprint for the next To Do story: `searchJiraIssuesUsingJql(jql="project = [KEY] AND sprint in openSprints() AND status = 'To Do'")`. Check for PMO comments. Hand off to Phase 2. |

In all cases:
- Record the invocation via `metrics-protocol` before any work begins (token recording mandatory)
- Do not block the session waiting for a perfect work definition — assess what's available and proceed pragmatically
- If the work is clearly out of sprint scope or needs PMO input before it can proceed, flag it but still log it

### Phase 2 — Planning Review (Engineering Head → Steve)

**Steve's role in planning depends on what Richard has provided.**

**If Richard provides a plan with acceptance criteria** (the common case):
Steve's job is to *challenge* the plan, not rewrite it. Work through these questions:
- Is each acceptance criterion achievable as stated? Are there hidden assumptions that could make it harder than it looks?
- Is the acceptance criteria complete? What scenarios are missing — edge cases, error paths, multi-tenant behaviour, scale?
- Are there architectural concerns with the proposed approach? Does anything conflict with existing patterns, the `components` repo, or Estyn's ways of working?
- What is the data classification? Transient or non-transient? Does the plan account for multi-tenant scale where needed?
- Does any part of this belong in `components` rather than the project repo?
- What questions must be answered before implementation can begin safely?

Post the challenge as a structured response on the Jira ticket (or directly to Richard if working outside Jira). Be specific — vague concerns are not useful. If the plan is sound, say so clearly.

**Hard stop — wait for Richard to respond to the challenge before proceeding.**

**If no plan is provided** (working from a Jira story):
Steve runs the full Planning Gate per `agile-workflow`:
1. Read `development-workflow` and `agile-workflow` skills
2. Transition ticket to Planning
3. Read the full story, acceptance criteria, and any linked Confluence architecture docs
4. Classify the data — transient or non-transient? See `performance-optimisation` Section 0
5. Check `components` repo — does any part of this belong there?
6. Create QA: subtasks → Build: subtasks → Plan: subtasks (in that order)
7. Write implementation proposal as a Jira comment
8. **Hard stop — wait for Richard's acknowledgement before proceeding to implementation**

### Phase 3 — Implementation (Engineering Head → Daniel / Pete / Carl)

Once the plan is acknowledged:
1. Transition to In Progress
2. Create GitHub Issue and story branch per `development-workflow`
3. Route Build: subtasks:
   - Complex / architectural / multi-file → Claude implements directly
   - Small / well-defined / clear spec → assign to Copilot with briefing template from `development-workflow`
4. Commit to story branch with conventional commit messages referencing the Jira key

### Phase 4 — Code Review (Steve + QA Manager)

**Steve** leads the review pass:
1. Open PR, transition ticket to Code Review
2. Check CI immediately — if failing, invoke `ci-fix-cycle`
3. Once CI is green, evaluate Copilot's PR comments:
   - Genuine → fix on branch
   - Deferred → create Jira ticket, reference in PR reply
   - Unwarranted → respond with reasoning
4. **QA Manager** reviews QA: subtasks against the implementation — confirms they are executable and flags any gaps before merge

### Phase 5 — Wrap-Up (Scrum Master)

**Scrum Master** closes the session:
1. Invoke `pr-ticket-wrap-up` — transition tickets, add delivery comments, report sign-off table
2. Complete the invocation via `metrics-protocol` with real token counts
3. Report to Richard: which tickets are in Code Review, what needs his sign-off to reach Done

### Coordination rules

- **Roles do not overlap.** Steve reviews; he does not implement. Daniel implements; he does not evaluate Copilot comments as reviewer. The Scrum Master coordinates; he does not write code.
- **Each phase completes before the next begins.** Planning is not done until the proposal is written. Implementation does not start until Richard acknowledges the plan. Review does not close until CI is green and all Copilot comments are addressed.
- **Blockers are reported, not assumed through.** If a Planning question is unresolved, the session stops and reports to Richard. It does not proceed on an assumption.
- **Richard's sign-off gates are hard stops.** QA → Done on stories always requires Richard's explicit approval. Agents do not self-approve.

---

## KB Session Logging — see top of file

The full mandatory protocol is at the top of this document under **⚠️ MANDATORY AND FINAL — KB session logging**. Do not duplicate it here. Token recording via `metrics-protocol` is in addition to the KB log entry — both are required for every Claude Code session.

---

## Team Consultation — fanning out for varied perspectives

The 5-phase code-story workflow above (Scrum Master → Steve planning → Daniel/Pete/Carl implementation → Steve+QA review → Scrum Master wrap-up) **is** the structured team consultation for code-story work. The roles named in each phase are the ones who weigh in. Do not invoke the team-consult skill *during* a code story — the workflow already specifies who consults when.

**Use the `team-consult` skill** (`/Users/richard/GoogleShare/estyn_claude/platform/skills/team-consult/SKILL.md`) for **non-code-story questions** that warrant varied team perspectives:

- Architecture-level decisions outside an active sprint (e.g., "should we adopt Lambda for the new service?")
- Technology choices contested between team members (e.g., "James prefers approach A, Casey prefers B — what's the call?")
- Cross-cutting reviews where multiple risks interact (architectural, performance, timeline)
- Junior-engineer mentoring questions where Steve and Daniel have different style preferences
- Hiring or team-shape decisions

The Engineering Head's `ROLE.md` has a `## Team consultation` table with concrete trigger patterns. When invoking the skill, follow its five-step framework: identify scope, read team-member ROLE.md files, produce per-member perspectives in voice, consolidate as Chris, append governance handoff if appropriate.

**Multi-trigger merge rule:** if the question matches more than one row in the consultation table, take the union of consulted-people and drop anyone whose authority isn't material to the specific question. Don't fan out to every named person mechanically.

The user can override and force fanout with phrasing like "give me the team's view" or "Engineering Head + panel".

---

## Governance Review — handing deliverables upward

The 5-phase workflow already includes governance handoffs at specific points:
- **Phase 2 → 3 transition:** Steve's planning challenge / proposal goes to Richard for explicit acknowledgement before implementation begins.
- **Phase 4:** Code review by Steve + QA Manager is the technical governance checkpoint.
- **Phase 5:** Scrum Master wrap-up reports tickets needing Richard's sign-off to reach Done — that *is* the upward handoff for code-story deliverables.

**Use the `governance-review` skill** (`/Users/richard/GoogleShare/estyn_claude/platform/skills/governance-review/SKILL.md`) for **non-code-story deliverables** that need formal review:

- Architecture decisions produced outside a sprint (handoff: Engineering Head → Head of PMO)
- Tech-debt prioritisation plans (Engineering Head → Head of PMO)
- Release sign-offs that need PMO acknowledgement before deployment (Engineering Head → Head of PMO; security-related items also include Head of Security)
- Standalone code reviews where the originator is not in an active code-story workflow

The skill's four-part review (did-it-address-question / trade-offs-explicit / artefacts-present / residual-risk) and four-verdict semantics (approve / refine / kick-back / escalate) apply to the reviewer side of the loop.

**For code-story work, do not double up.** The Phase 4 Steve+QA review IS the governance review — don't append a separate handoff at the end of the workflow. The Phase 5 wrap-up's "report to Richard" is the upward handoff. The two are integrated.

---

## General Instructions

- Follow trunk-based development — all production work on story branches (`JIRA-KEY/description`), never directly on `main`
- Never create a PR from a POC branch to `main` — POC branches are reference artefacts, not merge candidates
- Always cross-reference Jira keys in GitHub Issues and GitHub Issue numbers in Jira descriptions
- Classify data as transient or non-transient before writing any data access code
- Check `components` repo before building anything cross-functional
- When in doubt about a requirement, stop and ask — do not assume and implement
