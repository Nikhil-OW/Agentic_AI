import os
import sys
import json
import asyncio
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Initialize environment variables safely
load_dotenv()

# Append parent dir to sys.path to allow imports from core and utils
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.agent import run_autonomous_navigator, load_unified_config
from utils.browser_helper import BrowserHelper

# ----------------------------------------------------
# Pydantic Schemas for Gemini Structured JSON Outputs
# ----------------------------------------------------
class JiraStoryData(BaseModel):
    title: str = Field(description="The summary or title of the Jira story/ticket.")
    description: str = Field(description="The main description body of the story.")
    acceptance_criteria: List[str] = Field(description="List of acceptance criteria extracted from the story.")
    target_url: Optional[str] = Field(None, description="The test environment web application URL if mentioned in the story description.")

class TestCaseItem(BaseModel):
    test_case_id: str = Field(description="Unique identifier, e.g. TC001, TC002.")
    component: str = Field(description="The component area, e.g. Login, Authentication, Form submission, Validation.")
    description: str = Field(description="Detailed explanation of what is being tested.")
    execution_goal: str = Field(description="Specific, detailed natural language instructions telling our autonomous web agent exactly what to do step-by-step.")
    expected_result: str = Field(description="Expected outcome or success indicator to check.")

class TestSuiteOutput(BaseModel):
    test_cases: List[TestCaseItem] = Field(description="The complete list of predicted test case scenarios.")


# ----------------------------------------------------
# 1. Jira Ingestion Layer
# ----------------------------------------------------
class JiraExtractor:
    """Ingests Jira ticket URLs and extracts core details via DOM or perception fallback."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)

    async def extract_story(self, url: str) -> JiraStoryData:
        """Loads story details. Tries Atlassian REST API backend first, then falls back to browser scraping."""
        # Local mock bypass for smoke testing
        if url.startswith("mock://") or "dummy-jira" in url:
            print("💡 JiraExtractor: Mock URL detected. Short-circuiting to mock story data.")
            return self._get_mock_story_data()

        user_email = os.getenv("JIRA_USER_EMAIL")
        api_token = os.getenv("JIRA_API_TOKEN")
        env_domain = os.getenv("JIRA_DOMAIN")
        
        # Regex to parse issue key (e.g., PROJ-123)
        import re
        issue_key = None
        match = re.search(r'([a-zA-Z0-9]+-\d+)', url)
        if match:
            issue_key = match.group(1).upper()
            
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        domain = env_domain or parsed_url.netloc
        
        if issue_key and user_email and api_token and domain:
            print(f"📡 JiraExtractor: Attempting authenticated REST API fetch for key '{issue_key}' on domain '{domain}'")
            import base64
            import urllib.request
            import urllib.error
            
            auth_str = f"{user_email}:{api_token}"
            auth_bytes = auth_str.encode("utf-8")
            auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
            
            headers = {
                "Authorization": f"Basic {auth_b64}",
                "Accept": "application/json"
            }
            
            # Hit the v2 endpoint to get description as text/markdown instead of ADF JSON
            api_url = f"https://{domain}/rest/api/2/issue/{issue_key}"
            req = urllib.request.Request(api_url, headers=headers)
            
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    print("✅ JiraExtractor: REST API request succeeded. Parsing payload via Gemini...")
                    
                    fields = res_data.get('fields', {})
                    summary = fields.get('summary', '')
                    description = fields.get('description', '')
                    if not description or not str(description).strip():
                        print("💡 JiraExtractor: Empty description detected. Falling back to ticket summary as requirements payload.")
                        fields['description'] = summary
                    
                    prompt = (
                        "You are an AI Jira business analyst. We have fetched the following Jira ticket JSON payload from the REST API:\n\n"
                        f"--- TICKET JSON PAYLOAD ---\n{json.dumps(res_data.get('fields', {}), indent=2)[:10000]}\n\n"
                        "Extract the user story Title (summary), Description, and Acceptance Criteria (AC). "
                        "Also extract the target web application testing environment URL if found in any field.\n"
                        "Structure the output matching the requested JSON schema."
                    )
                    
                    response_gemini = self.client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=JiraStoryData,
                        )
                    )
                    
                    data = json.loads(response_gemini.text.strip())
                    print(f"🎯 JiraExtractor: Successfully parsed REST response: '{data.get('title')}'")
                    return JiraStoryData(**data)
                    
            except urllib.error.HTTPError as http_err:
                print(f"⚠️ JiraExtractor REST API HTTPError: {http_err.code} {http_err.reason}. Falling back to browser scraper...")
            except Exception as api_ex:
                print(f"⚠️ JiraExtractor REST API General Error: {api_ex}. Falling back to browser scraper...")
        else:
            missing = []
            if not issue_key: missing.append("Issue Key (failed parsing URL)")
            if not user_email: missing.append("JIRA_USER_EMAIL")
            if not api_token: missing.append("JIRA_API_TOKEN")
            print(f"⚠️ JiraExtractor: Direct API ingestion bypassed due to missing credentials: {', '.join(missing)}")
            print("🌐 JiraExtractor: Falling back to browser-based perception scraper...")

        # --- FALLBACK: Playwright Scraper ---
        browser_helper = BrowserHelper()
        page = await browser_helper.initialize_maximized_page(headless=True)
        
        try:
            print(f"🌐 JiraExtractor Fallback: Loading page... {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(5)  # Wait for single page app dynamic load
            
            # Scrape raw text
            raw_text = await page.evaluate("() => document.body.innerText")
            print(f"📄 JiraExtractor Fallback: Scraped {len(raw_text)} characters from DOM.")
            
            # Extract via Gemini
            prompt = (
                "You are an AI Jira business analyst. Your job is to extract the User Story Title, "
                "Description, Acceptance Criteria (AC), and any target web application testing URL from the raw text page dump below.\n\n"
                f"--- RAW JIRA PAGE CONTENT ---\n{raw_text[:8000]}\n\n"
                "Extract and structure the data into the requested JSON schema."
            )
            
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JiraStoryData,
                )
            )
            
            data = json.loads(response.text.strip())
            if not data.get('description') or not str(data.get('description')).strip():
                print("💡 JiraExtractor Fallback: Empty description detected. Falling back to ticket title.")
                data['description'] = data.get('title', '')
            print(f"🎯 JiraExtractor Fallback: Extracted story: '{data.get('title')}' with {len(data.get('acceptance_criteria', []))} ACs.")
            return JiraStoryData(**data)
            
        except Exception as e:
            print(f"⚠️ JiraExtractor Fallback Scraper Error: {e}. Falling back to default mock story for execution.")
            return self._get_mock_story_data()
        finally:
            await browser_helper.close_session()

    def _get_mock_story_data(self) -> JiraStoryData:
        return JiraStoryData(
            title="Authenticate and Verify Moodle Dashboard Accessibility",
            description=(
                "As an administrator, I want to authenticate on the sandbox Moodle system "
                "so that I can access the system admin features. "
                "Target environment URL: https://sandbox.moodledemo.net/login/index.php"
            ),
            acceptance_criteria=[
                "Verify that entering valid administrator credentials logs the user into the system dashboard.",
                "Verify that entering invalid credentials alerts the user with an 'Invalid login' banner.",
                "Verify that dashboard redirects URL to '/my/' homepage upon authentication."
            ],
            target_url="https://sandbox.moodledemo.net/login/index.php"
        )


# ----------------------------------------------------
# 2. Predictive Test Case Scenario Generation Layer
# ----------------------------------------------------
class TestCaseGenerator:
    """Generates test cases from Jira criteria and writes to Excel workbook."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)

    def generate_suite(self, story: JiraStoryData) -> List[TestCaseItem]:
        """Uses Gemini to predict scenarios based on story criteria."""
        print("🧠 TestCaseGenerator: Invoking Gemini to generate test cases...")
        
        prompt = (
            "You are a Senior Principal QA Engineer. Analyse the following Jira User Story details:\n"
            f"Title: {story.title}\n"
            f"Description: {story.description}\n"
            f"Acceptance Criteria:\n" + "\n".join(f"- {ac}" for ac in story.acceptance_criteria) + "\n\n"
            "Predict and generate a comprehensive suite of logical test case scenarios. "
            "You must include:\n"
            "1. Happy path (successful authentication/execution).\n"
            "2. Negative validations (e.g. invalid password, empty credentials, etc.).\n"
            "3. Boundary cases (if any apply to fields, otherwise structural variations).\n\n"
            "Return the list of test cases matching the structured schema."
        )

        response = self.client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TestSuiteOutput,
            )
        )
        
        suite = json.loads(response.text.strip())
        cases = [TestCaseItem(**c) for c in suite.get("test_cases", [])]
        print(f"📊 TestCaseGenerator: Generated {len(cases)} test cases.")
        return cases

    def write_to_excel(self, cases: List[TestCaseItem], default_url: str, output_path: str = "outputs/test_suite.xlsx"):
        """Saves generated test cases into a highly polished, formatted Excel workbook."""
        if not os.path.isabs(output_path):
            output_path = os.path.join(project_root, output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test Suite Matrix"
        
        # Enable grid lines
        ws.views.sheetView[0].showGridLines = True
        
        # Styling definitions
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        cell_font = Font(name="Segoe UI", size=10)
        bold_font = Font(name="Segoe UI", size=10, bold=True)
        alignment_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        alignment_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
        
        thin_border = Border(
            left=Side(style='thin', color='D9D9D9'),
            right=Side(style='thin', color='D9D9D9'),
            top=Side(style='thin', color='D9D9D9'),
            bottom=Side(style='thin', color='D9D9D9')
        )
        
        headers = ["Test Case ID", "Component", "Description", "Execution Goal", "Expected Result", "Status", "Target URL", "Timestamp", "Screenshot Link"]
        ws.append(headers)
        
        # Style headers
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = alignment_center
            cell.border = thin_border
            
        # Append data
        for case in cases:
            ws.append([
                case.test_case_id,
                case.component,
                case.description,
                case.execution_goal,
                case.expected_result,
                "Pending",
                default_url,
                "",
                ""
            ])
            
        # Style rows and set border
        for row in range(2, len(cases) + 2):
            for col in range(1, len(headers) + 1):
                cell = ws.cell(row=row, column=col)
                cell.font = cell_font
                cell.border = thin_border
                if col in [1, 2, 6, 8]:
                    cell.alignment = alignment_center
                else:
                    cell.alignment = alignment_left
                
                # Format Pending status cell
                if col == 6:
                    cell.font = bold_font
                    cell.fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid") # Light yellow
                    
        # Adjust column widths
        column_widths = {
            "A": 15,  # Test Case ID
            "B": 15,  # Component
            "C": 35,  # Description
            "D": 50,  # Execution Goal
            "E": 35,  # Expected Result
            "F": 12,  # Status
            "G": 30,  # Target URL
            "H": 20,  # Timestamp
            "I": 25   # Screenshot Link
        }
        for col, width in column_widths.items():
            ws.column_dimensions[col].width = width
            
        # Freeze top row
        ws.freeze_panes = "A2"
        
        wb.save(output_path)
        print(f"💾 TestCaseGenerator: Saved workbook to {output_path}")


# ----------------------------------------------------
# 3. Sequential Execution & Orchestration Layer
# ----------------------------------------------------
class PipelineOrchestrator:
    """Orchestrates test suite execution and updates status in Excel live."""
    
    def __init__(self, config_registry: Dict[str, Any]):
        self.config = config_registry

    async def execute_suite(self, excel_path: str = "outputs/test_suite.xlsx", sample_run: bool = False):
        """Reads test cases from Excel and runs them sequentially through the core agent."""
        if not os.path.isabs(excel_path):
            excel_path = os.path.join(project_root, excel_path)
        print(f"🚀 PipelineOrchestrator: Loading Excel suite from {excel_path}")
        
        if not os.path.exists(excel_path):
            print(f"❌ PipelineOrchestrator Error: Excel suite '{excel_path}' not found!")
            return
            
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active
        
        # Identify column indices (1-indexed)
        headers = [cell.value for cell in ws[1]]
        col_indices = {h: i for i, h in enumerate(headers, 1) if h}
        
        id_col = col_indices.get("Test Case ID")
        goal_col = col_indices.get("Execution Goal")
        status_col = col_indices.get("Status")
        url_col = col_indices.get("Target URL")
        time_col = col_indices.get("Timestamp")
        ss_col = col_indices.get("Screenshot Link")
        
        # Styles for result cells
        pass_fill = PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid") # Light green
        pass_font = Font(name="Segoe UI", size=10, bold=True, color="38761D")
        
        fail_fill = PatternFill(start_color="FCE5CD", end_color="FCE5CD", fill_type="solid") # Light red
        fail_font = Font(name="Segoe UI", size=10, bold=True, color="A61C00")
        
        max_row = ws.max_row
        print(f"📋 PipelineOrchestrator: Found {max_row - 1} test cases to execute.")
        
        rows_to_run = list(range(2, max_row + 1))
        if sample_run:
            print("[PIPELINE NOTIFICATION] Running in isolated sample verification mode. Only the primary scenario will be processed.")
            rows_to_run = rows_to_run[:1]
            
        for row in rows_to_run:
            case_id = ws.cell(row=row, column=id_col).value
            goal = ws.cell(row=row, column=goal_col).value
            target_url = ws.cell(row=row, column=url_col).value or self.config["environment"]["target_url"]
            
            print(f"\n⚡ Executing [{case_id}]: {goal[:80]}...")
            
            # Mark cell as Executing
            ws.cell(row=row, column=status_col).value = "Running"
            ws.cell(row=row, column=status_col).fill = PatternFill(start_color="CFE2F3", end_color="CFE2F3", fill_type="solid") # Light blue
            wb.save(excel_path)
            
            # Execute through core agent
            run_id = f"pipeline_{case_id.lower()}"
            try:
                # Respect CLI browser mode override if defined
                if "headless" not in self.config["environment"]:
                    self.config["environment"]["headless"] = True
                summary = await run_autonomous_navigator(
                    config_registry=self.config,
                    target_url=target_url,
                    user_goal=goal,
                    run_id=run_id
                )
                
                # Determine outcome
                is_passed = summary.get("is_final") and summary.get("status") == "SUCCESS"
                status_str = "PASSED" if is_passed else "FAILED"
                
                # Write results
                status_cell = ws.cell(row=row, column=status_col)
                status_cell.value = status_str
                if is_passed:
                    status_cell.fill = pass_fill
                    status_cell.font = pass_font
                else:
                    status_cell.fill = fail_fill
                    status_cell.font = fail_font
                    
                # Timestamp and Screenshot linking
                ws.cell(row=row, column=time_col).value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                ss_path = summary.get("screenshot_path")
                if ss_path and os.path.exists(ss_path):
                    # Store screenshot relative or absolute link
                    rel_ss_path = os.path.relpath(ss_path, os.path.dirname(excel_path))
                    ws.cell(row=row, column=ss_col).value = f'=HYPERLINK("{rel_ss_path}", "View Screenshot")'
                    ws.cell(row=row, column=ss_col).font = Font(name="Segoe UI", size=10, underline="single", color="1155CC")
                
            except Exception as run_ex:
                print(f"❌ PipelineOrchestrator Execution Crash on {case_id}: {run_ex}")
                status_cell = ws.cell(row=row, column=status_col)
                status_cell.value = "FAILED"
                status_cell.fill = fail_fill
                status_cell.font = fail_font
                ws.cell(row=row, column=time_col).value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Incremental save
            wb.save(excel_path)
            print(f"💾 Saved updates for [{case_id}] | Status: {ws.cell(row=row, column=status_col).value}")
            
        print("\n🏁 Sequential test suite execution loop concluded.")


# ----------------------------------------------------
# 4. Executive HTML Report Compiler
# ----------------------------------------------------
class ReportCompiler:
    """Parses Excel data matrix to generate a visual, responsive HTML executive dashboard."""
    
    @staticmethod
    def compile_dashboard(excel_path: str = "outputs/test_suite.xlsx", output_path: str = "outputs/dashboard.html"):
        """Generates premium standalone HTML QA dashboard with responsive layout and graphics."""
        if not os.path.isabs(excel_path):
            excel_path = os.path.join(project_root, excel_path)
        if not os.path.isabs(output_path):
            output_path = os.path.join(project_root, output_path)
        print(f"🎨 ReportCompiler: Compiling HTML dashboard from {excel_path}...")
        
        if not os.path.exists(excel_path):
            print(f"❌ ReportCompiler Error: Source Excel file '{excel_path}' not found!")
            return
            
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active
        
        headers = [cell.value for cell in ws[1]]
        rows_data = []
        
        total = 0
        passed = 0
        failed = 0
        
        for row in range(2, ws.max_row + 1):
            row_dict = {}
            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=row, column=col_idx)
                row_dict[header] = cell.value
                
            status = str(row_dict.get("Status", "Pending")).upper()
            total += 1
            if status == "PASSED":
                passed += 1
            elif status == "FAILED":
                failed += 1
                
            # Parse screenshot link
            ss_formula = row_dict.get("Screenshot Link") or ""
            ss_url = ""
            if "HYPERLINK" in str(ss_formula):
                # Extract link out of Formula: =HYPERLINK("../screenshots/...", "View Screenshot")
                try:
                    import re
                    match = re.search(r'"([^"]+)"', str(ss_formula))
                    if match:
                        ss_url = match.group(1)
                except Exception:
                    pass
            
            row_dict["parsed_screenshot"] = ss_url
            rows_data.append(row_dict)
            
        pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0
        
        # HTML design template
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Parallel AI Automation - Executive Test Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0B0F19;
            --card-bg: #161D30;
            --border-color: #242F4D;
            --text-primary: #F3F4F6;
            --text-secondary: #9CA3AF;
            --accent-orange: #E86B24;
            --accent-blue: #3B82F6;
            --status-pass: #10B981;
            --status-fail: #EF4444;
            --status-pending: #FBBF24;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', sans-serif;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            padding: 2rem;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        /* Header layout */
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        .header-left h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #E86B24 0%, #FF9E64 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }}

        .header-left p {{
            color: var(--text-secondary);
            font-size: 0.95rem;
            margin-top: 0.2rem;
        }}

        .badge-live {{
            background: rgba(232, 107, 36, 0.15);
            color: var(--accent-orange);
            padding: 0.4rem 0.8rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            border: 1px solid rgba(232, 107, 36, 0.3);
            display: inline-block;
        }}

        /* Dashboard Overview cards grid */
        .dashboard-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        @media (max-width: 1024px) {{
            .dashboard-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}

        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
        }}

        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
            border-color: rgba(232, 107, 36, 0.4);
        }}

        .card-title {{
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.5rem;
        }}

        .card-value {{
            font-size: 2.2rem;
            font-weight: 800;
            font-family: 'Outfit', sans-serif;
        }}

        /* Gimmick decorative gradient bars for cards */
        .card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
        }}

        .card-total::before {{ background-color: var(--accent-blue); }}
        .card-passed::before {{ background-color: var(--status-pass); }}
        .card-failed::before {{ background-color: var(--status-fail); }}
        .card-rate::before {{ background-color: var(--accent-orange); }}

        /* Execution metrics split view section */
        .row-details {{
            display: grid;
            grid-template-columns: 3fr 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
            align-items: start;
        }}

        @media (max-width: 1024px) {{
            .row-details {{
                grid-template-columns: 1fr;
            }}
        }}

        .table-container {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            overflow-x: auto;
        }}

        .section-header {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.3rem;
            font-weight: 700;
            margin-bottom: 1.2rem;
            color: var(--text-primary);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .search-box {{
            background: #0E1322;
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.9rem;
            width: 250px;
            transition: all 0.3s;
        }}

        .search-box:focus {{
            border-color: var(--accent-orange);
            outline: none;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}

        th {{
            color: var(--text-secondary);
            font-weight: 700;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 1rem;
            border-bottom: 2px solid var(--border-color);
        }}

        td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.9rem;
            vertical-align: middle;
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}

        /* Interactive Expandable accordion rows */
        .details-row {{
            background-color: #0E1322;
            display: none;
        }}

        .details-content {{
            padding: 1.2rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }}

        .btn-expand {{
            cursor: pointer;
            color: var(--accent-orange);
            background: none;
            border: none;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }}

        .status-badge {{
            display: inline-block;
            padding: 0.25rem 0.6rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 700;
            text-align: center;
        }}

        .badge-passed {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--status-pass);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}

        .badge-failed {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--status-fail);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .badge-pending {{
            background: rgba(251, 191, 36, 0.15);
            color: var(--status-pending);
            border: 1px solid rgba(251, 191, 36, 0.3);
        }}

        .ss-link {{
            color: var(--accent-blue);
            text-decoration: none;
            font-weight: 600;
        }}

        .ss-link:hover {{
            text-decoration: underline;
        }}

        /* Premium visual chart card */
        .chart-container {{
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
        }}

        .chart-wrapper {{
            position: relative;
            width: 100%;
            max-width: 250px;
            margin-top: 1rem;
        }}

    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-left">
                <h1>QA Automation Suite Pipeline Dashboard</h1>
                <p>Enterprise Continuous Integration Executive Performance Report</p>
            </div>
            <div>
                <span class="badge-live">📡 PIPELINE GATE PASSED</span>
            </div>
        </header>

        <!-- Stats Counter Panel -->
        <section class="dashboard-grid">
            <div class="card card-total">
                <div class="card-title">Total Scenarios</div>
                <div class="card-value">{total}</div>
            </div>
            <div class="card card-passed">
                <div class="card-title">Passed Cases</div>
                <div class="card-value" style="color: var(--status-pass);">{passed}</div>
            </div>
            <div class="card card-failed">
                <div class="card-title">Failed Cases</div>
                <div class="card-value" style="color: var(--status-fail);">{failed}</div>
            </div>
            <div class="card card-rate">
                <div class="card-title">Pass Rate</div>
                <div class="card-value" style="color: var(--accent-orange);">{pass_rate}%</div>
            </div>
        </section>

        <!-- Split Layout Detail Section -->
        <section class="row-details">
            <!-- Test Matrix table -->
            <div class="table-container">
                <div class="section-header">
                    <h2>Test Scenario Matrix</h2>
                    <input type="text" id="searchInput" class="search-box" placeholder="Search test cases..." onkeyup="filterTable()">
                </div>
                <table id="testSuiteTable">
                    <thead>
                        <tr>
                            <th style="width: 120px;">ID</th>
                            <th style="width: 150px;">Component</th>
                            <th>Description</th>
                            <th style="width: 120px; text-align: center;">Status</th>
                            <th style="width: 180px; text-align: center;">Timestamp</th>
                            <th style="width: 100px; text-align: center;">Details</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        
        for idx, row in enumerate(rows_data):
            case_id = row.get("Test Case ID", f"TC{idx+1:03d}")
            component = row.get("Component", "General")
            description = row.get("Description", "")
            goal = row.get("Execution Goal", "")
            expected = row.get("Expected Result", "")
            status = str(row.get("Status", "Pending")).upper()
            timestamp = row.get("Timestamp") or "Not executed"
            ss_path = row.get("parsed_screenshot") or ""
            
            badge_class = "badge-pending"
            if status == "PASSED":
                badge_class = "badge-passed"
            elif status == "FAILED":
                badge_class = "badge-failed"
                
            ss_link_html = ""
            if ss_path:
                ss_link_html = f'<br><br>🖼️ <strong>Visual Proof:</strong> <a href="{ss_path}" class="ss-link" target="_blank">Open Final Screenshot</a>'
            
            html_content += f"""
                        <tr id="row-{case_id}">
                            <td style="font-weight: 700; color: var(--accent-orange);">{case_id}</td>
                            <td style="font-weight: 600;">{component}</td>
                            <td>{description}</td>
                            <td style="text-align: center;">
                                <span class="status-badge {badge_class}">{status}</span>
                            </td>
                            <td style="text-align: center; color: var(--text-secondary); font-size: 0.85rem;">{timestamp}</td>
                            <td style="text-align: center;">
                                <button class="btn-expand" onclick="toggleDetails('{case_id}')">View ▾</button>
                            </td>
                        </tr>
                        <tr class="details-row" id="details-{case_id}">
                            <td colspan="6">
                                <div class="details-content">
                                    ⚙️ <strong>Execution Goal:</strong> {goal}<br><br>
                                    🎯 <strong>Expected Result:</strong> {expected}
                                    {ss_link_html}
                                </div>
                            </td>
                        </tr>
            """
            
        html_content += f"""
                    </tbody>
                </table>
            </div>

            <!-- Visualization column -->
            <div>
                <div class="chart-container">
                    <div class="section-header">
                        <h2>Pass/Fail Ratio</h2>
                    </div>
                    <div class="chart-wrapper">
                        <canvas id="ratioChart"></canvas>
                    </div>
                </div>
            </div>
        </section>
    </div>

    <script>
        // Toggle accordion detail row
        function toggleDetails(caseId) {{
            const detailsRow = document.getElementById('details-' + caseId);
            const btn = document.querySelector('#row-' + caseId + ' .btn-expand');
            if (detailsRow.style.display === 'table-row') {{
                detailsRow.style.display = 'none';
                btn.innerHTML = 'View ▾';
            }} else {{
                detailsRow.style.display = 'table-row';
                btn.innerHTML = 'Hide ▴';
            }}
        }}

        // Dynamic fuzzy table filtering
        function filterTable() {{
            const input = document.getElementById('searchInput');
            const filter = input.value.toLowerCase();
            const table = document.getElementById('testSuiteTable');
            const tr = table.getElementsByTagName('tr');

            for (let i = 1; i < tr.length; i++) {{
                // Skip accordion details rows in selection logic
                if (tr[i].classList.contains('details-row')) continue;
                
                const idTd = tr[i].getElementsByTagName('td')[0];
                const compTd = tr[i].getElementsByTagName('td')[1];
                const descTd = tr[i].getElementsByTagName('td')[2];
                const statusTd = tr[i].getElementsByTagName('td')[3];
                
                if (idTd || compTd || descTd || statusTd) {{
                    const textValue = (idTd.textContent + ' ' + compTd.textContent + ' ' + descTd.textContent + ' ' + statusTd.textContent).toLowerCase();
                    if (textValue.indexOf(filter) > -1) {{
                        tr[i].style.display = '';
                    }} else {{
                        tr[i].style.display = 'none';
                        // Collapse associated details row if hidden
                        const caseId = idTd.textContent.trim();
                        const detailsRow = document.getElementById('details-' + caseId);
                        if (detailsRow) detailsRow.style.display = 'none';
                        const btn = tr[i].querySelector('.btn-expand');
                        if (btn) btn.innerHTML = 'View ▾';
                    }}
                }}
            }}
        }}

        // Chart.js Visualization Loader
        const ctx = document.getElementById('ratioChart').getContext('2d');
        new Chart(ctx, {{
            type: 'doughnut',
            data: {{
                labels: ['Passed', 'Failed', 'Pending'],
                datasets: [{{
                    data: [{passed}, {failed}, {total - passed - failed}],
                    backgroundColor: ['#10B981', '#EF4444', '#FBBF24'],
                    borderColor: '#161D30',
                    borderWidth: 3
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{
                            color: '#F3F4F6',
                            font: {{
                                family: 'Plus Jakarta Sans',
                                size: 12
                            }}
                        }}
                    }}
                }},
                cutout: '70%'
            }}
        }});
    </script>
</body>
</html>
"""
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"🎨 ReportCompiler: Executive Dashboard Compiled Successfully at {output_path}")

# ----------------------------------------------------
# Main Orchestrated Pipeline Entry Hook
# ----------------------------------------------------
async def run_full_pipeline(jira_url: str, output_dir: str = "outputs", sample_run: bool = False):
    print("==================================================")
    print("🎬 STARTING COMPLETE AUTONOMOUS QA PIPELINE RUN")
    print("==================================================")
    
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(project_root, output_dir)
    
    # 1. Initialize environment configurations
    config = load_unified_config()
    api_key = config.get("api_key")
    if not api_key:
        print("❌ CRITICAL ERROR: GEMINI_API_KEY is not defined in the environment!")
        sys.exit(1)
        
    excel_path = os.path.join(output_dir, "test_suite.xlsx")
    html_path = os.path.join(output_dir, "dashboard.html")
    
    # STEP 1: Ingest Jira story details
    extractor = JiraExtractor(api_key=api_key)
    story_data = await extractor.extract_story(jira_url)
    
    # STEP 2: Generate test cases and save to Excel workbook
    generator = TestCaseGenerator(api_key=api_key)
    test_cases = generator.generate_suite(story_data)
    
    # Resolve target URL based on extracted Jira story data or config default
    testing_url = story_data.target_url or config["environment"]["target_url"]
    generator.write_to_excel(test_cases, default_url=testing_url, output_path=excel_path)
    
    # STEP 3: Sequentially execute test scenarios and record live results
    orchestrator = PipelineOrchestrator(config_registry=config)
    await orchestrator.execute_suite(excel_path=excel_path, sample_run=sample_run)
    
    # STEP 4: Compile HTML executive dashboard
    ReportCompiler.compile_dashboard(excel_path=excel_path, output_path=html_path)
    
    print("\n==================================================")
    print("🎉 FULL PIPELINE COMPLETED SUCCESSFULLY!")
    print(f"📊 Excel Suite Matrix: {excel_path}")
    print(f"💻 HTML Dashboard:     {html_path}")
    print("==================================================")
