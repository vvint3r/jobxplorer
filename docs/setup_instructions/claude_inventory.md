# Claude Code — Feature & Integration Inventory
### Applied Reference for JobXplore / Ubuntu Server Setup

---

## HOW TO READ THIS DOCUMENT

Each section follows a consistent format:
- **What it does** — the capability
- **How you use it** — practical invocation/config
- **When to use it** — applied decision guidance

---

## 1. MEMORY & CONTEXT PERSISTENCE

### 1.1 CLAUDE.md Files
**What it does:** Markdown files Claude reads at the start of every session — your persistent instruction layer.

**Scope hierarchy (load order, broadest → most specific):**

| Scope | Path | Shared? |
|---|---|---|
| Org-wide managed | `/etc/claude-code/CLAUDE.md` (Linux) | All users on machine |
| User (all projects) | `~/.claude/CLAUDE.md` | You only |
| Project (team) | `./CLAUDE.md` or `./.claude/CLAUDE.md` | Committed to git |
| Local (personal) | `./CLAUDE.local.md` | You only, gitignored |

**How you use it:**
```bash
/init          # Auto-generate a CLAUDE.md from your codebase
/memory        # Browse, toggle, and open all loaded CLAUDE.md files
```

Import other files inline:
```markdown
See @README and @package.json for project context.
Additional workflow: @docs/git-instructions.md
```

Use HTML comments for maintainer notes (stripped from Claude's context):
```markdown
<!-- This section is for human maintainers only — Claude won't see this -->
```

**When to use it:** Add to CLAUDE.md when Claude makes the same mistake twice, when a new session loses context you keep re-explaining, or after a code review catches something Claude should have known. Keep under 200 lines per file. Move long procedures to Skills instead.

**Path-scoped rules** (`.claude/rules/`): Load instructions only when Claude works with matching files:
```markdown
---
paths:
  - "src/api/**/*.ts"
---
# API rules only load when working with TypeScript API files
```

---

### 1.2 Auto Memory
**What it does:** Claude writes its own notes across sessions — build commands, debugging insights, preferences it discovers — without you writing anything.

**Storage:** `~/.claude/projects/<project>/memory/MEMORY.md` + topic files  
**Loaded:** First 200 lines of `MEMORY.md` at every session start  
**Requires:** Claude Code v2.1.59+

**How you use it:**
```bash
/memory                    # Browse and edit saved memories
# Ask Claude to remember something:
"remember that the API tests require a local Redis instance"
# Ask Claude to add to CLAUDE.md instead:
"add this to CLAUDE.md"
```

Toggle via settings:
```json
{ "autoMemoryEnabled": false }
```

**When to use it:** Leave on by default. It learns build commands, quirks, and preferences automatically. Edit or delete entries via `/memory` when stale.

---

## 2. SKILLS (CUSTOM COMMANDS)

**What it does:** Reusable, invokable instruction packages. Like macros — you or Claude invoke them by name. Body only loads when used (unlike CLAUDE.md which always loads).

**Storage locations:**

| Scope | Path |
|---|---|
| Personal (all projects) | `~/.claude/skills/<skill-name>/SKILL.md` |
| Project | `.claude/skills/<skill-name>/SKILL.md` |
| Plugin | `<plugin>/skills/<skill-name>/SKILL.md` |

**How you use it:**
```bash
/skill-name              # Invoke directly
/skill-name arg1 arg2   # Pass arguments
"what skills are available?"  # Let Claude discover relevant ones
```

Minimal SKILL.md structure:
```yaml
---
description: What this does and when to use it. Use when user asks about X.
disable-model-invocation: true   # Only you can invoke (not Claude automatically)
allowed-tools: Bash(git *) Read  # Pre-approve tools, no prompt needed
---

# Instructions
$ARGUMENTS  # Receives whatever you type after the skill name
```

**Dynamic context injection** (runs shell commands before Claude sees the skill):
```yaml
## Current diff
!`git diff HEAD`

## Open issues
!`gh issue list --state open --limit 5`
```

**Run in isolated subagent** (keeps main context clean):
```yaml
---
context: fork
agent: Explore
---
Research $ARGUMENTS and return a summary.
```

**Key frontmatter fields:**

| Field | Purpose |
|---|---|
| `description` | Tells Claude when to auto-invoke |
| `disable-model-invocation: true` | Manual-only (good for deploy, commit, send) |
| `user-invocable: false` | Claude-only (background knowledge) |
| `allowed-tools` | Pre-approve tools for this skill |
| `paths` | Only activate for matching file patterns |
| `model` | Override model for this skill's run |
| `effort` | Set reasoning depth (low/medium/high/xhigh/max) |

**When to use it:** When you keep pasting the same instructions into chat. When a CLAUDE.md section has grown into a procedure. When you want a repeatable workflow like `/commit`, `/review-pr`, `/deploy-staging`.

---

### 2.1 html-doc Skill (User-Level, JobXplore Design System)

**What it does:** Generates self-contained single-file HTML documentation artifacts from pipeline data, Markdown source files, or prompt-provided content. Produces human-readable output with status badges, sortable tables, collapsible sections, copy-to-clipboard code blocks, and a consistent dark slate + violet identity.

**How you use it:**
```bash
/html-doc pipeline-report "Alignment Run — May 2026"   # scored job results table
/html-doc status-board "JobXplore Backlog"              # kanban + backlog table
/html-doc architecture "SaaS Stack Overview"            # component map + data flow
/html-doc setup-checklist "Environment Setup"           # interactive checkbox wizard
/html-doc insights-report "Director Analytics"          # skill frequency + gap analysis
/html-doc reference-doc "tmux Setup Guide"              # convert any .md file to HTML
/html-doc "My Title"                                    # omit type — Claude infers from content
```

Output path: `docs/html/<type>-<slug>-<YYYYMMDD>.html` (gitignored by default — commit with `git add -f` if needed)

**Non-listed types:** Pass any type keyword or omit it. If a `.md` file path is provided, it converts to `reference-doc` format (H2s → cards, H3s → collapsibles, code blocks → styled with copy button, `|Key|Action|` tables → `<kbd>`-styled shortcut tables). For all other inputs, Claude infers structure from the content.

**When to use it:** When output contains tables, status data, code blocks, or multi-section hierarchy that a human will read. Not for CLAUDE.md, memory files, or anything a program needs to parse.

**Design system:** Dark slate (`#0a0f1e` base) + violet accent (`#7c3aed`). Pipeline stage colors: sky (1) → cyan (2) → emerald (3) → amber (4) → violet (5) → pink (6). Full spec: `~/.claude/skills/html-doc/SKILL.md`.

---

## 3. HOOKS

**What it does:** Shell commands (or HTTP calls, MCP tools, or AI prompts) that run automatically at lifecycle events — before/after tool use, on session start/end, on file changes, etc.

**Hook types:**

| Type | Use |
|---|---|
| `command` | Shell script |
| `http` | POST to an endpoint |
| `mcp_tool` | Call a connected MCP server tool |
| `prompt` | LLM-based evaluation |
| `agent` | Subagent-based validation |

**Key lifecycle events:**

| Event | When it fires |
|---|---|
| `SessionStart` | Session begins |
| `PreToolUse` | Before any tool executes (can block) |
| `PostToolUse` | After tool succeeds |
| `UserPromptSubmit` | Before Claude processes your message |
| `Stop` | After Claude finishes responding |
| `FileChanged` | When watched files change |

**Config location:** `.claude/settings.json` (project) or `~/.claude/settings.json` (user)

**How you use it:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "eslint",
          "args": ["${tool_input.file_path}"]
        }]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/load-context.sh"
        }]
      }
    ]
  }
}
```

**Block a destructive command:**
```bash
#!/bin/bash
COMMAND=$(jq -r '.tool_input.command')
if echo "$COMMAND" | grep -q 'rm -rf'; then
  jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: "rm -rf blocked"}}'
fi
exit 0
```

**When to use it:** Auto-lint after edits, run tests before commit, load git context at session start, block dangerous commands, send notifications on stop, enforce conventions that CLAUDE.md alone can't guarantee.

---

## 4. MCP (MODEL CONTEXT PROTOCOL)

**What it does:** Connects Claude to external tools and data sources — databases, issue trackers, Slack, Google Drive, GitHub, Sentry, Jira, etc.

**Transport types:**

| Type | Command | Best for |
|---|---|---|
| HTTP (recommended) | `claude mcp add --transport http` | Remote APIs |
| Stdio | `claude mcp add --transport stdio` | Local processes |
| SSE | `claude mcp add --transport sse` | (Deprecated) |

**Scope options:**

| Scope | Stored in | Shared? |
|---|---|---|
| Local (default) | `~/.claude.json` | No |
| Project | `.mcp.json` in project root | Yes (committed) |
| User | `~/.claude.json` | No (all your projects) |

**How you use it:**
```bash
# Add an MCP server
claude mcp add --transport http notion https://mcp.notion.com/mcp
claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
  --header "Authorization: Bearer YOUR_TOKEN"
claude mcp add --transport stdio db -- npx -y @bytebase/dbhub \
  --dsn "postgresql://user:pass@host:5432/db"

# Manage
claude mcp list
claude mcp get <name>
claude mcp remove <name>

# Check status in session
/mcp
```

**Reference MCP resources with @:**
```
Can you analyze @github:issue://123 and suggest a fix?
```

**Use MCP prompts as slash commands:**
```
/mcp__github__list_prs
/mcp__github__pr_review 456
```

**Project `.mcp.json` with env var expansion:**
```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```

**When to use it:** Whenever Claude needs to read from or write to an external system — GitHub, databases, project management tools, monitoring, design tools, communication platforms. Add as integrations grow; document active MCPs in CLAUDE.md.

**Browser:** [claude.ai/directory](https://claude.ai/directory) — Anthropic's reviewed connector directory.

---

## 5. SUBAGENTS

**What it does:** Specialized AI assistants that handle tasks in their own isolated context window, then return only a summary to your main session. Keeps your main conversation clean and context-efficient.

**Built-in agent types:**

| Agent | Purpose | Loads CLAUDE.md? |
|---|---|---|
| `general-purpose` | Default, full tools | Yes |
| `Explore` | Read-only codebase search | No (keeps context small) |
| `Plan` | Architecture planning | No |
| Custom | Your own defined agents | Configurable |

**How you use it:**

Inline delegation (natural language):
```
use a subagent to investigate how our auth system handles token refresh
```

Custom subagent file (`.claude/agents/my-agent.md`):
```yaml
---
name: security-reviewer
description: Reviews code changes for security vulnerabilities. Use when editing auth, API, or data handling code.
model: claude-opus-4-7
allowed-tools: Read Grep Glob
---
You are a security specialist. Review the provided code for...
```

**Via Skills** (`context: fork`):
```yaml
---
name: deep-research
context: fork
agent: Explore
---
Research $ARGUMENTS thoroughly. Find relevant files, analyze code, return summary with file references.
```

**Enable persistent memory for subagents:**
```json
{ "autoMemoryEnabled": true }
```
Each subagent can maintain its own `MEMORY.md`.

**When to use it:** When a research task would flood your main context with file reads. When you need to enforce strict tool constraints on a subtask. When you want parallel work streams. When routing tasks to faster/cheaper models (Haiku for simple tasks, Opus for complex).

---

## 6. SCHEDULING & AUTOMATION

### 6.1 Routines (Cloud, Always-On)
**What it does:** Scheduled tasks that run on Anthropic-managed infrastructure — no local machine required. Can trigger on schedule, API call, or GitHub events.

**How you use it:**
```bash
/schedule                              # Create conversationally
/schedule daily PR review at 9am      # One-liner
/schedule in 2 weeks, open cleanup PR # One-off
/schedule list                         # List routines
/schedule update                       # Modify existing
/schedule run                          # Trigger immediately
```

Or manage at: `claude.ai/code/routines`

**Trigger types:**
- **Schedule:** Hourly, daily, weekdays, weekly, or custom cron (min 1hr interval)
- **API:** HTTP POST endpoint with bearer token
- **GitHub events:** PR opened/closed/updated, releases — with filters (author, label, branch, draft state)

**API trigger example:**
```bash
curl -X POST https://api.anthropic.com/v1/claude_code/routines/trig_xxx/fire \
  -H "Authorization: Bearer sk-ant-oat01-xxxxx" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"text": "Sentry alert fired in prod. Stack trace: ..."}'
```

**When to use it:** Morning PR reviews, nightly CI failure analysis, weekly dependency audits, syncing docs after merges, alert triage, automated backport PRs. Runs even when your server is off (uses Anthropic cloud).

---

### 6.2 Desktop Scheduled Tasks
**What it does:** Recurring tasks that run on your local machine via the Desktop app. Has direct access to local files and tools.

**When to use it:** When the task needs local file access or tools not available in the cloud.

---

### 6.3 `/loop` (In-Session Polling)
**What it does:** Repeats a prompt within an active CLI session on an interval.

```bash
/loop 5m "check for new failing tests and fix them"
```

**When to use it:** Quick polling while a session is open. Stops when the session ends.

---

## 7. GITHUB INTEGRATION

### 7.1 GitHub Actions
**What it does:** AI-powered automation in your GitHub CI/CD pipeline. Claude responds to `@claude` mentions in PRs and issues, or runs automatically on events.

**Setup:**
```bash
/install-github-app    # Quickstart (in Claude Code terminal)
```

Or manually:
1. Install [github.com/apps/claude](https://github.com/apps/claude) to your repo
2. Add `ANTHROPIC_API_KEY` to repo secrets
3. Add workflow file from [examples/claude.yml](https://github.com/anthropics/claude-code-action/blob/main/examples/claude.yml)

**Basic workflow:**
```yaml
name: Claude Code
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
jobs:
  claude:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Trigger with:**
```
@claude implement this feature based on the issue description
@claude fix the TypeError in the dashboard component
@claude review this PR for security issues
```

**Run a skill in CI:**
```yaml
- uses: anthropics/claude-code-action@v1
  with:
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    prompt: "/code-review"
```

**When to use it:** Automated PR reviews, issue-to-PR automation, CI-triggered analysis, scheduled reports (daily summary of commits/issues).

---

### 7.2 GitHub Code Review (Automatic)
**What it does:** Posts automatic reviews on every PR without requiring `@claude` mention.

**Setup:** Configured separately from GitHub Actions. See `/en/code-review` docs.

**When to use it:** When you want every PR reviewed automatically, without anyone needing to trigger it.

---

## 8. CHANNELS (PUSH EVENTS INTO SESSION)

**What it does:** Push messages, alerts, and webhooks into a running Claude Code session from external platforms. Two-way: Claude can reply back through the same channel.

**Supported platforms:**
- **Telegram** — Bot-based, pairing flow
- **Discord** — Bot-based, pairing flow
- **iMessage** — macOS only, reads Messages DB directly
- **Custom** — Build your own via the Channels SDK

**How you use it:**
```bash
# Install a channel plugin
/plugin install telegram@claude-plugins-official

# Start Claude with channel active
claude --channels plugin:telegram@claude-plugins-official

# Pair your account (in Claude Code after receiving pairing code from bot)
/telegram:access pair <code>
/telegram:access policy allowlist
```

**When to use it:** When you want to message Claude from your phone and have it work in your server session. When you want CI alerts, monitoring events, or webhooks to land directly in an active session. Works alongside Remote Control for mobile access.

---

## 9. REMOTE CONTROL

**What it does:** Control a running Claude Code session (on your server) from any browser or the Claude mobile app. Session lives on the server; you steer it from anywhere.

**How you use it:**
```bash
# On your server, in tmux
tmux new-session -d -s jobxplore "claude remote-control --name 'JobXplore'"

# Connect from any device
# → claude.ai/code → find session by name
# → Claude iOS app → Code → Remote Sessions
# → Scan QR code shown in tmux output
```

**Key flags:**
```bash
claude remote-control --name "JobXplore"       # Named session
claude remote-control --spawn=worktree         # Isolated git worktree per client
```

**When to use it:** Primary cross-device workflow when Claude Code is running on an always-on server. Switch from workstation → laptop → phone without losing session context. The session and full conversation history persist on the server.

---

## 10. SETTINGS & PERMISSIONS

### 10.1 Settings File Hierarchy (priority order)

| Scope | Location | Overridable? |
|---|---|---|
| Managed (org) | `/etc/claude-code/managed-settings.json` | No |
| Local | `.claude/settings.local.json` | Overrides project |
| Project | `.claude/settings.json` | Committed to git |
| User | `~/.claude/settings.json` | Lowest priority |

### 10.2 Key Permission Rules
```json
{
  "permissions": {
    "allow": ["Bash(npm run *)", "Bash(git *)"],
    "deny": ["Bash(rm -rf *)", "Read(.env)"],
    "ask": ["Bash(git push *)"]
  }
}
```

### 10.3 Permission Modes

| Mode | Behavior |
|---|---|
| Default | Ask for approval on risky actions |
| `acceptEdits` | Auto-approve file edits |
| `plan` | Read-only; propose changes, no edits until approved |
| `auto` | Auto-approve everything (use carefully) |

Toggle plan mode mid-session: `Shift+Tab`

### 10.4 Key Settings (selected)

```json
{
  "model": "claude-sonnet-4-6",
  "autoMemoryEnabled": true,
  "defaultMode": "acceptEdits",
  "effortLevel": "high",
  "autoUpdatesChannel": "stable",
  "attribution": {
    "commit": "Co-authored-by: Claude Code <noreply@anthropic.com>"
  },
  "hooks": { ... },
  "env": {
    "NODE_ENV": "development"
  }
}
```

**Interactive config:** `/config`  
**JSON schema for autocomplete:** Add `"$schema": "https://json.schemastore.org/claude-code-settings.json"` to your settings file.

---

## 11. WORKTREES (PARALLEL SESSIONS)

**What it does:** Run multiple isolated Claude sessions simultaneously on different branches/features without file conflicts.

**How you use it:**
```bash
# Terminal 1 — working on feature-auth
claude --worktree feature-auth

# Terminal 2 — simultaneously fixing a bug
claude --worktree bugfix-dashboard
```

Worktrees are separate git checkouts. Changes in one don't affect the other.

**When to use it:** When you want Claude working on a feature while you work on something else. When you want to test a risky change without touching your main working tree.

---

## 12. SURFACES & ACCESS POINTS

### 12.1 Summary of All Access Surfaces

| Surface | Best for | Notes |
|---|---|---|
| **Terminal CLI** | Full-featured, scripting, piping | `claude` command |
| **VS Code extension** | Inline diffs, @-mentions, IDE integration | Search "Claude Code" in extensions |
| **JetBrains plugin** | IntelliJ, PyCharm, WebStorm | JetBrains Marketplace |
| **Desktop app** | Visual diffs, multi-session, routines, SSH | Windows/macOS |
| **Web (claude.ai/code)** | No local setup, long-running async tasks | Browser-based |
| **iOS app** | Mobile access, remote control | Claude app |
| **Remote Control** | Steer server session from any device | `claude remote-control` |
| **GitHub Actions** | CI/CD automation, PR workflows | `@claude` trigger |
| **Slack** | Route bug reports to PRs from team chat | `@Claude` in Slack |
| **Chrome extension** | Debug live web apps | Browser debugging |
| **Channels** | Push Telegram/Discord/iMessage into session | Plugin-based |
| **Routines** | Cloud-scheduled recurring tasks | claude.ai/code/routines |

### 12.2 Cross-Device Decision Guide

| Scenario | Best approach |
|---|---|
| Working from desk (workstation or laptop) | Claude Desktop → SSH to server |
| Server session running, need to check from phone | Remote Control → claude.ai/code or iOS app |
| Want to message Claude from phone, have it act on server | Channels (Telegram/Discord/iMessage) |
| Need Claude to run while computer is off | Routines (cloud-based) |
| Automate based on PR/issue events | GitHub Actions |
| Get push alerts from monitoring/CI | Channels or Routines (API trigger) |

---

## 13. AGENT SDK & CUSTOM AGENTS

**What it does:** Build fully custom agents powered by Claude Code's tools and capabilities. Full control over orchestration, tool access, and permissions. Enables programmatic integration beyond what skills and subagents provide.

**When to use it:** When building custom automation pipelines, integrating Claude Code into your own applications, or orchestrating multi-agent workflows beyond what `.claude/agents/` configs support.

**Docs:** `code.claude.com/docs/en/agent-sdk/overview`

---

## 14. CLI REFERENCE (KEY FLAGS)

```bash
claude                           # Start interactive session
claude -p "prompt"               # Non-interactive, print mode
claude --continue                # Resume most recent session
claude --resume                  # Pick from session list
claude --worktree <name>         # Isolated parallel session
claude --permission-mode plan    # Read-only, no edits until approved
claude --channels plugin:<name>  # Start with channel active
claude remote-control --name X   # Start Remote Control session
claude --from-pr <number>        # Resume session linked to a PR
claude --max-turns 10            # Limit agentic loop turns
claude --model claude-opus-4-7   # Override model
claude --add-dir ../shared       # Grant access to additional directory
claude mcp add ...               # Add MCP server
/init                            # Generate CLAUDE.md
/memory                          # Browse memory files
/config                          # Interactive settings
/mcp                             # Check MCP server status
/schedule                        # Create a routine
/skills                          # Browse available skills
/compact                         # Compress context
/clear                           # Start fresh context
```

---

## 15. APPLIED FEATURE MAP FOR JOBXPLORE

| Need | Feature to use |
|---|---|
| Persistent project context | `CLAUDE.md` at project root |
| Personal session preferences | `~/.claude/CLAUDE.md` |
| Remember build commands, quirks | Auto Memory (on by default) |
| Repeatable workflows (commit, review, deploy) | Skills in `.claude/skills/` |
| Auto-lint after every file edit | Hook: `PostToolUse` → `Edit\|Write` |
| Load git context at session start | Hook: `SessionStart` |
| Connect to external APIs/DBs | MCP servers |
| Work from any device seamlessly | Remote Control in tmux on server |
| Reach Claude from phone | Remote Control + iOS app, or Channels |
| Automate PR reviews | GitHub Actions (`@claude`) |
| Nightly tasks (dependency audit, etc.) | Routines (cloud-scheduled) |
| Research without flooding context | Subagents (`agent: Explore`) |
| Work on two features simultaneously | Worktrees |
| Review changes before they touch disk | Plan mode (`Shift+Tab`) |
| Block destructive commands | Hooks: `PreToolUse` with deny logic |
| Architecture diagrams (living doc) | Skill that runs Mermaid generation |

---

*This document reflects Claude Code docs as of May 2026. Re-run the architecture diagram prompt from the reference guide whenever a new integration is added to keep the system map current.*
