You are one member of a three-model review council (gpt-6-astra, Claude Fable 5.1, Claude Opus 5.5). Today is 2026-09-29. This is ROUND 2: the approval vote.

In round 1 the council reviewed docs/council/plan-r1.md; the three reviews are docs/council/astra.md, fable.md, opus.md, and the synthesis is docs/council/README.md. The maintainer revised the plan into docs/PLAN.md (r2, final). Read docs/PLAN.md in full and docs/council/README.md; consult the round-1 reviews as needed.

Your job: decide whether r2 can be approved as the plan to build from.
- Check every P0 and P1 from round 1 (all three reviews, not only your own): is it addressed in r2, partially addressed, or missing?
- Flag anything r2 introduced that is wrong or unsafe.
- Do not re-litigate decisions the maintainer made with a stated reason (Copilot first, Python, Terraform only, no Proton) unless they are unsafe.
- Only block approval for a P0 (unsafe or wrong) or a P1 (must fix before building). Everything else is a condition or a note.

Output format (markdown), terse:
## Vote
APPROVE | APPROVE WITH CONDITIONS | REJECT, plus one sentence.
## Round-1 findings status
A compact table: finding (reviewer + number) | status (addressed / partial / missing) | note. Cover every P0/P1 from all three reviews.
## Conditions (if any)
Numbered; each a concrete edit to PLAN.md, with the section.
## New issues in r2
Bullets with P-level, or "none".

Do not modify any files. Read-only review.
