import asyncio
import os
import sys

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.jira_pipeline import run_full_pipeline

async def main():
    # Use a dummy mock Jira URL to trigger the perception extractor fallback
    # The extractor parses it and maps it to a pilot run verifying Moodle Admin dashboard access
    jira_url = "mock://issue/QA-452-moodle-dashboard-verification"
    
    print("🎬 Starting Pilot Smoke Run of E2E Jira QA Pipeline...")
    try:
        await run_full_pipeline(jira_url=jira_url, output_dir="outputs")
        print("\n🎉 Smoke run completed successfully!")
    except Exception as e:
        print(f"\n❌ Smoke run crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
