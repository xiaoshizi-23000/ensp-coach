import time
from collections import defaultdict


DAY = 86400


def build_review_plan(checks, grades, quizzes, lab_titles, now=None, limit=8):
    now = time.time() if now is None else now
    grades_by_lab = defaultdict(list)
    for grade in grades:
        grades_by_lab[grade.get("lab")].append(grade)

    failures = {}
    for event in checks:
        if event.get("type") != "check":
            continue
        key = (event.get("lab"), event.get("step"), event.get("dev"), event.get("cmd"))
        item = failures.setdefault(key, {
            "count": 0, "last": 0, "title": event.get("title", ""),
            "out": event.get("out", ""),
        })
        item["count"] += 1
        ts = float(event.get("ts") or 0)
        if ts >= item["last"]:
            item["last"] = ts
            item["title"] = event.get("title", "") or item["title"]
            item["out"] = event.get("out", "") or item["out"]

    recommendations = []
    scheduled = 0
    for (lab_id, step_id, dev, command), item in failures.items():
        later = [g for g in grades_by_lab.get(lab_id, [])
                 if float(g.get("ts") or 0) >= item["last"]]
        latest_grade = max(later, key=lambda g: float(g.get("ts") or 0)) if later else None
        score = float(latest_grade.get("score", 0)) if latest_grade else None
        due = item["last"]
        mastered = False
        if score is not None and score >= 80:
            due = float(latest_grade["ts"]) + 14 * DAY
            mastered = True
        elif score is not None and score >= 60:
            due = float(latest_grade["ts"]) + 7 * DAY
            mastered = True
        if due > now:
            scheduled += 1
            continue
        overdue = max(0.0, now - due)
        priority = item["count"] * 100 + min(overdue / 3600, 72)
        recommendations.append({
            "id": f"lab:{lab_id}:{step_id}:{dev}:{command}",
            "kind": "lab",
            "labId": lab_id,
            "stepId": step_id,
            "title": lab_titles.get(lab_id, lab_id),
            "detail": f"{dev} · {command}",
            "reason": f"这条检查失败了 {item['count']} 次" + (
                "，最近一次交卷已达到掌握线" if mastered else ""),
            "dueAt": due,
            "overdue": overdue,
            "priority": round(priority, 1),
            "action": "重做实验",
        })

    quiz_state = {}
    for event in quizzes:
        qid = event.get("quiz")
        if not qid:
            continue
        state = quiz_state.setdefault(qid, {
            "wrong": 0, "lastWrong": 0, "lastCorrect": 0,
            "title": event.get("title", qid), "choice": "",
        })
        ts = float(event.get("ts") or 0)
        if event.get("out") == "对":
            state["lastCorrect"] = max(state["lastCorrect"], ts)
        else:
            state["wrong"] += 1
            state["lastWrong"] = max(state["lastWrong"], ts)
            state["title"] = event.get("title", "") or state["title"]
            state["choice"] = event.get("cmd", "") or state["choice"]

    for qid, item in quiz_state.items():
        if not item["wrong"]:
            continue
        if item["lastCorrect"] >= item["lastWrong"]:
            due = item["lastCorrect"] + 7 * DAY
            if due > now:
                scheduled += 1
                continue
            reason = "错过后已经答对，进入 7 天巩固复习"
        else:
            due = item["lastWrong"]
            reason = f"答错过 {item['wrong']} 次，尚未重新答对"
        overdue = max(0.0, now - due)
        recommendations.append({
            "id": "quiz:" + qid,
            "kind": "quiz",
            "quizId": qid,
            "title": item["title"],
            "detail": "上次误选：" + (item["choice"] or "未记录"),
            "reason": reason,
            "dueAt": due,
            "overdue": overdue,
            "priority": round(item["wrong"] * 85 + min(overdue / 3600, 72), 1),
            "action": "重做此题",
        })

    recommendations.sort(key=lambda item: (item["priority"], item["dueAt"]), reverse=True)
    return {
        "items": recommendations[:limit],
        "due": len(recommendations),
        "scheduled": scheduled,
        "generatedAt": now,
    }
