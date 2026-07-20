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


def generate_jit_test_data(live_elements, user_goal: str = ""):
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
    has_from_date = False
    has_to_date = False
    has_reason = False
    has_subject = False
    has_exp = False
    has_dept = False
    has_salary = False
    has_uan = False
    
    for el in live_elements:
        tag = str(el.get("tag", "")).lower()
        el_type = str(el.get("type", "")).lower()
        if tag not in ["input", "select", "textarea"]:
            continue
        if el_type in ["button", "submit", "checkbox", "file", "hidden"]:
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
        elif "from" in target_key or "start" in target_key:
            has_from_date = True
        elif "to" in target_key or "end" in target_key:
            has_to_date = True
        elif "date" in target_key or "joining" in target_key:
            has_joining = True
        elif "subject" in target_key:
            has_subject = True
        elif "reason" in target_key or "purpose" in target_key:
            has_reason = True
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
        jit_payload["dob"] = resolve_dynamic_date("dob", user_goal)
    if has_from_date:
        jit_payload["from_date"] = resolve_dynamic_date("from", user_goal)
    if has_to_date:
        jit_payload["to_date"] = resolve_dynamic_date("to", user_goal)
    if has_joining:
        jit_payload["joining_date"] = resolve_dynamic_date("joining", user_goal)
    if has_subject:
        jit_payload["subject"] = "Leave Application"
    if has_reason:
        jit_payload["reason"] = "Personal work requirement"
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


async def handle_active_modal(page, live_elements) -> tuple[bool, bool]:
    # 1. Bypass Integrity Check: verify if a modal is actually present on screen
    has_modal = False
    try:
        has_modal = await page.evaluate('''() => {
            const modal = document.querySelector('div.modal, .modal, [class*="modal"]');
            if (modal) {
                const rect = modal.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && window.getComputedStyle(modal).display !== 'none';
            }
            const bodyText = document.body.innerText || "";
            return bodyText.includes("LOP Warning") || bodyText.includes("Loss of Pay");
        }''')
    except Exception:
        pass
        
    if not has_modal:
        return False, False
        
    print("🚨 [MODAL INSPECTOR]: Active modal layout detected! Routing to dynamic modal handler.")
    
    # 2. Targeted semantic button selectors & Force parameter binding
    selectors_to_try = [
        'button:has-text("Ok")',
        'button:text("Ok")',
        'button:has-text("Cancel")',
        'button:text("Cancel")',
        '.modal button:has-text("Ok")',
        '.modal button:has-text("Cancel")',
        'div.modal button',
        '[class*="modal"] button'
    ]
    
    for sel in selectors_to_try:
        match_text = "Ok" if "ok" in sel.lower() else ("Cancel" if "cancel" in sel.lower() else "fallback button node")
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1000):
                print(f"[MODAL RESOLUTION]: Attempting click on button node matching text \"{match_text}\"")
                is_cancel = "cancel" in sel.lower()
                try:
                    await loc.click(force=True, timeout=2000)
                    await page.wait_for_timeout(1000)
                    print(f"✅ [MODAL RESOLUTION SUCCESS]: Overlay successfully cleared via text \"{match_text}\"")
                    return True, is_cancel
                except Exception:
                    print("❌ [MODAL RESOLUTION FAILED]: Direct click blocked. Retrying dynamic selector path...")
                    raise
        except Exception:
            continue
            
    # Fallback to Escape press if buttons cannot be resolved or clicked
    try:
        print("🛠️ [MODAL RESOLUTION]: Attempting fallback dismissal via keyboard Escape.")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        return True, False
    except Exception:
        pass
        
    return False, False


import datetime

def is_weekend_2026(dt: datetime.date) -> bool:
    return dt.weekday() in (5, 6)  # 5 = Saturday, 6 = Sunday

def get_valid_business_day(start_date: datetime.date, forward: bool = True) -> datetime.date:
    curr = start_date
    while is_weekend_2026(curr):
        curr += datetime.timedelta(days=1 if forward else -1)
    return curr

def resolve_dynamic_date(key: str, user_goal: str = "") -> str:
    # Environment context locked to 2026 (current date July 20, 2026)
    current_year = 2026
    current_month = 7

    key_lower = key.lower()
    goal_lower = user_goal.lower()

    if "dob" in key_lower or "birth" in key_lower:
        return "1995-05-15"

    allow_weekend = any(kw in goal_lower for kw in ["weekend", "saturday", "sunday"])

    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
        "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
    }

    target_month = None
    for m_name, m_val in months.items():
        if m_name in goal_lower:
            target_month = m_val
            break

    if target_month is None:
        # Immediate upcoming month (August 2026)
        target_year = 2026
        target_month = 8
    else:
        if target_month <= current_month:
            # Past month relative to July 2026 -> map to closest upcoming future instance (e.g. May -> May 2027)
            target_year = 2027
        else:
            target_year = 2026

    if "from" in key_lower or "start" in key_lower or "joining" in key_lower:
        dt = datetime.date(target_year, target_month, 1)
        if not allow_weekend and is_weekend_2026(dt):
            dt = get_valid_business_day(dt, forward=True)
        return dt.strftime("%Y-%m-%d")
    elif "to" in key_lower or "end" in key_lower:
        import calendar
        last_day = calendar.monthrange(target_year, target_month)[1]
        dt = datetime.date(target_year, target_month, min(last_day, 28))
        if not allow_weekend and is_weekend_2026(dt):
            dt = get_valid_business_day(dt, forward=False)
        return dt.strftime("%Y-%m-%d")
    else:
        dt = datetime.date(target_year, target_month, 15)
        if not allow_weekend and is_weekend_2026(dt):
            dt = get_valid_business_day(dt, forward=True)
        return dt.strftime("%Y-%m-%d")


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

    from core.test_cache_manager import check_and_init_cache, get_cache_dir
    cache_exists = check_and_init_cache()
    cache_dir = get_cache_dir()
    if not cache_exists:
        log(f"ℹ️ Active JIRA Key Cache directory '{cache_dir}' does not exist. Initializing 'Dynamic Interpretation Mode'.")
    else:
        log(f"ℹ️ Active JIRA Key Cache directory '{cache_dir}' exists. Cache is available.")

    system_prompt = load_system_instructions()
    from core.test_cache_manager import load_application_knowledge
    insights = load_application_knowledge()
    if insights:
        insights_str = "\n".join(f"- {ins}" for ins in insights)
        system_prompt += f"\n\n## Dynamic Application Insights\n{insights_str}\n"
        log("💡 [KNOWLEDGE LOOP]: Loaded and injected dynamic application insights into system prompt.")
    test_data = config_registry.get("test_data", {})
    config_user = test_data.get("username", "")
    config_pass = test_data.get("password", "")
    if config_user and config_pass:
        system_prompt += (
            f"\nIMPORTANT: If the active screen requires authentication, you MUST prioritize using these exact credentials: "
            f"Username: {config_user}, Password: {config_pass}. "
            f"Do not generate synthetic values for login inputs."
        )

    if any(kw in (user_goal or "").lower() for kw in ["extra work", "extra hours", "claim extra", "log extra"]):
        system_prompt += (
            "\n\n## CROSS-FUNCTIONAL NAVIGATION MAPPING FOR EXTRA WORK TICKETS\n"
            "- CRITICAL RULE FOR EXTRA WORK WORKFLOWS: While summary metrics for extra hours or days are displayed inside the Leave Management dashboard (e.g., 'Extra Work In JUL' metrics cards), the actual interactive entry form, application, and submission workflow tasks for logging extra work MUST be executed within the 'Reimbursement' sidebar section.\n"
            "- When a scenario or ticket mentions 'applying extra work', 'submitting extra work days', 'claiming extra work validation', or 'logging extra hours', you MUST programmatically favor navigating to the sidebar component matching text 'Reimbursement' (or anchor pattern `a:has-text(\"Reimbursement\")` / `li:has-text(\"Reimbursement\")`) rather than hunting for interactive input components inside the Leave Management overview grid.\n"
            "- Ensure that dynamic validation rules cross-check that inputs entered in the Reimbursement module cleanly propagate back to or update the metric counts displayed on the primary dashboard tracking views.\n"
        )
        log("🔀 [NAVIGATION ROUTING ENHANCEMENT]: Goal references Extra Work. Injected Reimbursement sidebar routing rules into system prompt.")

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
        consecutive_unchanged_count = 0
        total_unchanged_steps = 0
        hard_escape_until_step = 0
        recovery_mode = False
        
        while not is_final and step < max_steps:
            log(f"\n--- 🧠 Agent Dynamically Analyzing Step {step + 1} ---")
            
            force_next_clicks = False
            if recovery_mode:
                force_next_clicks = True
                recovery_mode = False
            
            # Extract and clear active overlay warning
            active_interception = interception_warning
            interception_warning = None

            # 1. Scrape deep layout parameters with timing telemetry
            scrape_start = time.time()
            live_elements = await browser_engine.extract_interactive_elements()

            # Track state before action (and modal resolutions) for cached/layout sequence hits
            import hashlib
            before_url = page.url
            before_repr = "".join(f"{el.get('computed_selector')}:{el.get('text')}" for el in live_elements)
            before_dom_hash = hashlib.md5(before_repr.encode('utf-8')).hexdigest()
            try:
                before_focus = await page.evaluate("() => document.activeElement ? document.activeElement.tagName + '.' + document.activeElement.className + '#' + document.activeElement.id : ''")
            except Exception:
                before_focus = ""

            # --- DYNAMIC PRE-FLIGHT MODAL INSPECTION ---
            modal_resolved, is_cancel = await handle_active_modal(page, live_elements)
            if modal_resolved:
                log("🔄 Modal overlay successfully cleared during pre-flight. Re-evaluating screen layout...")
                from core.test_cache_manager import save_application_knowledge, load_application_knowledge
                knowledge = load_application_knowledge()
                insight_desc = f"On URL path '{page.url}', dynamically resolved visible modal overlay using semantic click controls."
                if insight_desc not in knowledge:
                    knowledge.append(insight_desc)
                    save_application_knowledge(knowledge)
                    log(f"💾 [KNOWLEDGE APPENDED]: Saved modal resolution insight: '{insight_desc}'")
                if is_cancel:
                    log("🧹 [MODAL RESOLUTION]: Cancellation path ('Cancel') triggered. Clearing local cache loop memory traces immediately.")
                    consecutive_failures.clear()
                    consecutive_unchanged_count = 0
                    
                    from core.test_cache_manager import invalidate_flow_cache, invalidate_layout_map
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(page.url)
                        path_fragment = parsed.path.strip("/")
                        if path_fragment:
                            invalidate_flow_cache(f"flow_{path_fragment}")
                            invalidate_layout_map(path_fragment)
                    except Exception as e_inv:
                        log(f"⚠️ Invalidation error: {e_inv}")
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
                dynamic_payload = generate_jit_test_data(live_elements, user_goal)
                
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

            # --- CACHE-FIRST ROUTING AND TOKEN CONSERVATION ---
            from core.test_cache_manager import get_cached_actions, save_cached_actions, check_preflight_layout, update_layout_map_from_actions
            
            used_cache = False
            cache_type = None
            cache_key = None
            command = None
            
            if step < hard_escape_until_step:
                log(f"🛡️ [HARD COGNITIVE ESCAPE ACTIVE]: Step {step + 1} is under Hard Cognitive Escape (until step {hard_escape_until_step}). Bypassing all cache shortcuts and forcing raw LLM inference.")
            else:
                cached_actions, matched_flow = get_cached_actions(page.url, page_text)
                if cached_actions:
                    log(f"📋 [CACHE HIT]: Injecting execution locators for '{matched_flow}' directly. Skipping LLM inference.")
                    command = {
                        "thought": f"Using cached sequence for {matched_flow} flow directly.",
                        "actions": cached_actions,
                        "is_final": False
                    }
                    used_cache = True
                    cache_type = "flow"
                    cache_key = matched_flow
                else:
                    # Pre-flight layout coordinate check
                    layout_actions, matched_component = check_preflight_layout(user_goal, page.url, page_text, live_elements)
                    if layout_actions:
                        command = {
                            "thought": "Resolving structural component coordinates via layout blueprint map directly.",
                            "actions": layout_actions,
                            "is_final": False
                        }
                        used_cache = True
                        cache_type = "layout"
                        cache_key = matched_component
                    
            if command is None:
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


            # 4. Execute the planned interactions sequentially
            log(f"🛠️ Sequence Executor: Processing {len(actions_list)} planned action(s)...")
            actions_executed_successfully = True
            for idx, act in enumerate(actions_list):
                act_type = str(act.get('action', '')).lower().strip()
                act_selector = act.get('selector') or act.get('target_selector') or act.get('css_selector')
                act_text = act.get('text_to_type') or act.get('text') or act.get('value') or ''
                act_select_val = act.get('value_to_select') or act.get('value') or act.get('text_to_type') or ''
                act_wait = act.get('wait_time_ms')
                # Spatial container scoping check:
                if act_selector:
                    try:
                        has_visible_modal = await page.evaluate('''() => {
                            const modal = document.querySelector('.modal-container, .modal, [class*="modal"], [class*="Modal"]');
                            if (modal) {
                                const rect = modal.getBoundingClientRect();
                                return rect.width > 0 && rect.height > 0 && window.getComputedStyle(modal).display !== 'none';
                            }
                            return false;
                        }''')
                        if has_visible_modal and not any(m in str(act_selector).lower() for m in [".modal", "modal", "dialog"]):
                            log(f"🔒 [SPATIAL CONTAINER SCOPING]: Active modal detected. Scoping selector '{act_selector}' to visible modal parent.")
                            act_selector = f"[class*=\"modal\"]:visible >> {act_selector}"
                    except Exception:
                        pass

                # Strict Mode Mitigation check:
                if act_selector:
                    try:
                        count = await page.locator(act_selector).count()
                        if count > 1 and ">> nth=" not in act_selector:
                            log(f"⚠️ [STRICT MODE MITIGATION]: Selector '{act_selector}' matches {count} elements. Automatically scoping to first match (>> nth=0).")
                            act_selector = f"{act_selector} >> nth=0"
                    except Exception:
                        pass

                # Semantic Parent Link Interceptor for sidebar & menu navigation:
                if act_type == 'click' and act_selector:
                    import re
                    match_raw_text = re.search(r'^text=["\']([^"\']+)["\'](?:\s*>>\s*nth=\d+)?$', act_selector.strip())
                    if match_raw_text:
                        target_text = match_raw_text.group(1)
                        if any(nav_kw in target_text.lower() for nav_kw in ["leave", "reimbursement", "salary", "payroll", "employee", "dashboard", "setting", "report", "management"]):
                            semantic_sel = f":is(a, button, li, [role=\"menuitem\"], .menu-item):has-text(\"{target_text}\")"
                            try:
                                if await page.locator(semantic_sel).count() > 0:
                                    log(f"🔗 [SEMANTIC PARENT LINKING]: Converted raw text selector '{act_selector}' to interactive parent selector '{semantic_sel}'")
                                    act_selector = semantic_sel
                            except Exception:
                                pass

                # Extra Work Cross-Functional Routing Interceptor:
                if any(kw in (user_goal or "").lower() for kw in ["extra work", "extra hours", "claim extra", "log extra"]):
                    if act_type == 'click' and act_selector and not any(r in str(act_selector).lower() for r in ["reimbursement"]):
                        try:
                            reimb_loc = page.locator(':is(a, button, li, [role="menuitem"], .menu-item):has-text("Reimbursement")')
                            if await reimb_loc.count() > 0 and await reimb_loc.first.is_visible(timeout=500):
                                log(f"🔀 [REIMBURSEMENT ROUTING INTERCEPTOR]: Extra Work objective detected. Re-routing click action to 'Reimbursement' sidebar link.")
                                act_selector = ':is(a, button, li, [role="menuitem"], .menu-item):has-text("Reimbursement")'
                        except Exception:
                            pass

                log(f"  [{idx + 1}/{len(actions_list)}] Action: {act_type.upper()} on selector '{act_selector}'")

                try:
                    if act_type == 'type':
                        try:
                            await page.wait_for_selector(act_selector, state="visible", timeout=1500)
                            element = page.locator(act_selector)
                            await element.scroll_into_view_if_needed()
                            await element.focus()
                            await element.fill(act_text)
                        except Exception as e_type_stale:
                            if any(err_kw in str(e_type_stale).lower() for err_kw in ["stale", "detached", "intercepts pointer", "not attached", "target closed"]):
                                log(f"⚠️ [STABILITY GUARD]: Stale element or pointer interception detected on '{act_selector}'. Re-scraping live DOM tree to auto-heal locator reference...")
                                fresh_elems = await browser_engine.extract_interactive_elements()
                                for el in fresh_elems:
                                    if el.get("computed_selector") and (act_text.lower() in str(el.get("text", "")).lower() or el.get("tag") in ["input", "textarea"]):
                                        act_selector = el["computed_selector"]
                                        break
                                await page.wait_for_selector(act_selector, state="visible", timeout=1500)
                                await page.locator(act_selector).fill(act_text, force=True)
                            else:
                                raise e_type_stale

                        await page.keyboard.press("Tab") # Shift focus to trigger React change handlers
                        await asyncio.sleep(0.3) # 300ms layout stabilization sleep post form-filling
                    elif act_type == 'click':
                        try:
                            await page.wait_for_selector(act_selector, state="visible", timeout=1500)
                        except Exception as e_vis:
                            if any(err_kw in str(e_vis).lower() for err_kw in ["stale", "detached", "intercepts pointer", "not attached"]):
                                log(f"⚠️ [STABILITY GUARD]: Stale element reference detected on '{act_selector}'. Auto-healing locator...")
                                fresh_elems = await browser_engine.extract_interactive_elements()
                                if fresh_elems:
                                    act_selector = fresh_elems[0].get("computed_selector", act_selector)
                        
                        is_nav_click = (
                            'href' in str(act_selector).lower() or
                            'text=' in str(act_selector).lower() or
                            'button' in str(act_selector).lower() or
                            'a' in str(act_selector).lower()
                        )
                        
                        click_options = {}
                        if force_next_clicks:
                            log(f"    🛡️ Interception Recovery Bypass: programmatically forcing click on selector '{act_selector}'")
                            click_options["force"] = True

                        if is_nav_click:
                            try:
                                async with page.expect_navigation(wait_until="load", timeout=1500):
                                    try:
                                        await page.click(act_selector, timeout=1500, **click_options)
                                    except Exception as e_click:
                                        log(f"  ⚠️ Direct click on '{act_selector}' failed or was intercepted: {e_click}. Retrying with force=True...")
                                        await page.click(act_selector, force=True, timeout=1500)
                            except Exception:
                                pass
                        else:
                            try:
                                await page.click(act_selector, timeout=1500, **click_options)
                            except Exception as e_click:
                                log(f"  ⚠️ Direct click on '{act_selector}' failed or was intercepted: {e_click}. Retrying with force=True...")
                                try:
                                    await page.click(act_selector, force=True, timeout=1500)
                                except Exception:
                                    pass
                                    
                        try:
                            await page.wait_for_load_state("load", timeout=4000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                    elif act_type == 'select':
                        log(f"    ⚙️ Selecting option '{act_select_val}'")
                        try:
                            await page.wait_for_selector(act_selector, state="visible", timeout=1500)
                            element = page.locator(act_selector)
                            await element.scroll_into_view_if_needed()
                            await element.select_option(value=act_select_val)
                        except Exception as e_sel_stale:
                            log(f"⚠️ [STABILITY GUARD]: Stale selector on dropdown '{act_selector}': {e_sel_stale}. Retrying select with force...")
                            try:
                                await page.locator(act_selector).select_option(label=act_select_val)
                            except Exception:
                                pass
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(0.3)
                    elif act_type == 'wait':
                        sleep_s = float(act_wait or 1000) / 1000.0
                        log(f"    ⏳ Sleeping for {sleep_s}s...")
                        await asyncio.sleep(sleep_s)
                    elif act_type == 'press_key':
                        log(f"    🎹 Pressing key '{act_text or 'Enter'}' on selector '{act_selector}'")
                        if act_selector:
                            await page.wait_for_selector(act_selector, state="visible", timeout=1500)
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
                        # Check if action targeted semantic cells or grid cells
                        if any(gk in str(act_selector).lower() for gk in ["cell", "role=", "grid", "has-text"]):
                            from core.test_cache_manager import save_application_knowledge, load_application_knowledge
                            knowledge = load_application_knowledge()
                            insight_desc = f"Resolved complex grid/table navigation on URL path '{page.url}' by using semantic cell target selector: '{act_selector}'."
                            if insight_desc not in knowledge:
                                knowledge.append(insight_desc)
                                save_application_knowledge(knowledge)
                                log(f"💾 [KNOWLEDGE APPENDED]: Saved grid targeting insight: '{insight_desc}'")

                    # If custom wait is specified, execute it
                    if act_wait and act_type != 'wait':
                        await asyncio.sleep(float(act_wait) / 1000.0)

                except Exception as e_act:
                    log(f"  ❌ Sequence Action failed: {e_act}")
                    err_msg = str(e_act).lower()
                    if "intercepts pointer events" in err_msg or "click intercepted" in err_msg:
                        log("⚠️ [INTERCEPTION DETECTED]: Pointer interception occurred during action execution. Gracefully redirecting current step back to the AI analyzer using the updated Overlay Rules context...")
                        dom_snap = json.dumps(live_elements, indent=2)
                        interception_warning = (
                            f"Playwright Pointer Interception Exception: Your action on selector '{act_selector}' was blocked by a dynamic overlay/modal.\n"
                            f"Active DOM snapshot elements list:\n{dom_snap}\n"
                            "Please analyze this DOM tree, apply the Overlay Rules, and return the exact selector (text-based or role-based selector scoped directly to the visible modal) to resolve the overlay."
                        )
                    if act_selector:
                        consecutive_failures[act_selector] = consecutive_failures.get(act_selector, 0) + 1
                        log(f"  ⚠️ Selector '{act_selector}' has failed consecutively {consecutive_failures[act_selector]} time(s).")
                        if consecutive_failures[act_selector] >= 2:
                            log(f"❌ [CRITICAL LIMIT REACHED]: Selector '{act_selector}' failed twice consecutively. Terminating execution.")
                            raise RuntimeError(f"Step failed twice consecutively on selector '{act_selector}'")
                    log("  🔄 Stopping sequence execution early to allow self-healing re-analysis.")
                    actions_executed_successfully = False
                    break

            if not cached_actions and actions_list and actions_executed_successfully:
                try:
                    save_cached_actions(page.url, page_text, actions_list)
                except Exception as e_cache:
                    log(f"⚠️ Failed to cache actions: {e_cache}")
                    
            if actions_list and actions_executed_successfully:
                try:
                    update_layout_map_from_actions(page.url, page_text, actions_list, live_elements)
                except Exception as e_layout:
                    log(f"⚠️ Failed to update layout map: {e_layout}")

            if actions_executed_successfully:
                after_url = page.url
                new_elements = await browser_engine.extract_interactive_elements()
                after_repr = "".join(f"{el.get('computed_selector')}:{el.get('text')}" for el in new_elements)
                after_dom_hash = hashlib.md5(after_repr.encode('utf-8')).hexdigest()
                try:
                    after_focus = await page.evaluate("() => document.activeElement ? document.activeElement.tagName + '.' + document.activeElement.className + '#' + document.activeElement.id : ''")
                except Exception:
                    after_focus = ""
                
                # Check if state remains completely unchanged
                if before_url == after_url and before_dom_hash == after_dom_hash and before_focus == after_focus:
                    consecutive_unchanged_count += 1
                    total_unchanged_steps += 1
                    log(f"⚠️ [ANTI-LOOP GATES]: Detected unchanged viewport state (Consecutive: {consecutive_unchanged_count}/2 | Total: {total_unchanged_steps}/5).")
                else:
                    consecutive_unchanged_count = 0
                    
                if consecutive_unchanged_count >= 2:
                    log(f"🚨 [ANTI-LOOP GATES]: Viewport remained unchanged for 2 consecutive steps. Invalidating stale cache key and engaging Hard Cognitive Escape for the next 3 steps...")
                    from core.test_cache_manager import invalidate_flow_cache, invalidate_layout_map
                    if cache_type == "flow" and cache_key:
                        invalidate_flow_cache(cache_key)
                    elif cache_type == "layout" and cache_key:
                        invalidate_layout_map(cache_key)
                    
                    # Engage Hard Cognitive Escape for 3 steps
                    hard_escape_until_step = step + 4
                    log(f"🔒 [HARD COGNITIVE ESCAPE ENGAGED]: Cache shortcuts strictly blocked through step {hard_escape_until_step}. Forcing raw LLM inference.")
                    consecutive_unchanged_count = 0

                if total_unchanged_steps >= 5:
                    log(f"❌ [HARD STUCK TERMINATION]: Test case spent {total_unchanged_steps} steps without altering browser URL or DOM layout. Marking case as INCOMPLETE/FAILED and skipping forward.")
                    is_final = False
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
        sanitized_run_id = "".join([c if c.isalnum() or c in ['_', '-'] else '_' for c in run_id])
        screenshot_path = f"screenshots/run_{sanitized_run_id}_step_{step}_{timestamp_s}.png"

        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            log(f"✅ Visual execution proof saved cleanly to: {screenshot_path}")
            
            # Maintain a duplicate copy at run_{run_id}_final.png for UI reference
            final_copy = f"screenshots/run_{sanitized_run_id}_final.png"
            import shutil
            shutil.copy(screenshot_path, final_copy)
        except Exception as e_ss:
            log(f"⚠️ Failed to capture screenshot: {e_ss}")
            screenshot_path = None

        if is_final:
            log(f"🎉 SUCCESS: Concurrency run '{run_id}' form-filling execution milestone reached cleanly!")
            from core.test_cache_manager import commit_pending_cache
            commit_pending_cache()
        else:
            log(f"⚠️ WARNING: Concurrency run '{run_id}' completed without reaching the final milestone.")
            from core.test_cache_manager import clear_pending_cache
            clear_pending_cache()

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
            "screenshot_path": f"screenshots/run_{sanitized_run_id}_final.png" if os.path.exists(f"screenshots/run_{sanitized_run_id}_final.png") else None,
            "avg_llm_time": avg_llm,
            "avg_scrape_time": avg_scrape,
            "telemetry_report": telemetry_report,
            "llm_times": llm_times,
            "scrape_times": scrape_times
        }

        log(f"🏁 [{run_id}] Execution Finished | Status: {summary['status']} | Steps: {step} | Duration: {duration}s | Avg LLM: {avg_llm:.2f}s | Avg Scrape: {avg_scrape:.2f}s")
        return summary

    except Exception as e:
        from core.test_cache_manager import clear_pending_cache
        clear_pending_cache()
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