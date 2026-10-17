---
name: team-video-pipeline
description: Start, check and resume the free-model video pipeline (HyperFrames videos with sound) on this VPS (the `team-video` command). Use when the user asks about a video id, wants a render run, asks for status, or reports an audit verdict.
---

# Team pipeline (video)

The pipeline is a script; you only start it and report on it. Run these commands exactly, always through sudo as user team. Never run any other command with sudo.

| User asks | Command |
|---|---|
| status / "how is V01" | `sudo -u team /usr/local/bin/team-video status` (or `... status V01`) |
| run / start V01 | `sudo -u team /usr/local/bin/team-video check-spec V01`, then if it says `spec OK`: `sudo -u team /usr/local/bin/team-video run V01 --detach` |
| audit said BLOCK for V01 | `sudo -u team /usr/local/bin/team-video run V01 --from verdict --detach` |
| setup problems | `sudo -u team /usr/local/bin/team-video doctor` |

Rules:
- Video ids are letters, digits, `.`, `_`, `-`. Refuse anything else.
- If status shows "(a pipeline is running)", do not start another run; say when to check again. A render run takes minutes, not seconds.
- You never write briefs, edit files under /srv/team-video, push, or call Claude. The brief and the audit are done by the user in Claude Code; say so when that is the next step.
- Never print or ask for API keys. You cannot watch or hear a video; report only what status and the gates say.

Reply in the user's language with: the status line, what happens next, and the next step for the human (write the brief, run the audit with `team-video prompt video-audit V01`, or `team-video push V01` after APPROVE).
