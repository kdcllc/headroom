/auto-loop
Driver-dispatched mode: run story `%%STORY_ID%%`
from `_memory/loop/backlog.md` through ONE iteration — orchestration flow, evaluation gates,
commit only on an APPROVED audit with green targeted tests, then stop. This story
was already selected and validated by the driver: never re-evaluate eligibility
or pick another. Write learning/escalation lines to `%%OUTBOX_DIR%%/learnings.md`
and `%%OUTBOX_DIR%%/escalations.md` (names pinned) — never the shared memory
files directly. Write memory proposals to `%%OUTBOX_DIR%%/memory/` (format per
the protocol); stage only your story's paths, never `_memory/records/` or
`_memory/quarantine/`. The story id and
outbox path above are filled by the driver at
dispatch, not at setup. Set `ladder: auto` in the goal's `phases:` block. End with
the ITERATION: line naming your story id. Never push.
