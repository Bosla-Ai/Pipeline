import os
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"
import sys
import json
import time
from fastapi.testclient import TestClient

# Ensure root directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import combined_app
from src.config.settings import PIPELINE_SHARED_SECRET

def run_evaluation():
    client = TestClient(combined_app)
    
    # Load roadmap cases
    cases_path = os.path.join(os.path.dirname(__file__), "../data/eval/roadmap_cases.json")
    with open(cases_path, "r", encoding="utf-8") as f:
        roadmap_cases = json.load(f)
        
    # Load abuse cases
    abuse_path = os.path.join(os.path.dirname(__file__), "../data/eval/abuse_cases.json")
    with open(abuse_path, "r", encoding="utf-8") as f:
        abuse_cases = json.load(f)
        
    headers = {}
    if PIPELINE_SHARED_SECRET:
        headers["X-Pipeline-Secret"] = PIPELINE_SHARED_SECRET
        
    results = []
    
    print("=" * 60)
    print("RUNNING QUALITY CASES")
    print("=" * 60)
    for case in roadmap_cases:
        name = case["name"]
        req_body = case["request"]
        expect = case["expect"]
        
        start = time.perf_counter()
        # Mock socket wait to return None quickly for evaluation
        # By setting SOCKET_WAIT_TIMEOUT to 0
        os.environ["SOCKET_WAIT_TIMEOUT"] = "0"
        response = client.post("/generate-roadmap", json=req_body, headers=headers)
        duration_ms = (time.perf_counter() - start) * 1000
        
        status = response.status_code
        passed = True
        reason = "OK"
        
        if status != 200:
            passed = False
            reason = f"HTTP Status {status}"
        else:
            try:
                res_data = response.json()
                if res_data.get("status") != "success":
                    passed = False
                    reason = f"Response status: {res_data.get('status')}"
                else:
                    data = res_data.get("data", {})
                    # Check structure compatibility
                    for key in ["youtube", "udemy", "coursera", "learning_path"]:
                        if key not in data:
                            passed = False
                            reason = f"Missing key: {key}"
                            break
                            
                    # Check must_have_url
                    if passed and expect.get("must_have_url"):
                        for src, resources in data.items():
                            if src in ("youtube", "udemy", "coursera"):
                                for tag, res in resources.items():
                                    if res and not res.get("url"):
                                        passed = False
                                        reason = f"Resource for tag '{tag}' in {src} has no URL"
                                        break
                                if not passed:
                                    break
                                    
                    # Check content matches
                    keywords = expect.get("title_or_description_contains_any", [])
                    if passed and keywords:
                        match_found = False
                        for src in ("youtube", "udemy", "coursera"):
                            for tag, res in data.get(src, {}).items():
                                if res:
                                    title_desc = (res.get("title", "") + " " + res.get("description", "")).lower()
                                    if any(kw.lower() in title_desc for kw in keywords):
                                        match_found = True
                                        break
                            if match_found:
                                break
                        if not match_found:
                            passed = False
                            reason = f"No resource matched keywords: {keywords}"
            except Exception as e:
                passed = False
                reason = f"Crash during assertion: {e}"
                
        results.append({
            "name": name,
            "type": "quality",
            "status": status,
            "passed": passed,
            "reason": reason,
            "latency_ms": duration_ms
        })
        print(f"Case: {name:<35} | Passed: {str(passed):<5} | Status: {status} | Latency: {duration_ms:.1f}ms | Reason: {reason}")

    print("\n" + "=" * 60)
    print("RUNNING ABUSE CASES")
    print("=" * 60)
    for case in abuse_cases:
        name = case["name"]
        req_body = case["request"]
        expected_status = case.get("expected_status", 200)
        expect = case.get("expect", {})
        
        start = time.perf_counter()
        response = client.post("/generate-roadmap", json=req_body, headers=headers)
        duration_ms = (time.perf_counter() - start) * 1000
        
        status = response.status_code
        passed = True
        reason = "OK"
        
        if expected_status and status != expected_status:
            passed = False
            reason = f"Expected status {expected_status}, got {status}"
        else:
            # Check secret masking
            if expect.get("no_secret_strings") and PIPELINE_SHARED_SECRET:
                if PIPELINE_SHARED_SECRET in response.text:
                    passed = False
                    reason = "Response leaked PIPELINE_SHARED_SECRET"
                    
        results.append({
            "name": name,
            "type": "security",
            "status": status,
            "passed": passed,
            "reason": reason,
            "latency_ms": duration_ms
        })
        print(f"Case: {name:<35} | Passed: {str(passed):<5} | Status: {status} | Latency: {duration_ms:.1f}ms | Reason: {reason}")
        
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    failed = [r for r in results if not r["passed"]]
    print(f"Total run: {len(results)} | Passed: {len(results) - len(failed)} | Failed: {len(failed)}")
    
    # Save markdown summary
    report_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../docs/eval_runs"))
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "minimal_eval_report.md")
    
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write("# Bosla Pipeline v2 Minimal Evaluation Report\n\n")
        rf.write(f"**Date run**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        rf.write(f"**Total test cases**: {len(results)}\n")
        rf.write(f"**Passed**: {len(results) - len(failed)}\n")
        rf.write(f"**Failed**: {len(failed)}\n\n")
        rf.write("## Test Results Table\n\n")
        rf.write("| Test Name | Type | Status | Passed | Latency | Reason |\n")
        rf.write("|---|---|---|---|---|---|\n")
        for r in results:
            rf.write(f"| {r['name']} | {r['type']} | {r['status']} | {'✅' if r['passed'] else '❌'} | {r['latency_ms']:.1f}ms | {r['reason']} |\n")
            
    print(f"Markdown report generated at: {report_path}")
    return len(failed) == 0

if __name__ == "__main__":
    success = run_evaluation()
    sys.exit(0 if success else 1)
