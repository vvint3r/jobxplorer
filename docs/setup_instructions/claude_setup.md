# Claude Code Remote Control — JobXplore Setup Reference

## Environment

| Component    | Detail                                         |
| ------------ | ---------------------------------------------- |
| Server       | Ubuntu Server @ 192.168.5.200 (always on)      |
| Project path | `/home/wynt3r/CareerOps/JobXplore`             |
| GitHub repo  | `github.com/wynt3r/JobXplore` (existing)       |
| Clients      | Windows 11 Workstation, Windows 11 Laptop, iOS |

---

## One-Time Server Setup

SSH into your server and run:

```bash
# Install Claude Code CLI (if not already installed)
npm install -g @anthropic-ai/claude-code

# Navigate to your project
cd /home/wynt3r/CareerOps/JobXplore

# Start a persistent Remote Control session in tmux
tmux new-session -d -s jobxplore "claude remote-control --name 'JobXplore'"

# Verify it's running
tmux ls
```

To attach and see the session URL / QR code:

```bash
tmux attach -t jobxplore
# Press Ctrl+B then D to detach without killing it
```

---

## Connecting From Each Device

**Windows Workstation / Laptop**
- Open browser → [claude.ai/code](https://claude.ai/code)
- Find the session named `JobXplore` in your session list
- Or: paste the session URL shown in tmux output

**iOS**
- Open the Claude mobile app
- Tap the Code icon → Remote Sessions
- Find `JobXplore` or scan the QR code from your tmux terminal

---

## Day-to-Day Workflow

### Starting your day (server already running)

```bash
# Check the session is alive
tmux ls

# If it died (e.g. after network outage), restart it
cd /home/wynt3r/CareerOps/JobXplore
tmux new-session -d -s jobxplore "claude remote-control --name 'JobXplore'"
```

### Switching devices mid-session

Just connect from the new device via [claude.ai/code](https://claude.ai/code) — the session and full conversation context are preserved on the server.

### After a server reboot

tmux sessions don't survive reboots. Re-run the startup command above, or add it to your server's startup script.

### Optional — auto-restart on reboot

Add to crontab with `crontab -e`:

```cron
@reboot cd /home/wynt3r/CareerOps/JobXplore && tmux new-session -d -s jobxplore "claude remote-control --name 'JobXplore'"
```

---

## Useful Commands

| Command                          | Purpose                                 |
| -------------------------------- | --------------------------------------- |
| `tmux ls`                        | List active sessions                    |
| `tmux attach -t jobxplore`       | Attach to view/interact in terminal     |
| `tmux kill-session -t jobxplore` | Stop the session                        |
| `Ctrl+B, D`                      | Detach from tmux (keeps session alive)  |

---

## Agent Context

Paste this at the start of a new Claude Code session:

> You are working on **JobXplore**, a career operations tool located at:
> `/home/wynt3r/CareerOps/JobXplore`
>
> This project is version-controlled with Git and has an active GitHub repository.
> The runtime environment is an Ubuntu Server (192.168.5.200), always on.
> Sessions are accessed remotely via Claude Code Remote Control from:
> - Windows 11 Workstation
> - Windows 11 Laptop
> - iOS (Claude mobile app)
>
> **Before starting work each session:**
> 1. Review `CLAUDE.md` in the project root for current goals, conventions, and in-progress work
> 2. Run `git status` and `git log --oneline -10` to orient to current branch state
> 3. Check for any TODOs or notes left in `CLAUDE.md` from the previous session
>
> **Keep `CLAUDE.md` updated at the end of each session with:**
> - Current focus / what was worked on
> - Next steps
> - Any decisions made and why
> - Active integrations (MCPs, connectors, plugins, APIs)

---

## Architecture Diagram Prompt

Use this prompt with Claude Code to generate and maintain a living architecture diagram for the project:

> Generate a Mermaid diagram that maps the current architecture of the JobXplore project.
> The diagram should include:
>
> 1. The runtime environment (Ubuntu Server @ 192.168.5.200)
> 2. The Claude Code Remote Control session (tmux, persistent)
> 3. Client access points: Windows Workstation, Windows Laptop, iOS app — all connecting via `claude.ai/code`
> 4. The GitHub repository and its relationship to the local project path
> 5. All active MCP servers, connectors, plugins, and external API integrations (read these from `CLAUDE.md` or any config files present in the project)
> 6. Data flow arrows showing how each component interacts
>
> **Format:** Mermaid flowchart (LR orientation)
> **Save to:** `/home/wynt3r/CareerOps/JobXplore/docs/architecture.md`
>
> After generating, note in `CLAUDE.md` that this diagram exists and should be regenerated whenever a new integration is added.

---

## Notes

- Session conversation history lives on the server — switching devices never loses context
- `CLAUDE.md` is your persistent knowledge layer across sessions (even if the tmux session dies)
- Add new MCPs/integrations to `CLAUDE.md` so the agent re-learns them at every session start
- Re-run the diagram prompt any time the integration landscape changes
