# Cost optimization: measured comparison

Source: `bench-20261024T035739Z.json` (run bench-20261024T035739Z, model gpt-6-luna). All numbers below are computed from the benchmark exports by `scripts/write_cost_report.py`.

## Method

Each scenario was run with identical scripted user turns under each context mode, with Portkey's response cache bypassed (x-portkey-cache-force-refresh) so every request is a fresh model call. Token counts are the API's reported usage, summed per session (all roleplay turns + feedback). Decode is excluded (it is cached per scenario).

- **optimized**: Compact JSON (no indentation) for the same content; repeat lookups of an already-replayed fact are dropped from history; the redundant fact-topic list is removed (the tool's enum already lists the topics).
- **prefetch**: Optimized, plus every curated character fact placed in the static SCENARIO DATA message (a cacheable prefix), so the character rarely needs a get_scenario_facts round; the tool stays available.

Runs: 18 (3 per scenario per variant). All runs fresh (no gateway cache hits): True.

Prices: USD per 1,000,000 tokens; {"input": 0.1, "cached_input": null, "output": 0.5}. Source: AI Foundations course starter code: Lectures/Lecture 11/mult_agent_hp_tokenomics/backend/agents/pricing.py (PRICES['gpt-6-luna']) (as of 2026-10-06). Cached tokens are billed at the input rate (no cached rate is published), so prompt caching lowers latency but not the cost shown here.

## Per full simulation (conversation + feedback), mean of measured runs

"Lookup-only requests" are roleplay requests whose only output is a `get_scenario_facts` call.

| Variant | Runs | Requests | Lookup-only requests | Input tokens (sd) | Cached input | Output tokens | Cost (USD) | Quality (of 5) |
|---|---|---|---|---|---|---|---|---|
| optimized | 9 | 10.2 | 5.0 | 14,798 (±2,400) | 11,673 | 1,217 | 0.00209 | 5.00 |
| prefetch | 9 | 8.9 | 3.9 | 14,106 (±1,761) | 11,267 | 1,222 | 0.00202 | 5.00 |
| prefetch vs optimized | | -13.0% | -22.2% | -4.7% | -3.5% | +0.4% | -3.2% | +0.0% |

## By scenario (input tokens per run)

| Scenario | optimized | prefetch |
|---|---|---|
| tough-feedback | 11,375, 13,022, 13,008 (mean 12,468) | 14,781, 14,579, 10,940 (mean 13,433) |
| salary-negotiation | 16,490, 17,993, 16,286 (mean 16,923) | 13,079, 14,629, 16,467 (mean 14,725) |
| upset-client | 15,602, 12,247, 17,156 (mean 15,002) | 15,266, 11,972, 15,244 (mean 14,161) |

## Where the tokens go, by variant

| Variant | Request type | Requests | Input tokens | Share of variant's input | Output tokens | Cost (USD) |
|---|---|---|---|---|---|---|
| optimized | Roleplay, only a tool call | 45 | 61,665 | 46% | 1,046 | 0.0067 |
| optimized | Roleplay, the reply | 36 | 52,657 | 40% | 1,911 | 0.0062 |
| optimized | Feedback | 11 | 18,857 | 14% | 7,996 | 0.0059 |
| prefetch | Roleplay, only a tool call | 35 | 53,642 | 42% | 871 | 0.0058 |
| prefetch | Roleplay, the reply | 36 | 58,004 | 46% | 1,922 | 0.0068 |
| prefetch | Feedback | 9 | 15,311 | 12% | 8,202 | 0.0056 |

- optimized: cached share of input tokens (as reported by the API) 78.9%.
- prefetch: cached share of input tokens (as reported by the API) 79.9%.

## First request of each session

Same scenario, opening line and first user message in every variant. Between baseline and optimized only the packing differs; prefetch also carries every curated fact in the static scenario message.

| Scenario | optimized input tokens (calls a tool?) | prefetch input tokens (calls a tool?) |
|---|---|---|
| tough-feedback | 1133 (yes), 1133 (yes), 1133 (yes) | 1344 (yes), 1344 (yes), 1344 (no) |
| salary-negotiation | 1160 (yes), 1160 (yes), 1160 (yes) | 1346 (no), 1346 (no), 1346 (no) |
| upset-client | 1063 (yes), 1063 (yes), 1063 (yes) | 1250 (yes), 1250 (yes), 1250 (yes) |

## Quality rubric (deterministic, 1 point each)

- **in_character**: No reply broke character, and the output guard never had to regenerate.
- **facts_consistent**: Every number the character said appears in the scenario data or the user's own words.
- **concise**: Every character reply is 90 words or fewer.
- **varied**: No two character replies are more than 60% similar (difflib ratio).
- **feedback_grounded**: Feedback has all parts, validated on the first try, with no fabricated quotes removed.

| Variant | in_character | facts_consistent | concise | varied | feedback_grounded |
|---|---|---|---|---|---|
| optimized | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 |
| prefetch | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 |

Feedback scores the coach gave each run (same scripted user turns): optimized: [90, 80, 85, 90, 85, 80, 80, 85, 65] (mean 82.2); prefetch: [90, 80, 65, 90, 85, 85, 90, 85, 80] (mean 83.3).

## Earlier benchmark runs

Each earlier run is compared only within itself (same day, same conditions).

### `bench-20261024T021837Z.json`

| Variant | Runs | Requests | Lookup-only requests | Input tokens (sd) | Cached input | Output tokens | Cost (USD) | Quality (of 5) |
|---|---|---|---|---|---|---|---|---|
| baseline | 9 | 10.2 | 5.2 | 15,973 (±3,681) | 14,761 | 1,264 | 0.00223 | 5.00 |
| optimized | 9 | 10.8 | 5.6 | 15,675 (±2,270) | 14,508 | 1,177 | 0.00216 | 5.00 |
| optimized vs baseline | | +5.4% | +6.4% | -1.9% | -1.7% | -6.9% | -3.3% | +0.0% |

optimized vs baseline: -297 input tokens per session (-1.9%), standard error 1,441: within run-to-run noise.

## Conclusion

A difference counts as measured only if it is larger than two standard errors of the difference between the two variants' session means (9 sessions each).

- **prefetch vs optimized**: input tokens -691 per session (-4.7%, standard error 992), within run-to-run noise; cost -3.2% per session (within noise); requests per session 10.2 → 8.9; lookup-only requests per session 5.0 → 3.9; rubric quality 5.00 → 5.00 of 5.

The rubric checks format and numbers, not whether the character reveals hidden information too early; that needs a reading of the transcripts (see the benchmark JSON, `transcripts`).
