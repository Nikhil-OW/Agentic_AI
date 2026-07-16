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

def call_gemini_with_retry(client, model, contents, config=None, max_attempts=5):
    import re
    import time
    
    # Introduce rate limiting sleep to avoid hitting immediate RPM limits
    time.sleep(5.0)
    
    for attempt in range(1, max_attempts + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
        except Exception as ex:
            ex_str = str(ex)
            is_rate_limit = any(term in ex_str for term in ["429", "RESOURCE_EXHAUSTED", "Quota exceeded"])
            is_unavailable = any(term in ex_str for term in ["503", "UNAVAILABLE"])
            
            if is_rate_limit or is_unavailable:
                if is_rate_limit:
                    match = re.search(r'(?:retry in|retryDelay[\'\"\s:]+)([\d\.]+)', ex_str)
                    if match:
                        sleep_time = float(match.group(1)) + 5.0
                    else:
                        sleep_time = (2 ** attempt) * 10
                    alert_msg = f"Gemini API 429 Exhausted"
                else:
                    sleep_time = 60.0
                    alert_msg = f"Gemini API 503 Unavailable"
                
                print(f"[RATE LIMIT ALERT] {alert_msg}. Automatically sleeping for {sleep_time:.2f} seconds before retrying execution loop (Attempt {attempt}/{max_attempts})...")
                time.sleep(sleep_time)
            else:
                raise ex
    raise Exception(f"Gemini API Rate Limit or Availability attempts exhausted ({max_attempts} attempts).")

class ElementInteraction(BaseModel):
    action: str = Field(description="The action to perform: 'click', 'type', 'select', 'wait', 'press_key', or 'refresh'.")
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


def generate_jit_test_data(live_elements):
    """
    Reactively generates a synthetic data pool tailored to the exact input fields
    physically rendered on the active page.
    """
    jit_payload = {}
    
    # Analyze what fields are physically present
    has_first = False
    has_last = False
    has_email = False
    has_personal_email = False
    has_work_email = False
    has_phone = False
    has_company = False
    has_title = False
    has_city = False
    has_address = False
    has_zip = False
    has_memo = False
    has_empid = False
    has_password = False
    has_dob = False
    has_joining = False
    has_exp = False
    has_dept = False
    has_salary = False
    has_uan = False
    
    for el in live_elements:
        tag = str(el.get("tag", "")).lower()
        el_type = str(el.get("type", "")).lower()
        if tag not in ["input", "select", "textarea"]:
            continue
        if el_type in ["button", "submit", "checkbox", "radio", "file", "hidden"]:
            continue
            
        name = (el.get("name") or "").lower()
        id_attr = (el.get("id") or "").lower()
        label = (el.get("label") or "").lower()
        placeholder = (el.get("placeholder") or "").lower()
        target_key = f"{name} {id_attr} {label} {placeholder}".strip()
        
        if "first" in target_key or "fname" in target_key:
            has_first = True
        elif "last" in target_key or "lname" in target_key:
            has_last = True
        elif "personal" in target_key:
            has_personal_email = True
        elif "work" in target_key:
            has_work_email = True
        elif "email" in target_key:
            has_email = True
        elif "phone" in target_key or "mobile" in target_key or "number" in target_key:
            has_phone = True
        elif "company" in target_key:
            has_company = True
        elif "title" in target_key or "designation" in target_key:
            has_title = True
        elif "city" in target_key or "location" in target_key:
            has_city = True
        elif "address" in target_key:
            has_address = True
        elif "zip" in target_key or "postal" in target_key:
            has_zip = True
        elif "id" in target_key or "employee" in target_key:
            has_empid = True
        elif "password" in target_key:
            has_password = True
        elif "dob" in target_key or "birth" in target_key:
            has_dob = True
        elif "date" in target_key or "joining" in target_key:
            has_joining = True
        elif "experience" in target_key:
            has_exp = True
        elif "department" in target_key:
            has_dept = True
        elif "salary" in target_key:
            has_salary = True
        elif "uan" in target_key:
            has_uan = True
        elif "memo" in target_key or "note" in target_key or "description" in target_key:
            has_memo = True

    # Lazy generate Faker values ONLY for elements that exist on page
    if has_first:
        jit_payload["first_name"] = fake.first_name()
    if has_last:
        jit_payload["last_name"] = fake.last_name()
    if has_first and has_last:
        jit_payload["full_name"] = f"{jit_payload['first_name']} {jit_payload['last_name']}"
    elif has_first:
        jit_payload["full_name"] = f"{jit_payload['first_name']} {fake.last_name()}"
    elif has_last:
        jit_payload["full_name"] = f"{fake.first_name()} {jit_payload['last_name']}"
        
    if has_personal_email:
        f_name = jit_payload.get("first_name", fake.first_name()).lower()
        l_name = jit_payload.get("last_name", fake.last_name()).lower()
        jit_payload["personal_email"] = f"personal.{f_name}.{l_name}@example.com"
    if has_work_email:
        f_name = jit_payload.get("first_name", fake.first_name()).lower()
        l_name = jit_payload.get("last_name", fake.last_name()).lower()
        jit_payload["work_email"] = f"work.{f_name}.{l_name}@optimworks.com"
    if has_email:
        f_name = jit_payload.get("first_name", fake.first_name()).lower()
        l_name = jit_payload.get("last_name", fake.last_name()).lower()
        jit_payload["email"] = f"{f_name}.{l_name}@{fake.free_email_domain()}"
        
    if has_phone:
        jit_payload["phone_number"] = f"9{fake.msisdn()[:9]}"
    if has_company:
        jit_payload["company"] = fake.company()
    if has_title:
        jit_payload["job_title"] = fake.job()
    if has_city:
        jit_payload["city"] = fake.city()
    if has_address:
        jit_payload["street_address"] = fake.street_address()
    if has_zip:
        jit_payload["zip_code"] = fake.zipcode()
    if has_empid:
        jit_payload["employee_id"] = f"EMP{fake.random_int(1000, 9999)}"
    if has_password:
        jit_payload["password"] = "Password123!"
    if has_dob:
        jit_payload["dob"] = "1995-05-15"
    if has_joining:
        jit_payload["joining_date"] = "2026-07-01"
    if has_exp:
        jit_payload["past_experience"] = str(fake.random_int(1, 10))
    if has_dept:
        jit_payload["department"] = "Engineering"
    if has_salary:
        jit_payload["salary"] = str(fake.random_int(50000, 150000))
    if has_uan:
        jit_payload["uan"] = f"100{fake.random_int(100000000, 999999999)}"
    if has_memo:
        jit_payload["text_memo"] = fake.paragraph(nb_sentences=3)
        
    return jit_payload


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


async def detect_validation_errors(page, user_goal="") -> Optional[str]:
    """
    Scrapes the active page for application-side validation banners, alert dialogs,
    error divs, invalid field messages, or duplicate entry constraint rejections.
    """
    if not page:
        return None
    try:
        goal_lower = user_goal.lower()
        ignore_newsletter = not any(kw in goal_lower for kw in ["subscribe", "newsletter", "footer", "subscription"])
        
        return await page.evaluate("""(ignoreNewsletter) => {
            const selectors = [
                '.alert-danger', '.alert-error', '.error-message', '.error-text', 
                '.validation-error', '.invalid-feedback', '[role="alert"]', 
                '.error', '.danger', '.text-danger', '.alert', '.notification-danger',
                '#error-message', '#validation-errors', '.field-validation-error',
                '.error-summary', '.validation-summary-errors'
            ];
            let errors = [];
            
            const isIrrelevant = (node) => {
                if (!node) return false;
                if (!ignoreNewsletter) return false;
                
                const container = node.closest('footer, aside, .footer, .sidebar, #footer, #sidebar, .newsletter, .subscribe, #subscribe_email');
                if (container) return true;
                
                const text = (node.innerText || "").toLowerCase();
                const nameAttr = (node.getAttribute("name") || "").toLowerCase();
                const idAttr = (node.getAttribute("id") || "").toLowerCase();
                const classAttr = (node.getAttribute("class") || "").toLowerCase();
                
                if (nameAttr.includes("subscribe") || nameAttr.includes("newsletter") ||
                    idAttr.includes("subscribe") || idAttr.includes("newsletter") ||
                    classAttr.includes("subscribe") || classAttr.includes("newsletter") ||
                    text.includes("subscribe") || text.includes("newsletter")) {
                    return true;
                }
                return false;
            };
            
            // 1. Selector-based scanning
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    if (isIrrelevant(el)) return;
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
                if (isIrrelevant(el)) return;
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
                if (isIrrelevant(el)) return;
                if (el.validationMessage && el.offsetWidth > 0 && el.offsetHeight > 0) {
                    errors.push(`Field '${el.name || el.id || el.placeholder}': ${el.validationMessage}`);
                }
                if (el.getAttribute('aria-invalid') === 'true') {
                    errors.push(`Field '${el.name || el.id || el.placeholder}' is marked invalid.`);
                }
            });
            
            return errors.length > 0 ? errors.join('; ') : null;
        }""", ignore_newsletter)
    except Exception as e:
        print(f"⚠️ Error while parsing page validation errors: {e}")
        return None


async def detect_success_indicators(page, live_elements, user_goal="", execution_history=None):
    """
    Scans the live DOM structure and text elements for positive success indicators
    (toasts, popups, success keywords, or dashboard transitions).
    """
    try:
        # If a password input field is visible on screen, we are on a login form and not logged in yet
        has_password_field = False
        for el in live_elements:
            tag = el.get("tag", "").lower()
            type_attr = (el.get("type") or "").lower()
            selector = el.get("computed_selector") or ""
            if tag == "input" and (type_attr == "password" or "password" in selector.lower()):
                has_password_field = True
                break
        if has_password_field:
            return None

        url = page.url.lower()
        
        is_login_goal = any(kw in user_goal.lower() for kw in ["log in", "login", "authenticate", "sign in", "verify dashboard"]) and not any(kw in user_goal.lower() for kw in ["add", "create", "new", "register", "submit"])
        has_filled_form = False
        if execution_history:
            has_filled_form = any(
                h.get("action_executed") in ["type", "select"] 
                and not any(login_sel in str(h.get("target_selector")).lower() for login_sel in ["useremail", "userpassword", "loginbtn", "username", "password"])
                for h in execution_history
            )

        if any(keyword in url for keyword in ["dashboard", "home", "employees", "list", "index"]):
            if "login" not in url:
                if is_login_goal or has_filled_form:
                    return f"Redirected to dashboard/list view URL: {page.url}"

        success_message = await page.evaluate('''() => {
            const successKeywords = [
                "saved successfully",
                "successfully added",
                "employee created",
                "profile saved",
                "created successfully",
                "added successfully",
                "registration complete",
                "logged in"
            ];
            
            let foundText = null;
            document.querySelectorAll('div, span, p, h1, h2, h3, h4, h5, h6, b, strong, label').forEach(el => {
                if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                    const text = el.innerText ? el.innerText.trim() : '';
                    if (text && text.length > 2) {
                        const lowerText = text.toLowerCase();
                        for (const kw of successKeywords) {
                            if (lowerText.includes(kw)) {
                                foundText = text;
                                return;
                            }
                        }
                    }
                }
            });
            return foundText;
        }''')
        
        if success_message:
            return f"Success indicator found in DOM: {success_message}"

        for el in live_elements:
            text = (el.get("text") or "").lower()
            selector = el.get("computed_selector") or ""
            if "success" in text or "saved" in text or "created" in text or "toast" in selector:
                if any(kw in text for kw in ["success", "saved", "created", "added", "complete"]):
                    return f"Success text matched: {el.get('text')}"

    except Exception:
        pass
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
    test_data = config_registry.get("test_data", {})
    config_user = test_data.get("username", "")
    config_pass = test_data.get("password", "")
    if config_user and config_pass:
        system_prompt += (
            f"\nIMPORTANT: If the active screen requires authentication, you MUST prioritize using these exact credentials: "
            f"Username: {config_user}, Password: {config_pass}. "
            f"Do not generate synthetic values for login inputs."
        )

    max_steps = config_registry["environment"].get("max_retry_steps", 8)

    # Initialize dynamic data payload
    dynamic_payload = {}

    # Initialize an execution memory matrix to maintain run context
    execution_history = []
    consecutive_failures = {}
    llm_times = []
    scrape_times = []
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
        interception_warning = None

        while not is_final and step < max_steps:
            log(f"\n--- 🧠 Agent Dynamically Analyzing Step {step + 1} ---")
            
            # Extract and clear active overlay warning
            active_interception = interception_warning
            interception_warning = None

            # 1. Scrape deep layout parameters with timing telemetry
            scrape_start = time.time()
            live_elements = await browser_engine.extract_interactive_elements()

            # Check for success indicators at the beginning of the step
            success_indicator = await detect_success_indicators(page, live_elements, user_goal, execution_history)
            if success_indicator:
                log(f"🎉 SUCCESS INDICATOR DETECTED: {success_indicator}")
                log("🏁 Form submission or authentication confirmed. Terminating loop with PASSED status.")
                is_final = True
                break

            # Detect any validation error messages on the page
            validation_error = await detect_validation_errors(page, user_goal)
            scrape_duration = time.time() - scrape_start
            scrape_times.append(scrape_duration)
            log(f"⏱️ Telemetry: Page Scrape & Validation Check Time: {scrape_duration:.3f}s")

            if validation_error:
                log(f"⚠️ SELF-HEALING: Validation/rejection error detected on page: {validation_error}")
                log("🎲 SELF-HEALING: Re-generating alternative synthetic data parameters for active screen...")
                
            test_data = config_registry.get("test_data", {})
            config_user = test_data.get("username", "")
            config_pass = test_data.get("password", "")
            
            # Enforce hard static configuration credentials if on a login page context
            is_login_context = False
            try:
                current_url = browser_engine.page.url.lower()
                if "login" in current_url or any(el.get("id") in ["email", "userEmail", "username", "password", "userPassword"] for el in live_elements):
                    is_login_context = True
            except Exception:
                pass

            if is_login_context and config_user and config_pass:
                log("🔐 Login context detected. Binding static credentials from configuration instead of triggering JIT generator.")
                dynamic_payload = {
                    "email": config_user,
                    "username": config_user,
                    "userEmail": config_user,
                    "password": config_pass,
                    "userPassword": config_pass
                }
            else:
                # Reactively generate JIT test data for fields currently on the page
                dynamic_payload = generate_jit_test_data(live_elements)
                
            log("🎲 JIT SYNTHETIC DATA POOL GENERATED FOR ACTIVE SCREEN:")
            log(json.dumps(dynamic_payload, indent=2))
            log("--------------------------------------------------")

            # 2. Build context payload, injecting history tracking layer and error context if present
            error_injection = ""
            if active_interception:
                error_injection += f"--- OVERLAY INTERCEPTION ERROR ---\n{active_interception}\n\n"
            if validation_error:
                error_injection += (
                    f"--- RUNTIME ERROR / VALIDATION REJECTION ENCOUNTERED ---\n"
                    f"The application has rejected the input or submission with the following error:\n"
                    f"\"{validation_error}\"\n\n"
                    f"Action Required:\n"
                    f"1. Clear and re-fill the conflicting field with updated values from the refreshed \"SYNTHETIC DATA POOL\" below.\n"
                    f"2. Use the refreshed dynamic fields to avoid duplicate or validation constraint issues.\n"
                    f"3. Click the submit/add button to re-attempt submission.\n\n"
                )

            # Compile failure injection warnings if any selector has failed consecutively
            failure_injection = ""
            blocked_selectors = [sel for sel, count in consecutive_failures.items() if count >= 2]
            if blocked_selectors:
                failure_injection = (
                    f"--- REPEATED FAILURE DETECTION ---\n"
                    f"The following elements/selectors have failed repeatedly during execution:\n"
                )
                for sel in blocked_selectors:
                    failure_injection += f"- Selector '{sel}' has failed {consecutive_failures[sel]} times consecutively.\n"
                failure_injection += (
                    f"\nAction Required:\n"
                    f"You MUST NOT retry the exact same selector or action on those blocked selectors. "
                    f"Analyze the layout matrix for alternative paths to achieve the same goal, "
                    f"such as hitting the 'Enter' key on the active field (using action 'press_key'), "
                    f"clicking an adjacent text label, refreshing the view (using action 'refresh'), "
                    f"or selecting a different element.\n\n"
                )

            # Extract visible page text to capture labels, hint texts, instructions, and credentials
            try:
                page_text_raw = await page.evaluate("() => document.body.innerText")
                page_text = "\n".join([line.strip() for line in page_text_raw.split("\n") if line.strip()])
            except Exception as e_text:
                page_text = f"Error extracting page text: {e_text}"

            context_payload = (
                f"Your Ultimate High-Level Objective: '{user_goal}'\n\n"
                f"{error_injection}"
                f"{failure_injection}"
                f"--- PAGE VISIBLE TEXT AND CONTEXTUAL INSTRUCTIONS ---\n"
                f"{page_text[:4000]}\n\n"
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

            # 3. Process layout schema via the AI brain (with exponential backoff retries and timing)
            log("📡 Sending layout matrix and memory history to AI brain...")
            response = None
            llm_start = time.time()
            try:
                response = call_gemini_with_retry(
                    client=ai_client,
                    model='gemini-flash-lite-latest',
                    contents=context_payload,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=AgentAction,
                    ),
                    max_attempts=3
                )
            except Exception as ex:
                log(f"❌ Gemini API attempts completely exhausted: {ex}")
                raise ex
            llm_duration = time.time() - llm_start
            llm_times.append(llm_duration)
            log(f"⏱️ Telemetry: LLM Inference Time: {llm_duration:.3f}s")

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

            # Force End-of-Form Terminal Action Guard
            has_submit_in_actions = False
            for act in actions_list:
                act_type = str(act.get('action', '')).lower().strip()
                act_selector = act.get('selector') or act.get('target_selector') or act.get('css_selector') or ''
                if act_type == 'click' and any(kw in str(act_selector).lower() for kw in ['add', 'save', 'submit', 'login', 'create']):
                    has_submit_in_actions = True
                    break

            submit_element = None
            input_elements = [el for el in live_elements if el.get("tag", "").lower() in ["input", "select", "textarea"] and el.get("type", "").lower() not in ["search", "button", "submit", "hidden"]]
            has_inputs = len(input_elements) > 1
            if has_inputs:
                for el in live_elements:
                    selector = el.get("computed_selector") or ""
                    tag = el.get("tag", "").lower()
                    text = (el.get("text") or "").lower()
                    placeholder = (el.get("placeholder") or "").lower()
                    is_btn = tag == "button" or el.get("type") == "submit" or "button" in selector or "submit" in selector
                    is_submit_text = any(kw in text or kw in placeholder or kw in selector.lower() for kw in ["add", "save", "submit", "login", "create"])
                    if is_btn and is_submit_text:
                        submit_element = el
                        break

            if submit_element and not has_submit_in_actions:
                is_final_raw = command.get('is_final') or command.get('final') or command.get('isFinal') or False
                is_final_val = str(is_final_raw).lower() in ('true', '1', 'yes') if not isinstance(is_final_raw, bool) else is_final_raw
                if is_final_val or len(actions_list) > 0:
                    log(f"🛡️ Form Submission Safety Guard: Force-appending click on submission button '{submit_element['computed_selector']}'")
                    actions_list.append({
                        "action": "click",
                        "selector": submit_element["computed_selector"],
                        "text_to_type": None,
                        "value_to_select": None,
                        "wait_time_ms": 2000
                    })

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
                        has_employee_form = (
                            await page.locator("input:not([type='hidden']), select, textarea").count() > 1
                            and not any(login_kw in str(act_selector).lower() for login_kw in ["login", "signin"])
                        )

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
                        
                        is_nav_click = (
                            'href' in str(act_selector).lower() or
                            'text=' in str(act_selector).lower() or
                            'button' in str(act_selector).lower() or
                            'a' in str(act_selector).lower()
                        )
                        
                        if is_nav_click:
                            try:
                                async with page.expect_navigation(wait_until="load", timeout=4000):
                                    try:
                                        await page.click(act_selector, timeout=4000)
                                    except Exception as e_click:
                                        log(f"  ⚠️ Direct click on '{act_selector}' failed or was intercepted: {e_click}. Retrying with force=True...")
                                        await page.click(act_selector, force=True)
                            except Exception:
                                pass
                        else:
                            try:
                                await page.click(act_selector, timeout=5000)
                            except Exception as e_click:
                                log(f"  ⚠️ Direct click on '{act_selector}' failed or was intercepted: {e_click}. Retrying with force=True...")
                                try:
                                    await page.click(act_selector, force=True)
                                except Exception:
                                    pass
                                    
                        try:
                            await page.wait_for_load_state("load", timeout=4000)
                        except Exception:
                            pass
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
                    elif act_type == 'press_key':
                        log(f"    🎹 Pressing key '{act_text or 'Enter'}' on selector '{act_selector}'")
                        if act_selector:
                            await page.wait_for_selector(act_selector, state="visible", timeout=5000)
                            await page.locator(act_selector).press(act_text or "Enter")
                        else:
                            await page.keyboard.press(act_text or "Enter")
                        await asyncio.sleep(0.5)
                    elif act_type == 'refresh':
                        log("    🔄 Refreshing page view...")
                        await page.reload()
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)

                    # Log this action into the running memory matrix
                    execution_history.append({
                        "step": step + 1,
                        "sub_step": idx + 1,
                        "action_executed": act_type,
                        "target_selector": act_selector
                    })

                    if act_selector:
                        consecutive_failures[act_selector] = 0

                    # If custom wait is specified, execute it
                    if act_wait and act_type != 'wait':
                        await asyncio.sleep(float(act_wait) / 1000.0)

                except Exception as e_act:
                    log(f"  ❌ Sequence Action failed: {e_act}")
                    err_msg = str(e_act).lower()
                    if "intercepts pointer events" in err_msg or "click intercepted" in err_msg:
                        interception_warning = (
                            f"Your click on selector '{act_selector}' was blocked because a dynamic overlay modal "
                            "or popup (such as '#cartModal') was active and intercepting pointer events. "
                            "You MUST immediately target and click the appropriate button/link INSIDE that modal "
                            "(e.g., clicking 'View Cart' or closing the modal) before attempting to click any background elements."
                        )
                    if act_selector:
                        consecutive_failures[act_selector] = consecutive_failures.get(act_selector, 0) + 1
                        log(f"  ⚠️ Selector '{act_selector}' has failed consecutively {consecutive_failures[act_selector]} time(s).")
                    log("  🔄 Stopping sequence execution early to allow self-healing re-analysis.")
                    break

            # Determine final status with variations supported
            is_final_raw = command.get('is_final') or command.get('final') or command.get('isFinal') or False
            is_final = str(is_final_raw).lower() in ('true', '1', 'yes') if not isinstance(is_final_raw, bool) else is_final_raw

            # Post-action success and validation verification (Error-Retry self-healing check)
            new_elements = await browser_engine.extract_interactive_elements()
            success_indicator = await detect_success_indicators(page, new_elements, user_goal, execution_history)
            if success_indicator:
                log(f"🎉 SUCCESS INDICATOR DETECTED POST-ACTION: {success_indicator}")
                log("🏁 Form submission or authentication confirmed. Terminating loop with PASSED status.")
                is_final = True
            else:
                post_action_error = await detect_validation_errors(page, user_goal)
                
                # Check if active form elements and a submit button are still visible
                input_elements_post = [el for el in new_elements if el.get("tag", "").lower() in ["input", "select", "textarea"] and el.get("type", "").lower() not in ["search", "button", "submit", "hidden"]]
                has_inputs = len(input_elements_post) > 1
                
                has_visible_submit = False
                if has_inputs:
                    for el in new_elements:
                        selector = el.get("computed_selector") or ""
                        tag = el.get("tag", "").lower()
                        text = (el.get("text") or "").lower()
                        is_btn = tag == "button" or el.get("type") == "submit" or "button" in selector or "submit" in selector
                        is_submit_text = any(kw in text or kw in selector.lower() for kw in ["add", "save", "submit", "login", "create"])
                        if is_btn and is_submit_text:
                            has_visible_submit = True
                            break
                
                if is_final and (post_action_error or has_visible_submit):
                    if post_action_error:
                        log(f"⚠️ SELF-HEALING OVERRIDE: Post-action validation error detected on page: {post_action_error}")
                    else:
                        log(f"⚠️ SELF-HEALING OVERRIDE: Form is still visible on screen with submission button. State transition did not occur.")
                    log("🛡️ Rejecting agent finalization request. Retrying submission...")
                    is_final = False

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
        
        # Compute latency averages
        avg_llm = round(sum(llm_times) / len(llm_times), 3) if llm_times else 0.0
        avg_scrape = round(sum(scrape_times) / len(scrape_times), 3) if scrape_times else 0.0
        ratio = round(avg_llm / avg_scrape, 1) if avg_scrape > 0 else 0.0
        
        telemetry_report = (
            "==================================================\n"
            "📊 AGENTIC PERFORMANCE TELEMETRY REPORT\n"
            "==================================================\n"
            f"Average AI Inference Latency:   {avg_llm:.2f}s / step\n"
            f"Average DOM Scrape Latency:     {avg_scrape:.2f}s / step\n"
            f"Total AI Reasonings:            {len(llm_times)}\n"
            f"Total DOM Scrapes:              {len(scrape_times)}\n"
            f"Average Latency Ratio (AI/Sys): {ratio}x\n"
            "=================================================="
        )

        summary = {
            "run_id": run_id,
            "target_url": target_url,
            "user_goal": user_goal,
            "total_steps": step,
            "status": "SUCCESS" if is_final else "FAILED/INCOMPLETE",
            "is_final": is_final,
            "duration_seconds": duration,
            "screenshot_path": f"screenshots/run_{run_id}_final.png" if os.path.exists(f"screenshots/run_{run_id}_final.png") else None,
            "avg_llm_time": avg_llm,
            "avg_scrape_time": avg_scrape,
            "telemetry_report": telemetry_report
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
        
        log("\n" + telemetry_report + "\n")

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
            "screenshot_path": None,
            "avg_llm_time": 0.0,
            "avg_scrape_time": 0.0,
            "telemetry_report": "No telemetry available due to exception."
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