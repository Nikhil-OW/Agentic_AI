import asyncio
import os
import json
import sys
# Append the project root to sys.path to resolve core and utils modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.agent import run_autonomous_navigator, load_unified_config

async def main():
    config = load_unified_config()
    # Force headless for automated CLI verification run
    config["environment"]["headless"] = True
    
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
    import copy
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
        sys.exit(0)
    else:
        print("❌ Parallel AI Test Automation Suite failed or encountered errors.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
