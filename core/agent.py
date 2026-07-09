import sys
import json
import asyncio
import os

# Append the project root to sys.path to resolve core and utils modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Reconfigure stdout/stderr to UTF-8 for safe emoji and Unicode rendering on Windows if supported
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from faker import Faker
from pydantic import BaseModel, Field
from utils.browser_helper import BrowserHelper

class ElementInteraction(BaseModel):
    action: str = Field(description="The action to perform: 'click', 'type', 'select', or 'wait'.")
    selector: Optional[str] = Field(None, description="The CSS selector or text matcher of the target element.")
    text_to_type: Optional[str] = Field(None, description="The text to type if action is 'type'.")
    value_to_select: Optional[str] = Field(None, description="The value to select if action is 'select'.")
    wait_time_ms: Optional[int] = Field(None, description="Optional sleep duration in milliseconds after this action.")

class AgentAction(BaseModel):
    thought: str = Field(description="Step-by-step reasoning for the proposed sequence.")
    actions: list[ElementInteraction] = Field(default=[], description="The sequential list of interactions to perform in this step.")
    action: Optional[str] = Field(None, description="Legacy single action field.")
    selector: Optional[str] = Field(None, description="Legacy target selector field.")
    text_to_type: Optional[str] = Field(None, description="Legacy text to type field.")
    value_to_select: Optional[str] = Field(None, description="Legacy value to select field.")
    is_final: bool = Field(description="Set to true only when the ultimate objective is fully completed.")

# Initialize environment variables safely from .env
load_dotenv()

# Initialize the Faker data generation engine natively
fake = Faker()


def load_unified_config():
    """Consolidates the standardized config schema and maps the secure API layer."""
    # Move up one level from core/ to Agentic_AI/ root, then look inside config/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "config.json")

    try:
        with open(config_path, "r") as f:
            runtime_config = json.load(f)
    except FileNotFoundError:
        print("❌ CRITICAL: Standardized config.json is missing from the config/ directory!")
        sys.exit(1)

    # Resolve Target URL (CLI argument takes absolute priority over default_url if valid URL)
    cli_url = None
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("http://") or arg.startswith("https://"):
                cli_url = arg
                break

    if cli_url:
        runtime_config["environment"]["target_url"] = cli_url
    else:
        runtime_config["environment"]["target_url"] = runtime_config["environment"]["default_url"]

    runtime_config["api_key"] = os.getenv("GEMINI_API_KEY")
    return runtime_config


def load_system_instructions():
    """Reads the core prompt rules from the subfolder text file."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    instructions_path = os.path.join(base_dir, "prompts", "system_instructions.txt")
    try:
        with open(instructions_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return "Return a valid JSON instruction for QA automation."


def generate_dynamic_test_data():
    """
    Industry-Standard Synthetic Data Engine.
    Generates a randomized payload on the fly to fulfill form constraints without static maintenance.
    """
    first_name = fake.first_name()
    last_name = fake.last_name()
    base_email = f"{first_name.lower()}.{last_name.lower()}@{fake.free_email_domain()}"

    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "email": base_email,
        "work_email": f"work.{first_name.lower()}.{last_name.lower()}@optimworks.com",
        "personal_email": f"personal.{first_name.lower()}.{last_name.lower()}@example.com",
        "company": fake.company(),
        "job_title": fake.job(),
        "phone_number": f"9{fake.msisdn()[:9]}",  # Generates a realistic 10-digit number
        "city": fake.city(),
        "street_address": fake.street_address(),
        "zip_code": fake.zipcode(),
        "text_memo": fake.paragraph(nb_sentences=3)
    }


def extract_json_block(text: str) -> str:
    """Extracts JSON block cleanly by removing markdown fences or leading/trailing text."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part_clean = part.strip()
            if part_clean.startswith("json"):
                part_clean = part_clean[4:].strip()
            if part_clean.startswith("{") and part_clean.endswith("}"):
                return part_clean

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx:end_idx + 1]

    return text


async def detect_validation_errors(page) -> Optional[str]:
    """
    Scrapes the active page for application-side validation banners, alert dialogs,
    error divs, invalid field messages, or duplicate entry constraint rejections.
    """
    if not page:
        return None
    try:
        return await page.evaluate("""() => {
            const selectors = [
                '.alert-danger', '.alert-error', '.error-message', '.error-text', 
                '.validation-error', '.invalid-feedback', '[role="alert"]', 
                '.error', '.danger', '.text-danger', '.alert', '.notification-danger',
                '#error-message', '#validation-errors', '.field-validation-error',
                '.error-summary', '.validation-summary-errors'
            ];
            let errors = [];
            
            // 1. Selector-based scanning
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.innerText ? el.innerText.trim() : '';
                    if (text && el.offsetWidth > 0 && el.offsetHeight > 0) {
                        if (!errors.includes(text)) {
                            errors.push(text);
                        }
                    }
                });
            });
            
            // 2. Custom visual style-based and wildcard red-text scanning
            document.querySelectorAll('span, div, p, label, b, i, strong').forEach(el => {
                const text = el.innerText ? el.innerText.trim() : '';
                if (text && text.length > 3 && el.offsetWidth > 0 && el.offsetHeight > 0) {
                    const style = window.getComputedStyle(el);
                    const color = style.color || '';
                    
                    const isReddish = color.includes('rgb(23') || 
                                      color.includes('rgb(22') || 
                                      color.includes('rgb(24') || 
                                      color.includes('rgb(25') || 
                                      color.includes('red') || 
                                      color.includes('orange') || 
                                      color.includes('rgb(21') || 
                                      color.includes('rgb(180') || 
                                      color.includes('rgb(204');
                                      
                    const hasErrorWords = text.toLowerCase().includes('error') || 
                                          text.toLowerCase().includes('invalid') || 
                                          text.toLowerCase().includes('already exists') || 
                                          text.toLowerCase().includes('cannot be') || 
                                          text.toLowerCase().includes('must be') || 
                                          text.toLowerCase().includes('check the') || 
                                          text.toLowerCase().includes('required') || 
                                          text.startsWith('*');
                                          
                    if (isReddish && hasErrorWords) {
                        if (!errors.includes(text)) {
                            errors.push(text);
                        }
                    }
                }
            });
            
            // 3. Check HTML5 validationMessages
            const inputs = document.querySelectorAll('input, select, textarea');
            inputs.forEach(el => {
                if (el.validationMessage && el.offsetWidth > 0 && el.offsetHeight > 0) {
                    errors.push(`Field '${el.name || el.id || el.placeholder}': ${el.validationMessage}`);
                }
                if (el.getAttribute('aria-invalid') === 'true') {
                    errors.push(`Field '${el.name || el.id || el.placeholder}' is marked invalid.`);
                }
            });
            
            return errors.length > 0 ? errors.join('; ') : null;
        }""")
    except Exception as e:
        print(f"⚠️ Error while parsing page validation errors: {e}")
        return None


async def run_autonomous_navigator(config_registry, target_url, user_goal, run_id="default_run", log_callback=None):
    def log(msg):
        formatted = f"[{run_id}] {msg}"
        print(formatted)
        if log_callback:
            log_callback(msg)

    log(f"🚀 Launching Dynamic Autonomous QA Engine for {run_id}...")

    if not config_registry.get("api_key"):
        log("❌ CRITICAL ERROR: GEMINI_API_KEY not found in .env file! Exiting.")
        sys.exit(1)

    ai_client = genai.Client(api_key=config_registry["api_key"])
    browser_engine = BrowserHelper()
    system_prompt = load_system_instructions()

    max_steps = config_registry["environment"].get("max_retry_steps", 8)

    # Instantiate today's fresh dynamic dataset
    dynamic_payload = generate_dynamic_test_data()
    log("🎲 DYNAMIC TEST DATA ASSET INSTANTIATED:")
    log(json.dumps(dynamic_payload, indent=2))
    log("--------------------------------------------------")

    # Initialize an execution memory matrix to maintain run context
    execution_history = []
    import time
    start_time = time.time()

    try:
        headless_mode = config_registry.get("environment", {}).get("headless", False)
        page = await browser_engine.initialize_maximized_page(headless=headless_mode)
        log(f"🌐 Driving navigation to target application: {target_url}")
        try:
            # Ensure this is actively hit right after the logs initialize with network settle threshold
            await page.goto(target_url, wait_until="networkidle", timeout=15000)
        except Exception as e_nav:
            log(f"⚠️ Navigation settle threshold bypassed: {e_nav}. Proceeding with current page state.")

        is_final = False
        step = 0

        while not is_final and step < max_steps:
            log(f"\n--- 🧠 Agent Dynamically Analyzing Step {step + 1} ---")

            # 1. Scrape deep layout parameters
            live_elements = await browser_engine.extract_interactive_elements()

            # Detect any validation error messages on the page
            validation_error = await detect_validation_errors(page)
            if validation_error:
                log(f"⚠️ SELF-HEALING: Validation/rejection error detected on page: {validation_error}")
                # Dynamically regenerate alternative data parameters using Faker
                log("🎲 SELF-HEALING: Re-generating alternative synthetic data parameters...")
                dynamic_payload = generate_dynamic_test_data()
                log("🎲 NEW DYNAMIC TEST DATA ASSET INSTANTIATED:")
                log(json.dumps(dynamic_payload, indent=2))

            # 2. Build context payload, injecting history tracking layer and error context if present
            error_injection = ""
            if validation_error:
                error_injection = (
                    f"--- RUNTIME ERROR / VALIDATION REJECTION ENCOUNTERED ---\n"
                    f"The application has rejected the input or submission with the following error:\n"
                    f"\"{validation_error}\"\n\n"
                    f"Action Required:\n"
                    f"1. Clear and re-fill the conflicting field with updated values from the refreshed \"SYNTHETIC DATA POOL\" below.\n"
                    f"2. Use the refreshed dynamic fields to avoid duplicate or validation constraint issues.\n"
                    f"3. Click the submit/add button to re-attempt submission.\n\n"
                )

            context_payload = (
                f"Your Ultimate High-Level Objective: '{user_goal}'\n\n"
                f"{error_injection}"
                f"--- RUNTIME MEMORY LOGS ---\n"
                f"Actions You Have Already Executed in This Session:\n"
                f"{json.dumps(execution_history, indent=2) if execution_history else 'None. This is step 1.'}\n\n"
                f"--- STATIC CREDENTIALS ---\n"
                f"Use the credentials below if the page asks you to log in or authenticate:\n"
                f"{json.dumps(config_registry.get('test_data', {}), indent=2)}\n\n"
                f"--- SYNTHETIC DATA POOL ---\n"
                f"Use fields below to fill out user/profile registration forms dynamically:\n"
                f"{json.dumps(dynamic_payload, indent=2)}\n\n"
                f"--- CURRENT SCREEN VIEW ---\n"
                f"Live Actionable Elements Visible Right Now:\n"
                f"{json.dumps(live_elements, indent=2)}"
            )

            # 3. Process layout schema via the AI brain (with exponential backoff retries)
            log("📡 Sending layout matrix and memory history to AI brain...")
            response = None
            for attempt in range(5):
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-flash-lite-latest',
                        contents=context_payload,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            response_mime_type="application/json",
                            response_schema=AgentAction,
                        )
                    )
                    break
                except Exception as ex:
                    log(f"⚠️ API Call failed (attempt {attempt + 1}/5): {ex}")
                    if attempt < 4:
                        if "429" in str(ex) or "RESOURCE_EXHAUSTED" in str(ex):
                            import re
                            match = re.search(r"retry in ([\d\.]+)s", str(ex))
                            sleep_time = float(match.group(1)) + 2.0 if match else 60.0
                            log(f"⏳ Quota rate limit hit. Waiting {sleep_time:.2f} seconds before retrying...")
                        else:
                            sleep_time = 2 ** attempt
                            log(f"🔄 Retrying in {sleep_time} seconds...")
                        await asyncio.sleep(sleep_time)
                    else:
                        raise ex

            # --- SELF-HEALING PARSING LAYER ---
            raw_text = response.text.strip()
            cleaned_text = extract_json_block(raw_text)

            try:
                command = json.loads(cleaned_text)
            except json.JSONDecodeError:
                log(f"⚠️ Raw Parsing Failed. Cleaned output was:\n{cleaned_text}")
                log("🔄 Retrying current step due to formatting anomaly...")
                step += 1
                continue

            # Standardize alternative variation keys dynamically to prevent KeyErrors
            ai_thought = (
                command.get('thought') or 
                command.get('thoughts') or 
                command.get('reasoning') or 
                command.get('thought_process') or 
                "Executing interaction block..."
            )
            log(f"🤖 AI Thought: {ai_thought}")

            # Parse actions list (handle backward-compatibility fallback)
            actions_list = []
            raw_actions = command.get('actions')
            if isinstance(raw_actions, list) and len(raw_actions) > 0:
                actions_list = raw_actions
            else:
                # Check for single action fallback
                ai_action = str(command.get('action') or command.get('action_executed') or '').lower().strip()
                if ai_action:
                    actions_list = [{
                        "action": ai_action,
                        "selector": command.get('selector') or command.get('target_selector') or command.get('css_selector'),
                        "text_to_type": command.get('text_to_type') or command.get('text') or command.get('value'),
                        "value_to_select": command.get('value_to_select') or command.get('value') or command.get('text_to_type'),
                        "wait_time_ms": None
                    }]

            # 4. Execute the planned interactions sequentially
            log(f"🛠️ Sequence Executor: Processing {len(actions_list)} planned action(s)...")
            for idx, act in enumerate(actions_list):
                act_type = str(act.get('action', '')).lower().strip()
                act_selector = act.get('selector') or act.get('target_selector') or act.get('css_selector')
                act_text = act.get('text_to_type') or act.get('text') or act.get('value') or ''
                act_select_val = act.get('value_to_select') or act.get('value') or act.get('text_to_type') or ''
                act_wait = act.get('wait_time_ms')

                log(f"  [{idx + 1}/{len(actions_list)}] Action: {act_type.upper()} on selector '{act_selector}'")

                try:
                    if act_type == 'type':
                        await page.wait_for_selector(act_selector, state="visible", timeout=5000)
                        element = page.locator(act_selector)
                        await element.scroll_into_view_if_needed()
                        await element.focus()
                        await element.fill(act_text)
                        await page.keyboard.press("Tab") # Shift focus to trigger React change handlers
                        await asyncio.sleep(0.5) # Explicit wait to prevent React state propagation race conditions
                    elif act_type == 'click':
                        # Form Submission Safety Guard: check if this is the employee creation submit click
                        is_submit_click = (
                            'submit' in str(act_selector).lower() or 
                            'add' in str(act_selector).lower() or 
                            'save' in str(act_selector).lower() or
                            'button[type="submit"]' in str(act_selector)
                        )
                        has_employee_form = await page.locator("input[name='firstName']").count() > 0

                        if is_submit_click and has_employee_form:
                            log("🛡️ Form Submission Safety Guard: Ensuring all available form fields are filled...")
                            # 1. Locate all visible, enabled form fields
                            fields = await page.locator("input, select, textarea").all()
                            for field in fields:
                                if not (await field.is_visible() and await field.is_enabled()):
                                    continue
                                
                                tag_name = await field.evaluate("el => el.tagName")
                                current_val = await field.evaluate("el => el.value")
                                
                                # If already filled, skip
                                if current_val and current_val.strip():
                                    continue
                                    
                                name_attr = (await field.get_attribute("name") or "").lower()
                                id_attr = (await field.get_attribute("id") or "").lower()
                                placeholder_attr = (await field.get_attribute("placeholder") or "").lower()
                                target_key = f"{name_attr} {id_attr} {placeholder_attr}"
                                
                                # Match intents
                                value_to_fill = None
                                if "first" in target_key or "fname" in target_key:
                                    value_to_fill = dynamic_payload.get("first_name")
                                elif "last" in target_key or "lname" in target_key:
                                    value_to_fill = dynamic_payload.get("last_name")
                                elif "personal" in target_key:
                                    value_to_fill = dynamic_payload.get("personal_email")
                                elif "work" in target_key:
                                    value_to_fill = dynamic_payload.get("work_email")
                                elif "email" in target_key:
                                    value_to_fill = dynamic_payload.get("email")
                                elif "phone" in target_key or "mobile" in target_key or "number" in target_key:
                                    value_to_fill = dynamic_payload.get("phone_number")
                                elif "company" in target_key:
                                    value_to_fill = dynamic_payload.get("company")
                                elif "title" in target_key or "designation" in target_key:
                                    value_to_fill = dynamic_payload.get("job_title")
                                elif "city" in target_key or "location" in target_key:
                                    value_to_fill = dynamic_payload.get("city")
                                elif "address" in target_key:
                                    value_to_fill = dynamic_payload.get("street_address")
                                elif "zip" in target_key or "postal" in target_key:
                                    value_to_fill = dynamic_payload.get("zip_code")
                                elif "id" in target_key or "employee" in target_key:
                                    value_to_fill = f"EMP{fake.random_int(1000, 9999)}"
                                elif "password" in target_key:
                                    value_to_fill = "Password123!"
                                elif "dob" in target_key or "birth" in target_key:
                                    value_to_fill = "1995-05-15"
                                elif "date" in target_key or "joining" in target_key:
                                    value_to_fill = "2026-07-01"
                                elif "experience" in target_key:
                                    value_to_fill = "3"
                                elif "salary" in target_key:
                                    value_to_fill = "75000"
                                elif "uan" in target_key:
                                    value_to_fill = f"100{fake.random_int(100000000, 999999999)}"
                                elif "memo" in target_key or "note" in target_key or "description" in target_key:
                                    value_to_fill = dynamic_payload.get("text_memo")
                                
                                # 2. Fill the field sequentially with explicit wait
                                if tag_name == "SELECT":
                                    # Wait for select element
                                    await page.wait_for_selector(f"select[name='{name_attr}']" if name_attr else f"select#{id_attr}", state="visible", timeout=3000)
                                    options = await field.locator("option").all()
                                    for opt in options:
                                        opt_val = await opt.get_attribute("value")
                                        opt_text = await opt.inner_text()
                                        if opt_val and opt_val.strip() and opt_val.lower() != "select":
                                            await field.select_option(value=opt_val)
                                            log(f"    ⚙️ Auto-filled select field '{name_attr or id_attr}' with: {opt_text}")
                                            await page.keyboard.press("Escape")
                                            # Click away to close select overlay
                                            try:
                                                await page.mouse.click(10, 10)
                                            except Exception:
                                                pass
                                            await asyncio.sleep(0.5)
                                            break
                                elif tag_name in ["INPUT", "TEXTAREA"]:
                                    type_attr = (await field.get_attribute("type") or "text").lower()
                                    if type_attr in ["button", "submit", "checkbox", "radio", "file", "hidden"]:
                                        continue
                                    
                                    if not value_to_fill:
                                        value_to_fill = f"Test {name_attr or id_attr or 'Field'}"
                                    
                                    # Wait for input element
                                    selector_spec = f"input[name='{name_attr}']" if name_attr else (f"input#{id_attr}" if id_attr else None)
                                    if selector_spec:
                                        await page.wait_for_selector(selector_spec, state="visible", timeout=3000)
                                    
                                    await field.scroll_into_view_if_needed()
                                    await field.focus()
                                    await field.fill(value_to_fill)
                                    log(f"    ✍️ Auto-filled field '{name_attr or id_attr}' with: {value_to_fill}")
                                    
                                    # Dismiss calendar overlays
                                    if "date" in target_key or "dob" in target_key or "joining" in target_key:
                                        await page.keyboard.press("Escape")
                                        # Click away to close calendar overlay
                                        try:
                                            await page.mouse.click(10, 10)
                                        except Exception:
                                            pass
                                        await asyncio.sleep(0.5)
                            
                            log("🛡️ Form Submission Safety Guard: All available fields successfully populated.")

                        await page.wait_for_selector(act_selector, state="visible", timeout=5000)
                        await page.click(act_selector)
                        await page.wait_for_load_state("load")
                        await asyncio.sleep(2)
                    elif act_type == 'select':
                        log(f"    ⚙️ Selecting option '{act_select_val}'")
                        await page.wait_for_selector(act_selector, state="visible", timeout=5000)
                        element = page.locator(act_selector)
                        await element.scroll_into_view_if_needed()
                        await element.select_option(value=act_select_val)
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(0.5)
                    elif act_type == 'wait':
                        sleep_s = float(act_wait or 1000) / 1000.0
                        log(f"    ⏳ Sleeping for {sleep_s}s...")
                        await asyncio.sleep(sleep_s)

                    # Log this action into the running memory matrix
                    execution_history.append({
                        "step": step + 1,
                        "sub_step": idx + 1,
                        "action_executed": act_type,
                        "target_selector": act_selector
                    })

                    # If custom wait is specified, execute it
                    if act_wait and act_type != 'wait':
                        await asyncio.sleep(float(act_wait) / 1000.0)

                except Exception as e_act:
                    log(f"  ❌ Sequence Action failed: {e_act}")
                    log("  🔄 Stopping sequence execution early to allow self-healing re-analysis.")
                    break

            # Determine final status with variations supported
            is_final_raw = command.get('is_final') or command.get('final') or command.get('isFinal') or False
            is_final = str(is_final_raw).lower() in ('true', '1', 'yes') if not isinstance(is_final_raw, bool) else is_final_raw

            step += 1
            await asyncio.sleep(2)

        # --- OUTSIDE WHILE LOOP: SCREENSHOT AND REPORTING ---
        timestamp_s = int(time.time())
        os.makedirs("screenshots", exist_ok=True)
        screenshot_path = f"screenshots/run_{run_id}_step_{step}_{timestamp_s}.png"

        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            log(f"✅ Visual execution proof saved cleanly to: {screenshot_path}")
            
            # Maintain a duplicate copy at run_{run_id}_final.png for UI reference
            final_copy = f"screenshots/run_{run_id}_final.png"
            import shutil
            shutil.copy(screenshot_path, final_copy)
        except Exception as e_ss:
            log(f"⚠️ Failed to capture screenshot: {e_ss}")
            screenshot_path = None

        if is_final:
            log(f"🎉 SUCCESS: Concurrency run '{run_id}' form-filling execution milestone reached cleanly!")
        else:
            log(f"⚠️ WARNING: Concurrency run '{run_id}' completed without reaching the final milestone.")

        duration = round(time.time() - start_time, 2)
        summary = {
            "run_id": run_id,
            "target_url": target_url,
            "user_goal": user_goal,
            "total_steps": step,
            "status": "SUCCESS" if is_final else "FAILED/INCOMPLETE",
            "is_final": is_final,
            "duration_seconds": duration,
            "screenshot_path": f"screenshots/run_{run_id}_final.png" if os.path.exists(f"screenshots/run_{run_id}_final.png") else None
        }

        # Brief, professional QA executive summary
        log("\n==================================================")
        log("📊 TEST SUITE EXECUTION SUMMARY")
        log("==================================================")
        log(f"Target Goal:           {user_goal}")
        log(f"Total Steps Taken:     {step}")
        log(f"Duration (seconds):    {duration}")
        log(f"Status:                {summary['status']}")
        log(f"Final State Reached:   {is_final}")
        log("==================================================\n")

        return summary

    except Exception as e:
        log(f"❌ Execution Exception Encountered: {e}")
        duration = round(time.time() - start_time, 2)
        return {
            "run_id": run_id,
            "target_url": target_url,
            "user_goal": user_goal,
            "total_steps": 0,
            "status": f"ERROR: {e}",
            "is_final": False,
            "duration_seconds": duration,
            "screenshot_path": None
        }
    finally:
        await browser_engine.close_session()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parallel AI Automation CLI Runner")
    parser.add_argument("--url", help="Target URL override")
    parser.add_argument("--goal", help="Natural language objective")
    parser.add_argument("--headless", action="store_true", default=None, help="Force headless execution")
    parser.add_argument("--headed", action="store_true", default=None, help="Force headed execution")
    args, unknown = parser.parse_known_args()

    # 1. Resolve centralized configurations
    runtime_registry = load_unified_config()
    
    # Resolve target URL
    target_url = args.url or runtime_registry["environment"]["target_url"]
    
    # Resolve Goal Objective
    goal = args.goal
    if not goal:
        # Fallback to positional args if present, else default
        remaining_args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if remaining_args:
            goal = " ".join(remaining_args)
        else:
            goal = "Log into the system and successfully add a new employee record using the dynamic data pool."

    # Resolve headless visibility defaults
    if args.headless:
        runtime_registry["environment"]["headless"] = True
    elif args.headed:
        runtime_registry["environment"]["headless"] = False
    else:
        # Auto-default to headless in CI/CD pipelines
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("JENKINS_URL") or os.getenv("GITLAB_CI"):
            runtime_registry["environment"]["headless"] = True

    print("\n==================================================")
    print(f"🎯 ACTIVE OBJECTIVE: {goal}")
    print(f"🌐 TARGET URL:      {target_url}")
    print(f"🖥️ BROWSER MODE:     {'HEADLESS' if runtime_registry['environment'].get('headless') else 'HEADED'}")
    print("==================================================\n")

    # 2. Fire the autonomous loop and return standard shell exit codes
    try:
        summary = asyncio.run(run_autonomous_navigator(runtime_registry, target_url, goal, "cli_run"))
        if summary.get("is_final") or summary.get("status") == "SUCCESS":
            print("\n🎉 CLI RUN COMPLETED SUCCESSFULLY!")
            sys.exit(0)
        else:
            print("\n❌ CLI RUN failed to reach ultimate objective.")
            sys.exit(1)
    except Exception as cli_ex:
        print(f"\n❌ CLI RUN crashed with exception: {cli_ex}")
        sys.exit(1)