# Comparison framework: three ways to prepare for the same conversation

**Scenario for every condition:** *Calming an upset client.* You are the account manager. Your team's integration bug pushed Bayside Clinics' patient-portal launch back a week after they had announced it to about 3,000 patients. Marcus Bell, their Director of Operations, is upset and on the phone.

## The three conditions

| | Condition | Exactly what the person gets |
|---|---|---|
| **A** | Practicing alone / generic advice | A one-page written guide made of the three generic notes in `data/guidance.json` used for this scenario (de-escalation, apologizing with ownership, closing with commitments). No interaction and no feedback on their own words. |
| **B** | General-purpose chatbot | The same model SkillSim uses (`gpt-6-luna`) with **no system prompt, no scenario data, and no tools**. The person describes the situation in their own words, asks it to play Marcus, has the conversation, then asks for feedback. The prompts used in the internal run are in `scripts/internal_evaluation.py`. |
| **C** | SkillSim Lite | The scenario as built: briefing, role-play agent with its private scenario data and fact tool, then structured feedback with verified quotes and a retry challenge. |

Using the same model for B and C means any difference comes from SkillSim's design (scenario data, prompts, tools, validation), not from a stronger model.

## Criteria

Human raters score each condition 1–5 (`comparison_ratings_template.csv`). The internal evaluation uses automatic proxies instead, listed beside each criterion. **Proxies are not the same as human judgment**, and the report should treat them as weaker evidence.

| Criterion | Question for a human rater (1 = poor, 5 = excellent) | Automatic proxy (internal evaluation) |
|---|---|---|
| **Specificity** | Does the guidance refer to *this* situation and to what *I* actually said? | Number of the user's own lines quoted verbatim (≥ 6 consecutive words) in the feedback, and number of scenario details named (e.g. "3,000 patients", "Thursday", "CEO", "staging"). |
| **Realism** | Did the other person behave like a real, upset client: pushing back, reacting to what I said, speaking naturally? | Replies stay spoken dialogue (no narration, stage directions, coaching or "as an AI"), at most 80 words, and the character pushes back at least once before agreeing. Realism is the criterion proxies capture least well. |
| **Actionability** | Do I know exactly what to say or do differently next time? | The feedback contains (a) a concrete alternative line of at least 8 words that the user did not say, and (b) one specific challenge or next step for another try. |
| **Consistency** | Does the other person stay consistent with the facts, and is the feedback stable for the same performance? | Figures the character states that appear nowhere in the scenario or the user's words (fewer is better), and the spread of the overall score across repeated runs with identical user turns (C only; A and B give no score). |
| **Time required** | How long did it take, including reading? | Measured model wait time (sum of request latencies) plus estimated reading time for advice and feedback at 200 words per minute. User typing time isn't measured in the internal run. |

## Hypotheses (made *before* any testing; not findings)

- **H1.** C will be more specific than A and B, because its feedback is required to quote the user and its character has curated facts.
- **H2.** C will be more consistent on facts than B, because B has no scenario data and may invent details.
- **H3.** B will be at least as fast as C per turn, because C makes extra tool calls; A will be fastest but offers no practice.
- **H4.** Realism will be similar for B and C, because both use the same model.
- **H5.** Real users will rate C's usefulness higher than they would rate A, but that needs participants (see `protocol.md`) and is untested.

## How results are reported

Each finding goes in one of three places, and never moves between them without new evidence:

1. **Measured (internal):** produced by `scripts/internal_evaluation.py`, with run IDs, using the proxies above. Machine-checked, with no human judgment.
2. **Measured (participants):** produced by `scripts/summarize_evaluation.py` from consented rows in `participant_data.csv` and `comparison_ratings.csv`.
3. **Hypotheses / not yet tested:** everything else, including H1–H5 until data supports or contradicts them.
