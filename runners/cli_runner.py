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
        
    print("🚀 Spawning parallel runs concurrently...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    print("\n" + "="*50)
    print("📊 CONSOLIDATED ENTERPRISE QA METRICS MATRIX")
    print("="*50)
    for idx, res in enumerate(results):
        target = targets[idx]
        if isinstance(res, Exception):
            print(f"App: {target['name']} | Status: CRASHED/ERROR | Steps: 0 | Error: {res}")
        else:
            print(f"App: {res.get('run_id')} | Status: {res.get('status')} | Steps: {res.get('total_steps')} | Duration: {res.get('duration_seconds')}s | Final: {res.get('is_final')}")
            print(f"  Screenshot: {res.get('screenshot_path')}")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
