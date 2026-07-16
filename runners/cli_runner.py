import asyncio
import os
import sys
import json
import argparse
import copy

# Append the project root to sys.path to resolve core and utils modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.agent import run_autonomous_navigator, load_unified_config
from core.jira_pipeline import run_full_pipeline

async def run_parallel_suite(config):
    targets = [
        {
            "name": "Optimworks Employee Add",
            "url": "https://dev.urbuddi.com/login",
            "goal": "Log into the system and completely add a new employee profile, ensuring no mandatory field is left blank."
        },
        {
            "name": "Moodle Admin Verify",
            "url": "https://sandbox.moodledemo.net/login/index.php",
            "goal": "Log into the system using admin credentials and verify you can view the dashboard."
        }
    ]
    
    tasks = []
    for idx, target in enumerate(targets):
        run_id = target["name"].lower().replace(" ", "_")
        config_copy = copy.deepcopy(config)
        tasks.append(
            run_autonomous_navigator(
                config_registry=config_copy,
                target_url=target["url"],
                user_goal=target["goal"],
                run_id=run_id
            )
        )
        
    print("🚀 Spawning Parallel AI Test Automation Suite concurrently...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    print("\n" + "="*50)
    print("📊 CONSOLIDATED ENTERPRISE QA METRICS MATRIX")
    print("="*50)
    all_succeeded = True
    telemetry_reports = []
    for idx, res in enumerate(results):
        target = targets[idx]
        if isinstance(res, Exception):
            print(f"App: {target['name']} | Status: CRASHED/ERROR | Steps: 0 | Error: {res}")
            all_succeeded = False
        else:
            print(f"App: {res.get('run_id')} | Status: {res.get('status')} | Steps: {res.get('total_steps')} | Duration: {res.get('duration_seconds')}s | Final: {res.get('is_final')}")
            print(f"  Screenshot: {res.get('screenshot_path')}")
            if res.get('telemetry_report'):
                telemetry_reports.append((res.get('run_id'), res.get('telemetry_report')))
            if not res.get("is_final") or res.get("status") != "SUCCESS":
                all_succeeded = False
    print("="*50 + "\n")

    if telemetry_reports:
        print("==================================================")
        print("📊 CONSOLIDATED PERFORMANCE TELEMETRY REPORTS")
        print("==================================================")
        for run_id, report in telemetry_reports:
            print(f"\n[Run: {run_id}]")
            print(report)
        print("==================================================\n")

    if all_succeeded:
        print("🎉 Parallel AI Test Automation Suite completed successfully.")
        return 0
    else:
        print("❌ Parallel AI Test Automation Suite failed or encountered errors.")
        return 1

async def main():
    parser = argparse.ArgumentParser(description="Parallel AI Automation CLI Runner & QA Pipeline Orchestrator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--suite", action="store_true", help="Execute the parallel multi-app automation suite (default).")
    group.add_argument("--jira", "--jira-url", type=str, dest="jira", help="Execute the E2E Jira QA Pipeline for the given Jira ticket/story URL.")
    
    parser.add_argument("--sample-run", "-s", action="store_true", default=False, help="Isolated E2E smoke test on the first test scenario only.")
    parser.add_argument("--headed", action="store_true", default=False, help="Execute the Playwright browser in headed mode.")
    parser.add_argument("--target-url", type=str, help="Inject target URL override for application under test.")
    
    args = parser.parse_known_args()[0]
    
    config = load_unified_config()
    # Configure browser visibility based on CLI overrides (default to headless)
    if args.headed:
        config["environment"]["headless"] = False
    else:
        config["environment"]["headless"] = True
        
    if args.target_url:
        config["environment"]["target_url"] = args.target_url
    
    if args.jira:
        print(f"📡 Launching E2E Jira QA Pipeline for URL: {args.jira}")
        try:
            # Resolve relative outputs directory absolutely to project root
            outputs_dir = os.path.join(project_root, "outputs")
            await run_full_pipeline(
                jira_url=args.jira, 
                output_dir=outputs_dir, 
                sample_run=args.sample_run, 
                target_url=args.target_url
            )
            sys.exit(0)
        except Exception as e:
            print(f"❌ Jira QA Pipeline execution crashed: {e}")
            sys.exit(1)
    else:
        # Default behavior: run parallel multi-app test suite
        exit_code = await run_parallel_suite(config)
        sys.exit(exit_code)

if __name__ == "__main__":
    asyncio.run(main())
