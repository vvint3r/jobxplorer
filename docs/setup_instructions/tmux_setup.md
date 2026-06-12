# tmux + Claude Code: Parallel Sessions Setup

## The Concept

Each tmux pane = one independent Claude Code session. They run in parallel on your server, persist after you disconnect, and you can switch between them from any SSH connection (or even your phone via Remote Control).

---

## Option 1: Manual Pane Split (Quick Start)

SSH into your server, then:

```bash
# Start a new named tmux session
tmux new-session -s claude
```

Inside tmux:

| Action                  | Keys          |
|-------------------------|---------------|
| Vertical split (left/right)   | `Ctrl+b %`  |
| Horizontal split (up/down)    | `Ctrl+b "`  |
| Navigate between panes        | `Ctrl+b ←→↑↓` |

In each pane, start Claude:

```bash
claude          # or: claude --resume, claude --worktree <name>
```

---

## Option 2: Scripted Layout (4 Panes, Auto-Started)

Save this as `~/start-claude-sessions.sh`:

```bash
#!/bin/bash
SESSION="claude-work"

tmux new-session -d -s $SESSION -x 220 -y 50

# Split into 4 panes (2x2 grid)
tmux split-window -h -t $SESSION
tmux split-window -v -t $SESSION:0.0
tmux split-window -v -t $SESSION:0.1

# Start Claude in each pane
tmux send-keys -t $SESSION:0.0 "claude" Enter
tmux send-keys -t $SESSION:0.1 "claude" Enter
tmux send-keys -t $SESSION:0.2 "claude" Enter
tmux send-keys -t $SESSION:0.3 "claude" Enter

# Attach
tmux attach-session -t $SESSION
```

Then make it executable and run it:

```bash
chmod +x ~/start-claude-sessions.sh
./start-claude-sessions.sh
```

For 6 panes, add two more `split-window` + `send-keys` lines.

---

## Option 3: Worktrees (Recommended for Parallel Dev)

If each session works on a different feature/task, use worktrees so they don't conflict on the same files:

```bash
# Each pane gets its own isolated branch/directory
claude --worktree feature-auth
claude --worktree bugfix-dashboard
claude --worktree refactor-api
claude --worktree docs-update
```

---

## Reconnecting from Windows

From any SSH session (or Windows Terminal tab):

```bash
tmux attach -t claude-work     # rejoin existing session
tmux ls                        # list all running sessions
```

Your Claude sessions are still running exactly where you left them.

---

## Key tmux Shortcuts

| Action                   | Keys            |
|--------------------------|-----------------|
| Detach (leave running)   | `Ctrl+b d`      |
| Switch pane              | `Ctrl+b` + arrow|
| Zoom a pane (fullscreen) | `Ctrl+b z`      |
| Zoom out                 | `Ctrl+b z` again|
| New window (tab)         | `Ctrl+b c`      |
| Switch window            | `Ctrl+b 0-9`    |

---

**Recommended starting point:** run the script above for a 4-pane layout, use `--worktree` per pane if the sessions will touch the same codebase, and zoom in (`Ctrl+b z`) when you need to focus on one.
