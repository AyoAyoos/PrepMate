# Faithfulness repro case (found during Phase 5) — HMM fabrication

Preserved for the Phase 7 faithfulness eval. Do not delete.

## The failure mode
"Rule 2 passed but rule 3 silently failed": the model had *enough* context to
avoid refusing (rule 2), but then **fabricated specificity** on top of an
otherwise-grounded umbrella (violating rule 3). Distinct from outright
refusal-avoidance.

## Repro
- Query: `Explain HMM tagging with an example`
- Corpus distances (L2, lower=better): `[0.521, 0.538, 0.688, 0.705]`
  → top hit passes MAX_DISTANCE=0.70, so the LLM is called.
- `grounded=True` (correct flag: context passed gate + no refusal marker),
  but the answer contained fabricated specifics.
- Fabricated detail: invented transition probabilities `N -> V: 0.5`,
  `V -> N: 0.3`, `ADJ -> N: 0.2` and a made-up worked example
  ("The quick brown fox jumps over the lazy dog", states
  N/V/ADJ with words like dog/cat/house, runs/jumps/eats).
  These specific numbers/words do NOT appear in the cited slide chunks.

## Why it matters
A binary grounded flag cannot catch this. Faithfulness grading on the
answerable category is required to catch "correct umbrella, invented
specifics." This is why the eval needs the three-way
Grounded / Partially-grounded / Hallucinated rubric.

## Tripwire demo
An automated keyword/number-presence check would have flagged `0.5`/`0.3`/`0.2`
automatically — good concrete jury evidence.
