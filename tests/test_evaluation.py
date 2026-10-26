"""Tests for the evaluation summary script. The rows below are synthetic test fixtures that exercise
the code paths. They are not participant data and never appear in any evaluation output."""

from __future__ import annotations

import unittest

from scripts.summarize_evaluation import clean_participants, summarize

HEADER = dict.fromkeys(["participant_id", "consent_data", "consent_quote", "consent_transcript", "finished",
                        "time_minutes", "turns", "opened_decode", "usefulness", "realism", "retried", "feedback",
                        "observed_issues"], "")


def row(**kw):
    return {**HEADER, **kw}


class SummaryTests(unittest.TestCase):
    def test_no_data_produces_no_numbers(self):
        text = summarize([], [])
        self.assertIn("No participant data collected yet", text)
        self.assertIn("No human comparison ratings collected yet", text)
        self.assertNotIn("mean", text)

    def test_rows_without_data_consent_are_not_counted(self):
        rows = [row(participant_id="T1", consent_data="no", usefulness="5"),
                row(participant_id="T2", consent_data="", usefulness="5")]
        kept, declined, problems = clean_participants(rows)
        self.assertEqual((kept, declined), ([], 1))
        self.assertTrue(any("T2" in p for p in problems))
        self.assertIn("No participant data collected yet", summarize(rows, []))

    def test_feedback_is_quoted_only_with_quote_consent(self):
        rows = [row(participant_id="T1", consent_data="yes", consent_quote="yes", feedback="fixture comment one"),
                row(participant_id="T2", consent_data="yes", consent_quote="no", feedback="fixture comment two")]
        text = summarize(rows, [])
        self.assertIn("fixture comment one", text)
        self.assertNotIn("fixture comment two", text)
        self.assertIn("1 more comment(s) recorded but not quoted", text)

    def test_out_of_range_ratings_are_rejected_not_clamped(self):
        kept, _, problems = clean_participants([row(participant_id="T1", consent_data="yes", usefulness="7")])
        self.assertEqual(kept, [])
        self.assertTrue(any("out of range" in p for p in problems))

    def test_small_samples_are_flagged(self):
        text = summarize([row(participant_id="T1", consent_data="yes", finished="yes", time_minutes="8",
                              usefulness="4", realism="3", retried="no")], [])
        self.assertIn("fewer than 5 participants", text)
        self.assertIn("1 of 1", text)

    def test_comparison_ratings_by_condition(self):
        ratings = [{"condition": "C", "specificity": "4", "realism": "3", "actionability": "5", "consistency": "4", "time_minutes": "9"},
                   {"condition": "Z", "specificity": "4"}]
        text = summarize([], ratings)
        self.assertIn("| C |", text)
        self.assertIn("condition must be A, B, or C", text)
