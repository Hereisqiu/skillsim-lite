# SkillSim Lite: usability and quality evaluation protocol

**Length:** 10–15 minutes per participant. **Scenario (same for everyone):** *Calming an upset client* (Beginner).
**Facilitator:** one person runs the session and takes notes. **Participants:** classmates, colleagues, or friends who volunteer.

This is an informal usability check for a course project, not a research study. Nothing is published beyond the course report. If you plan to publish or present the results outside the course, check your institution's human-subjects (IRB) rules first.

---

## 1. Before the session (facilitator)

- Start the app (`python run.py`) in a **fresh browser profile or private window**, so the participant starts with an empty History.
- Open `evaluation/participant_data.csv` (a copy of `participant_data_template.csv`). Assign the next participant ID (`P01`, `P02`, …). **Do not record names, emails, employers, or other identifying details.**
- Have a timer ready.

## 2. Consent (read aloud, about 1 minute)

> "Thanks for helping. I'm testing a practice tool for difficult workplace conversations. You'll read a short scenario, have a 4–6 message conversation with an AI character, read its feedback, and answer a few questions. It takes about 10 to 15 minutes.
>
> I'm testing the tool, not you. There are no right answers, and you can stop at any time without giving a reason.
>
> Your conversation is stored only on this laptop, and I'll delete it at the end unless you say I can keep it. Please don't type real names, companies, or private information; make things up if you need to.
>
> I'd like to record, under an ID number and not your name: whether you finished, how long it took, two 1–5 ratings, one piece of feedback, and what I see go wrong. Separately, may I quote your feedback word for word in my class report? And may I keep the conversation text itself?
>
> You can say yes or no to each of these. If you say no to everything, you can still try the tool, and I won't write anything down."

Record the answers in three columns (`yes` or `no`):

| Column | Question | If `no` |
|---|---|---|
| `consent_data` | May I record the measurements and notes? | Write only the participant ID and `no`. Leave every other column blank. The summary script ignores the row. |
| `consent_quote` | May I quote your feedback word for word? | Paraphrase it, or leave `feedback` blank. The summary script never prints it. |
| `consent_transcript` | May I keep the conversation text? | Click **History → Delete my history** before the participant leaves. |

A participant can withdraw later: delete their row and their session.

## 3. Task (about 8–10 minutes; start the timer when they click "Choose a scenario")

Say only: *"Please find the 'Calming an upset client' scenario, read it, practice the conversation, and look at your feedback. Think out loud if you're comfortable. I won't help unless you're stuck for more than a minute."*

1. Select the scenario and read the context. Reading **Decode this situation** is optional; note whether they open it.
2. Have the conversation until they choose to end it (the app allows up to 12 turns).
3. End the conversation and read the feedback.
4. **Stop the timer** when they finish reading the feedback, or say they're done.
5. Note whether they click **Retry** on their own. **Do not prompt them to retry.** If they do retry, let them continue but don't time it.

**Observe and note** (in `observed_issues`, as short neutral descriptions): hesitations over 10 seconds, wrong clicks, error messages, the character replying oddly, feedback that seemed wrong, and anything the participant said aloud that showed confusion. Write what happened, not what you think caused it.

## 4. Questions (about 2 minutes, read exactly)

1. "On a scale of 1 to 5, how **useful** was this for preparing for a conversation like this? 1 is not useful at all, 5 is very useful."
2. "On a scale of 1 to 5, how **realistic** did the client feel? 1 is not realistic at all, 5 is very realistic."
3. "What is **one** concrete thing you would change or keep?"

Write answer 3 as close to word for word as you can, in `feedback`.

## 5. Wrap-up

- Thank them. If `consent_transcript` is `no`, delete their history now, in front of them.
- If they finished, copy the session ID from the URL (`#/session/<id>/feedback`) into `session_id`, only if `consent_transcript` is `yes`.

## 6. What each column means

| Column | Values | Notes |
|---|---|---|
| `participant_id` | `P01`… | Never a name |
| `date` | `YYYY-MM-DD` | |
| `facilitator` | initials | |
| `consent_data`, `consent_quote`, `consent_transcript` | `yes` / `no` | See section 2 |
| `prior_experience` | `none` / `some` / `a lot` | Ask: "Have you had a conversation like this at work?" (optional) |
| `finished` | `yes` / `no` | Reached the feedback page |
| `time_minutes` | number, e.g. `7.5` | From "Choose a scenario" to finishing the feedback |
| `turns` | integer | User messages sent (shown in the sidebar) |
| `opened_decode` | `yes` / `no` | |
| `usefulness` | 1–5 | Question 1 |
| `realism` | 1–5 | Question 2 |
| `retried` | `yes` / `no` | Clicked Retry without being prompted |
| `feedback` | text | Question 3 (only quoted in the report if `consent_quote` is `yes`) |
| `observed_issues` | text | Separate items with `;` |
| `session_id` | text | Optional, only with `consent_transcript` = `yes` |

## 7. After collecting data

```bash
python -m scripts.summarize_evaluation
```

This writes `evaluation/results_summary.md` from consented rows only. If there are no consented rows, it says so instead of producing numbers.
