"""Opt-in real service verification, without printing credentials or balances."""
from pathlib import Path
import argparse
import json
import time
import server


def wait(app, task):
    deadline = time.monotonic() + 250
    while time.monotonic() < deadline:
        job = app.store.get_job(task["job_id"])
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise RuntimeError("Verification job did not finish within its limit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume")
    args = parser.parse_args()
    root = Path(args.resume) if args.resume else Path(__file__).resolve().parent / "checks" / ("live-" + time.strftime("%Y%m%d-%H%M%S"))
    root.mkdir(parents=True, exist_ok=True)
    app = server.Application(root / "data", root / "config")
    report = server.load_json(root / "report.json") if args.resume else {"started_at": server.now(), "provider": app.settings.public(), "real_model_calls_requested": 0, "real_public_fetch": False}
    if not report["provider"]["configured"]:
        raise RuntimeError("No local model configuration")
    if args.resume:
        question = app.store.all_questions()[0]
    else:
        first = wait(app, app.analyze({"question": "依据当前材料，东方甄选FY2024–FY2025经营表现如何变化？", "period": "FY2024–FY2025", "source_ids": ["S008"]}))
        report["real_model_calls_requested"] += 1
        report["initial_analysis"] = {"status": first["status"], "error": first.get("error")}
        if first["status"] != "done":
            server.atomic_json(root / "report.json", report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            return 1
        question = first["result"]
    qid = question["id"]
    report["initial_analysis"].update(source_ids=question["source_ids"], findings=len(question["analysis"]["findings"]), mode=question["analysis"]["mode"])
    saved = question if args.resume else app.save_judgment(qid, {"text": "目前只有FY2024业绩公告，还不足以判断FY2025经营变化；需要补齐下一财年的原始报告。"})
    before = saved["judgment"]
    url = app.store.get_source("S006")["url"]
    fetched = wait(app, app.add_source(qid, {"url": url}))
    report["fetch_status"] = fetched["status"]
    report["fetch_error"] = fetched.get("error")
    if fetched["status"] == "done":
        report["real_public_fetch"] = True
        report["new_source_ids"] = fetched["result"]["pending_source_ids"]
        compared = wait(app, app.compare(qid))
        report["real_model_calls_requested"] += 1
        report["comparison_status"] = compared["status"]
        report["comparison_error"] = compared.get("error")
        if compared["status"] == "done":
            result = compared["result"]
            report["judgment_unchanged"] = result["judgment"] == before
            report["changes"] = result["comparison"]["changes"]
            report["reopened_consistent"] = server.Store(root / "data").get_question(qid) == result
    report["completed_at"] = server.now()
    server.atomic_json(root / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report.get("comparison_status") == "done" and report.get("judgment_unchanged") else 1


if __name__ == "__main__":
    raise SystemExit(main())
