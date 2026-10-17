---
name: team-pipeline
description: Start, check and resume the free-model coding pipeline on this VPS (the `team` command). Use when the user asks about a feature id, wants a pipeline run, asks for status, or reports a Claude audit verdict.
---

# Team pipeline

The pipeline is a script; you only start it and report on it. Run these commands exactly, always through sudo as user team. Never run any other command with sudo.

| User asks | Command |
|---|---|
| status / "how is F12" | `sudo -u team /usr/local/bin/team status` (or `... status F12`) |
| run / start F12 | `sudo -u team /usr/local/bin/team check-spec F12`, then if it says `spec OK`: `sudo -u team /usr/local/bin/team run F12 --detach` |
| audit said BLOCK for F12 | `sudo -u team /usr/local/bin/team run F12 --from verdict --detach` |
| setup problems | `sudo -u team /usr/local/bin/team doctor` |

Rules:
- Feature ids are letters, digits, `.`, `_`, `-`. Refuse anything else.
- If status shows "(a pipeline is running)", do not start another run; say when to check again.
- You never write specs, edit files under /srv/team, push code, or call Claude. Specs and audits are done by the user in Claude Code; say so when that is the next step.
- Never print or ask for API keys.

Reply in the user's language with: the status line, what happens next, and the next step for the human (write the spec, run the audit with `team prompt claude-audit F12`, or `team push F12` after APPROVE).
