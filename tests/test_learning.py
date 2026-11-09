import unittest

from learning import DAY, build_review_plan


NOW = 2_000_000_000.0
TITLES = {"tr-route": "静态路由排错"}


def check(ts, lab="tr-route", step="s1", cmd="display ip routing-table"):
    return {"ts": ts, "type": "check", "lab": lab, "step": step,
            "dev": "R1", "cmd": cmd, "title": "定位并修复", "out": ""}


class ReviewPlanTests(unittest.TestCase):
    def plan(self, checks, grades=None, quizzes=None):
        return build_review_plan(checks, grades or [], quizzes or [], TITLES, now=NOW)

    def test_unresolved_failure_is_due_now(self):
        result = self.plan([check(NOW - 3600)])
        self.assertEqual(result["due"], 1)
        self.assertEqual(result["items"][0]["kind"], "lab")
        self.assertEqual(result["items"][0]["labId"], "tr-route")

    def test_recent_high_grade_schedules_follow_up(self):
        result = self.plan(
            [check(NOW - 2 * DAY)],
            [{"ts": NOW - DAY, "type": "grade", "lab": "tr-route", "score": 90}],
        )
        self.assertEqual(result["due"], 0)
        self.assertEqual(result["scheduled"], 1)

    def test_failed_grade_keeps_item_due(self):
        result = self.plan(
            [check(NOW - 2 * DAY)],
            [{"ts": NOW - DAY, "type": "grade", "lab": "tr-route", "score": 50}],
        )
        self.assertEqual(result["due"], 1)

    def test_quiz_wrong_then_correct_enters_review(self):
        result = self.plan([], quizzes=[
            {"ts": NOW - 8 * DAY, "type": "quiz", "quiz": "qz-trunk", "title": "Trunk",
             "cmd": "G0/0/1", "out": "错"},
            {"ts": NOW - 7 * DAY, "type": "quiz", "quiz": "qz-trunk", "title": "Trunk",
             "cmd": "G0/0/1", "out": "对"},
        ])
        self.assertEqual(result["due"], 1)
        self.assertEqual(result["items"][0]["quizId"], "qz-trunk")

    def test_quiz_correct_recently_is_scheduled(self):
        result = self.plan([], quizzes=[
            {"ts": NOW - 2 * DAY, "type": "quiz", "quiz": "qz-trunk", "title": "Trunk",
             "cmd": "A", "out": "错"},
            {"ts": NOW - DAY, "type": "quiz", "quiz": "qz-trunk", "title": "Trunk",
             "cmd": "A", "out": "对"},
        ])
        self.assertEqual(result["due"], 0)
        self.assertEqual(result["scheduled"], 1)


if __name__ == "__main__":
    unittest.main()
