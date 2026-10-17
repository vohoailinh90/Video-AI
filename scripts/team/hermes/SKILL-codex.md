---
name: team-codex-pipeline
description: Start, check and resume the Codex-led free-model coding pipeline on this VPS (the `team-codex` command). Use when the user asks about a feature id, wants a pipeline run, asks for status, or reports a Codex audit verdict.
---

# Team pipeline (Codex lead)

The pipeline is a script; you only start it and report on it. Run these commands exactly, always through sudo as user team. Never run any other command with sudo.

| User asks | Command |
|---|---|
| status / "how is F12" | `sudo -u team /usr/local/bin/team-codex status` (or `... status F12`) |
| run / start F12 | `sudo -u team /usr/local/bin/team-codex check-spec F12`, then if it says `spec OK`: `sudo -u team /usr/local/bin/team-codex run F12 --detach` |
| audit said BLOCK for F12 | `sudo -u team /usr/local/bin/team-codex run F12 --from verdict --detach` |
| setup problems | `sudo -u team /usr/local/bin/team-codex doctor` |

Rules:
- Feature ids are letters, digits, `.`, `_`, `-`. Refuse anything else.
- If status shows "(a pipeline is running)", do not start another run; say when to check again.
- You never write specs, edit files under /srv/team-codex, push code, or call Codex. Specs and audits are done by the user in Codex; say so when that is the next step.
- Never print or ask for API keys.

Reply in the user's language with: the status line, what happens next, and the next step for the human (write the spec, run the audit with `team-codex prompt codex-audit F12`, or `team-codex push F12` after APPROVE).
