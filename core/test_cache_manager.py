import os
import json
import re

CACHE_ROOT = ".testcache"
_dynamic_mode = False
_pending_cache_actions = []
_pending_layouts = []

def get_cache_dir():
    jira_key = os.environ.get("ACTIVE_JIRA_KEY", "DUMMY")
    # Clean JIRA key for filesystem safety
    jira_key = re.sub(r'[^a-zA-Z0-9_\-]', '', jira_key)
    if not jira_key:
        jira_key = "DUMMY"
    return os.path.join(CACHE_ROOT, jira_key)

def init_cache():
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)

def check_and_init_cache(jira_key: str = None) -> bool:
    if jira_key:
        clean_key = re.sub(r'[^a-zA-Z0-9_\-]', '', jira_key)
        if clean_key:
            os.environ["ACTIVE_JIRA_KEY"] = clean_key
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        set_dynamic_mode(True)
        return False
    else:
        set_dynamic_mode(False)
        return True

def set_dynamic_mode(val: bool):
    global _dynamic_mode
    _dynamic_mode = val
    if val:
        print("💡 [DYNAMIC INTERPRETATION MODE]: Active Jira Key cache directory does not exist. Bypassing cache files.")

def get_dynamic_mode() -> bool:
    global _dynamic_mode
    return _dynamic_mode

def commit_pending_cache():
    cache_dir = get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    
    # Save cache actions
    for url, text, actions, flow_name in _pending_cache_actions:
        save_cached_actions_to_disk(url, text, actions, flow_name)
    _pending_cache_actions.clear()
    
    # Save layouts
    for url, text, actions_list, live_elements in _pending_layouts:
        update_layout_map_from_actions_to_disk(url, text, actions_list, live_elements)
    _pending_layouts.clear()
    print(f"💾 [DYNAMIC MODE COMMITTED]: Serialized coordinates and flow blueprints to '{cache_dir}'.")

def clear_pending_cache():
    _pending_cache_actions.clear()
    _pending_layouts.clear()

def get_cached_actions(page_url, page_text):
    if get_dynamic_mode():
        return None, None
        
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return None, None
        
    for filename in os.listdir(cache_dir):
        if not filename.endswith(".json") or filename == "app_layout_map.json":
            continue
        filepath = os.path.join(cache_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("key", {})
            url_contains = key.get("url_contains")
            text_contains = key.get("text_contains")
            
            # Match URL
            if url_contains and url_contains.lower() not in page_url.lower():
                continue
            
            # Match text
            if text_contains and text_contains.lower() not in page_text.lower():
                continue
                
            # If we matched everything in the key, return actions and flow name
            flow_name = filename[:-5]
            return data.get("actions"), flow_name
        except Exception:
            continue
    return None, None

def save_cached_actions(page_url, page_text, actions, flow_name=None):
    if get_dynamic_mode():
        _pending_cache_actions.append((page_url, page_text, actions, flow_name))
        print(f"📋 [DYNAMIC MODE QUEUED]: Queued sequence for {flow_name or 'dynamic_flow'} to memory.")
        return
    save_cached_actions_to_disk(page_url, page_text, actions, flow_name)

def save_cached_actions_to_disk(page_url, page_text, actions, flow_name=None):
    init_cache()
    if not actions:
        return
        
    if not flow_name:
        # Infer flow name dynamically
        page_text_lower = page_text.lower()
        if "login" in page_url.lower():
            flow_name = "navigation_login"
        elif "lop warning" in page_text_lower or "lop" in page_text_lower:
            flow_name = "lop_warning"
        elif "leave" in page_text_lower:
            flow_name = "navigation_leave_mgmt"
        else:
            first_sel = ""
            if len(actions) > 0:
                first_sel = str(actions[0].get("selector") or "").strip()
                first_sel = re.sub(r'[^a-zA-Z0-9]', '_', first_sel).strip("_")
            flow_name = f"flow_{first_sel[:30]}" if first_sel else "flow_generic"
            
    # Clean flow name for filesystem safety
    flow_name = re.sub(r'[^a-zA-Z0-9_\-]', '', flow_name)
    cache_dir = get_cache_dir()
    filepath = os.path.join(cache_dir, f"{flow_name}.json")
    
    # Construct a key that uniquely identifies this page state
    url_contains = ""
    from urllib.parse import urlparse
    parsed = urlparse(page_url)
    if parsed.path and parsed.path != "/":
        url_contains = parsed.path
    else:
        url_contains = page_url
        
    text_contains = ""
    page_text_lower = page_text.lower()
    if "lop warning" in page_text_lower:
        text_contains = "LOP Warning"
    elif "leave request history" in page_text_lower:
        text_contains = "Leave Request History"
    elif "leave request" in page_text_lower:
        text_contains = "Leave Request"
    elif "dashboard" in page_text_lower:
        text_contains = "Dashboard"
    elif "login" in page_text_lower:
        text_contains = "Login"
    else:
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
        if lines:
            text_contains = lines[0][:50]
            
    data = {
        "key": {
            "url_contains": url_contains,
            "text_contains": text_contains
        },
        "actions": actions
    }
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"💾 [CACHE STORED]: Saved sequence to {filepath}")
    except Exception as e:
        print(f"⚠️ Failed to write to cache file {filepath}: {e}")

def load_layout_map() -> dict:
    cache_dir = get_cache_dir()
    layout_map_file = os.path.join(cache_dir, "app_layout_map.json")
    if os.path.exists(layout_map_file):
        try:
            with open(layout_map_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_layout_map(layout_map: dict):
    init_cache()
    cache_dir = get_cache_dir()
    layout_map_file = os.path.join(cache_dir, "app_layout_map.json")
    try:
        with open(layout_map_file, "w", encoding="utf-8") as f:
            json.dump(layout_map, f, indent=2)
    except Exception:
        pass

def check_preflight_layout(user_goal: str, page_url: str, page_text: str, live_elements: list) -> tuple:
    if get_dynamic_mode():
        return None, None
        
    layout_map = load_layout_map()
    user_goal_lower = user_goal.lower()
    from urllib.parse import urlparse
    current_path = urlparse(page_url).path or "/"
    
    for component, data in layout_map.items():
        if component.lower() in user_goal_lower or any(kw in user_goal_lower for kw in component.lower().split()):
            target_path = data.get("target_path") or "/"
            if target_path.lower() != current_path.lower():
                continue
                
            selector_id = data.get("selector_id")
            element_text = data.get("element_text")
            
            for el in live_elements:
                computed = el.get("computed_selector") or ""
                el_id = el.get("id") or ""
                text = el.get("text") or ""
                
                if (selector_id and (selector_id == computed or selector_id == el_id or selector_id in computed)) or \
                   (element_text and (element_text.lower() in text.lower())):
                    print(f"📋 [LAYOUT MAP HIT]: Resolving component '{component}' coordinates dynamically. Skipping LLM.")
                    return [{
                        "action": "click",
                        "selector": computed,
                        "text_to_type": None,
                        "value_to_select": None
                    }], component
    return None, None

def update_layout_map_from_actions(page_url: str, page_text: str, actions_list: list, live_elements: list = None):
    if get_dynamic_mode():
        _pending_layouts.append((page_url, page_text, actions_list, live_elements))
        print("📋 [DYNAMIC MODE QUEUED]: Queued layout map updates to memory.")
        return
    update_layout_map_from_actions_to_disk(page_url, page_text, actions_list, live_elements)

def update_layout_map_from_actions_to_disk(page_url: str, page_text: str, actions_list: list, live_elements: list = None):
    from datetime import datetime
    layout_map = load_layout_map()
    updated = False
    
    for act in actions_list:
        act_type = act.get("action")
        selector = act.get("selector") or ""
        
        component_name = None
        selector_lower = selector.lower()
        page_text_lower = page_text.lower()
        
        if "leave management" in selector_lower or "leave management" in page_text_lower:
            component_name = "Leave Management"
        elif "leaves" in selector_lower or "leaves" in page_text_lower:
            component_name = "Leave Management"
        elif "salary" in selector_lower or "salary" in page_text_lower:
            component_name = "Salary Details"
        elif "payroll" in selector_lower or "payroll" in page_text_lower:
            component_name = "Payroll Processing"
        elif "ok" in selector_lower and ("lop" in selector_lower or "lop" in page_text_lower):
            component_name = "LOP Warning"
            
        if component_name and act_type == "click":
            from urllib.parse import urlparse
            parsed = urlparse(page_url)
            target_path = parsed.path or "/"
            
            selector_id = ""
            parent_container = ""
            element_text = ""
            
            if live_elements:
                for el in live_elements:
                    if el.get("computed_selector") == selector or el.get("text") == selector:
                        selector_id = el.get("id") or ""
                        parent_container = el.get("class") or ""
                        element_text = el.get("text") or ""
                        break
                        
            if not element_text and "text=" in selector:
                element_text = selector.replace("text=", "").replace('"', '')
            if not selector_id and selector.startswith("#"):
                selector_id = selector
                
            # Add spatial text descriptors
            selector_id = act.get("selector_id") or selector_id or selector
            parent_container = act.get("parent_scope") or parent_container
            element_text = act.get("element_text") or element_text
                
            layout_map[component_name] = {
                "selector_id": selector_id,
                "parent_container": parent_container,
                "target_path": target_path,
                "element_text": element_text or component_name,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            updated = True
            
    if updated:
        save_layout_map(layout_map)
        cache_dir = get_cache_dir()
        layout_map_file = os.path.join(cache_dir, "app_layout_map.json")
        print(f"💾 [LAYOUT MAP UPDATED]: Saved component coordinates to {layout_map_file}")

def invalidate_flow_cache(flow_name: str):
    cache_dir = get_cache_dir()
    filepath = os.path.join(cache_dir, f"{flow_name}.json")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"🗑️ [CACHE INVALIDATED]: Deleted stale cache file {filepath}")
        except Exception as e:
            print(f"⚠️ Failed to delete cache file {filepath}: {e}")

def invalidate_layout_map(component_name: str):
    layout_map = load_layout_map()
    if component_name in layout_map:
        try:
            del layout_map[component_name]
            save_layout_map(layout_map)
            print(f"🗑️ [LAYOUT INVALIDATED]: Removed stale component '{component_name}' from app_layout_map.json")
        except Exception as e:
            print(f"⚠️ Failed to remove component '{component_name}' from layout map: {e}")

def load_application_knowledge() -> list[str]:
    filepath = os.path.join(CACHE_ROOT, "application_knowledge.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_application_knowledge(knowledge_list: list[str]):
    if not os.path.exists(CACHE_ROOT):
        os.makedirs(CACHE_ROOT, exist_ok=True)
    filepath = os.path.join(CACHE_ROOT, "application_knowledge.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(knowledge_list, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to write application knowledge file: {e}")
