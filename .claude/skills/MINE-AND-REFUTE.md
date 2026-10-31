# Mine and refute (shared protocol)

The fact-grounding method for any skill that writes a piece from verified facts (a case study, a paper, a long write-up). Each meaning lives here once; a calling skill adds only its own deltas (what scopes the miners, extra reconciliation rules, which register the voice refuter reads).

## Mine

Run a Workflow: parallel miners over whatever the subject needs (git history, the issue board, code mechanisms, decision records; miners follow [`DOMAIN-AWARENESS.md`](DOMAIN-AWARENESS.md)), plus one adversarial refuter that reruns every claim and marks it CONFIRMED, CORRECTED or REFUTED. Survivors land in numbered `material/NN-<slice>.md` fact sheets: one fact per bullet, paired with the command that recomputes it, honesty caveats attached to the fact they qualify.

A fact sheet is a dated record: when a fact changes later (a recount moves, the repository ships a change under the sheet), the bullet gets a dated CORRECTED note beside the old value, citing the change commit, never a silent rewrite.

Done when: every fact in `material/` has a recompute command and survived refutation; caveats travel with their fact.

## Refute the draft

Run a Workflow with three parallel refuters over the draft: facts, against the material sheets and the repository itself; voice, against the calling skill's register and [`.claude/soul.md`](../soul.md); citation drift, checking each reference still says what its sentence claims. Apply every blocker and should-fix; a finding you reject goes into the directory README with one line of why, so the next pass does not re-raise it.

Done when: every blocker's fix is verified in place; one verifier agent re-checking the applied fixes suffices when it finds nothing new, and a full refuter rerun is needed only when it does. Each should-fix is applied or recorded as rejected.
