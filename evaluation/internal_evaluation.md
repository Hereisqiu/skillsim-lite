# Internal evaluation: A vs B vs C (no human participants)

> **This is not user testing.** No people took part. Every number is an automatic proxy computed from real model outputs on repeatable, scripted test cases, as defined in `comparison_framework.md`. These numbers are not opinions, ratings, or testimonials. Participant results, once collected, go in `results_summary.md`.

Run 2026-10-24T18:09:41.295339+00:00 · model gpt-6-luna · scenario *Calming an upset client* · 3 runs each for B and C with identical scripted user turns · gateway cache bypassed · all B/C runs fresh: True

## Results (mean per run)

| Proxy | A: generic advice | B: general chatbot | C: SkillSim |
|---|---|---|---|
| user_lines_quoted (of 4) | 0 | 0.33 | 3.33 |
| quoted_user_fragments (post-hoc) | 0 | 1.67 | 4.33 |
| scenario_details_named | 0 | 8 | 8.33 |
| alternative_line (share of runs) | 0.0 | 1.0 | 1.0 |
| next_step (share of runs) | 0.0 | 0.0 | 1.0 |
| non_dialogue_replies | — | 0 | 0 |
| max_reply_words | — | 60.33 | 45.67 |
| pushback_replies (of 4) | — | 4 | 3.33 |
| invented_figures | — | 0 | 0 |
| overall_score_sd | — | — | 2.89 |
| overall_scores | — | — | [70, 75, 75] |
| model_seconds | 0 | 13.67 | 25.57 |
| reading_minutes_est | 0.56 | 1.88 | 2.51 |
| cost_usd | 0 | 0.00061 | 0.00238 |

## Hypotheses vs. these internal results

- **H1 (C more specific than A and B):** C quoted 3.33 of 4 user lines on average, B 0.33, A 0; scenario details named: C 8.33, B 8, A 0; post-hoc quoted fragments: C 4.33, B 1.67. Consistent with H1 on these proxies.
- **H2 (C more consistent on facts than B):** invented figures per run: C 0, B 0. Not supported: no difference on this proxy.
- **H3 (B at least as fast as C):** model wait per run: B 13.67 s, C 25.57 s; estimated reading: A 0.56, B 1.88, C 2.51 min. Consistent with H3.
- **H4 (similar realism for B and C):** non-dialogue replies B 0, C 0; longest reply B 60.33 words, C 45.67; pushback replies B 4, C 3.33. Proxies only; realism needs human ratings.
- **H5 (users find C more useful than A):** not testable without participants.

## What these proxies cannot tell you

- Whether the feedback actually helps someone do better in a real conversation.
- Realism as a person feels it. The proxies only check form (dialogue, length, presence of pushback).
- Condition A involves no practice, so its realism and consistency don't apply.
- B's result depends on how the person phrases the request. The internal run uses one plausible phrasing (`CHATBOT_SETUP`).
- `user_lines_quoted` (defined before the run) needs 6 consecutive words. B tends to quote shorter fragments, so it undercounts B. `quoted_user_fragments (post-hoc)` was added *after* seeing the first results (quoted fragments of 3 or more words copied from the user) and is reported alongside it, not in place of it.
- `next_step` looks for phrases like "next time". B's feedback has a "What to improve" list that is plausibly actionable but doesn't use those phrases, so this proxy likely undervalues B. C scores 1.0 because its schema always includes a retry challenge.
- B's `scenario_details_named` is high partly because the user's own setup message supplied those details.

## Scripted user turns (identical for B and C)

1. You're right to be upset, and I'm sorry. This one's on us: a bug in our integration with your scheduling system was caught in final testing and pushed your launch.
2. Our engineers found the root cause and expect the fix verified by Thursday. I'd like to show you a working demo on staging Friday.
3. I'll send you a written summary today by 5 p.m. that you can forward to your CEO. Can we check in Wednesday at 10?
4. For the go/no-go, I'll own that decision with our engineering lead, and if Thursday's verification fails we'll tell you the same day and agree a new date together before anything goes to patients.

Full transcripts and feedback for every run are in `internal_evaluation.json`.
