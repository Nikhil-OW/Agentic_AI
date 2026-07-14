import io
import sys
import os
import glob
import asyncio
import streamlit as st
import pandas as pd
# Append the project root to sys.path to resolve core and utils modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.agent import run_autonomous_navigator, load_unified_config

# Page configuration for a wide developer workspace
st.set_page_config(
    page_title="Parallel AI Automation Workspace",
    page_icon="🤖",
    layout="wide"
)

# Custom orange/blue theme styling for premium aesthetics
st.markdown("""
    <style>
        /* Modern font and background setups */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }
        
        .main-header {
            font-size: 2.3rem;
            font-weight: 700;
            color: #E86B24;
            margin-bottom: 0.2rem;
            letter-spacing: -0.5px;
        }
        .subheader {
            font-size: 1.05rem;
            color: #5C6B73;
            margin-bottom: 2rem;
            font-weight: 400;
        }
        
        /* Premium custom buttons */
        .stButton>button {
            background: linear-gradient(135deg, #E86B24 0%, #C7561B 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 0.6rem 1.4rem !important;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 4px 6px rgba(232, 107, 36, 0.15);
        }
        .stButton>button:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 12px rgba(232, 107, 36, 0.25);
            background: linear-gradient(135deg, #C7561B 0%, #A34212 100%) !important;
        }
        
        /* Secondary action buttons */
        div[data-testid="column"] button[key*="del"] {
            background: #FAD2E1 !important;
            color: #9B2226 !important;
            padding: 0.3rem 0.8rem !important;
            font-size: 0.9rem !important;
            box-shadow: none !important;
        }
        div[data-testid="column"] button[key*="del"]:hover {
            background: #F5B3CB !important;
            transform: none !important;
        }
        
        .sidebar-header {
            font-weight: 700;
            color: #1D3F75;
            font-size: 1.2rem;
            margin-bottom: 1rem;
            letter-spacing: -0.2px;
        }
        
        /* Section styling */
        .table-header {
            font-weight: 600;
            color: #1D3F75;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #E2E8F0;
            margin-bottom: 0.8rem;
        }
    </style>
""", unsafe_allow_html=True)

# App titles
st.markdown('<div class="main-header">🤖 Parallel AI Automation Workspace</div>', unsafe_allow_html=True)
st.markdown('<div class="subheader">Parallel AI Test Automation Suite with Telemetry Logging</div>', unsafe_allow_html=True)

# 1. Sidebar Config Override Settings
with st.sidebar:
    st.markdown('<div class="sidebar-header">⚙️ Environment Settings</div>', unsafe_allow_html=True)
    
    # Load default configs
    config = load_unified_config()
    default_steps = config.get("environment", {}).get("max_retry_steps", 15)
    
    max_steps = st.number_input("Max Execution Steps", min_value=1, max_value=30, value=int(default_steps))
    
    browser_mode = st.selectbox("Browser Visibility", ["Headed (Visible Browser)", "Headless (Run in Background)"], index=0)
    headless = True if browser_mode == "Headless (Run in Background)" else False

    st.markdown("---")
    st.markdown('<div class="sidebar-header">🔐 Admin Credentials</div>', unsafe_allow_html=True)
    static_user = st.text_input("Username / Email", value=config.get("test_data", {}).get("username", "nafreen@gmail.com"))
    static_pass = st.text_input("Password", value=config.get("test_data", {}).get("password", "nafreen@123"), type="password")

    # Synchronize streamlit choices back to the config structure
    config["environment"]["max_retry_steps"] = max_steps
    config["environment"]["headless"] = headless
    config["test_data"]["username"] = static_user
    config["test_data"]["password"] = static_pass

# 2. Parallel Target Execution Workspace
if "targets" not in st.session_state:
    st.session_state.targets = [
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

st.markdown("### 🎯 Multi-Application Concurrency Targets")
st.write("Manage and assign natural language objetivos across multiple application environments concurrently:")

# Tabular Spreadsheet Header Row for clean targets input grid
col_h1, col_h2, col_h3, col_h4 = st.columns([2, 3, 5, 1])
with col_h1:
    st.markdown('<div class="table-header">App Target Name</div>', unsafe_allow_html=True)
with col_h2:
    st.markdown('<div class="table-header">Target URL Override</div>', unsafe_allow_html=True)
with col_h3:
    st.markdown('<div class="table-header">Goal Objective / User Intent</div>', unsafe_allow_html=True)
with col_h4:
    st.markdown('<div class="table-header">Action</div>', unsafe_allow_html=True)

updated_targets = []
for idx, target in enumerate(st.session_state.targets):
    col1, col2, col3, col4 = st.columns([2, 3, 5, 1])
    with col1:
        name = st.text_input("App Target Name", value=target["name"], key=f"target_name_{idx}", label_visibility="collapsed")
    with col2:
        url = st.text_input("Target URL Override", value=target["url"], key=f"target_url_{idx}", label_visibility="collapsed")
    with col3:
        goal = st.text_input("Goal Objective", value=target["goal"], key=f"target_goal_{idx}", label_visibility="collapsed")
    with col4:
        delete_clicked = st.button("🗑️ Delete", key=f"del_{idx}")
    
    if not delete_clicked:
        updated_targets.append({"name": name, "url": url, "goal": goal})

st.session_state.targets = updated_targets

# Action bar below the table grid
col_add, col_run = st.columns([1, 1])
with col_add:
    if st.button("➕ Add App Target"):
        st.session_state.targets.append({
            "name": f"Target App {len(st.session_state.targets) + 1}",
            "url": "https://example.com",
            "goal": "Verify the page contains elements."
        })
        st.rerun()

with col_run:
    run_test_suite = st.button("🚀 Run Test Suite")

if run_test_suite:
    if not st.session_state.targets:
        st.warning("⚠️ No target applications configured. Please add at least one target.")
    else:
        st.markdown("---")
        st.markdown("### 📡 Test Suite Telemetry Dashboard")
        
        # Allocate dynamic tabs for each execution
        tab_names = [f"🖥️ {t['name']}" for t in st.session_state.targets]
        tabs = st.tabs(tab_names)
        
        log_placeholders = []
        status_placeholders = []
        telemetry_placeholders = []
        image_placeholders = []
        
        for idx, tab in enumerate(tabs):
            with tab:
                st.markdown(f"**Target URL**: `{st.session_state.targets[idx]['url']}` | **Objective**: *\"{st.session_state.targets[idx]['goal']}\"*")
                
                # Split screen layout: Left for Status/Visual, Right for logs
                col_left, col_right = st.columns([4, 6])
                with col_left:
                    status_placeholder = st.empty()
                    telemetry_placeholder = st.empty()
                    image_placeholder = st.empty()
                with col_right:
                    st.markdown("💻 **Execution Output Console**")
                    log_placeholder = st.empty()
                
                status_placeholders.append(status_placeholder)
                telemetry_placeholders.append(telemetry_placeholder)
                log_placeholders.append(log_placeholder)
                image_placeholders.append(image_placeholder)
        
        # Dynamic logger callbacks
        log_buffers = [[] for _ in st.session_state.targets]
        
        def make_log_callback(index):
            def callback(msg):
                log_buffers[index].append(msg)
                log_placeholders[index].code("\n".join(log_buffers[index]))
            return callback
        
        async def execute_suite():
            tasks = []
            for idx, target in enumerate(st.session_state.targets):
                run_id = target["name"].lower().replace(" ", "_")
                status_placeholders[idx].info("⏳ Initializing browser...")
                
                log_cb = make_log_callback(idx)
                
                # Dynamic task definition with deepcopy for complete memory isolation
                import copy
                config_copy = copy.deepcopy(config)
                tasks.append(
                    run_autonomous_navigator(
                        config_registry=config_copy,
                        target_url=target["url"],
                        user_goal=target["goal"],
                        run_id=run_id,
                        log_callback=log_cb
                    )
                )
            
            # Fire concurrent loop
            status_summary = st.info("🧠 Driving concurrent perception-action loops...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            status_summary.empty()
            return results
        
        # Run async loop synchronously inside Streamlit
        results = asyncio.run(execute_suite())
        
        # 3. Post-run Artifact and Screenshot renders
        for idx, res in enumerate(results):
            target_name = st.session_state.targets[idx]['name']
            if isinstance(res, Exception):
                status_placeholders[idx].error(f"❌ Execution crashed with exception: {res}")
            elif res.get("is_final"):
                status_placeholders[idx].success(f"🎉 Success: Objective completed in {res['total_steps']} steps!")
                if res.get("telemetry_report"):
                    telemetry_placeholders[idx].code(res.get("telemetry_report"))
                screenshot_path = res.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    image_placeholders[idx].image(
                        screenshot_path,
                        caption=f"Visual Proof: {target_name}",
                        use_container_width=True
                    )
            else:
                status_placeholders[idx].warning(f"⚠️ Warning: Session finished without meeting target state (Steps: {res.get('total_steps')})")
                if res.get("telemetry_report"):
                    telemetry_placeholders[idx].code(res.get("telemetry_report"))
                screenshot_path = res.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    image_placeholders[idx].image(
                        screenshot_path,
                        caption=f"Visual State proof: {target_name}",
                        use_container_width=True
                    )
        
        # 4. ENTERPRISE AUTOMATION STATUS REPORT
        st.markdown("---")
        st.markdown("### 📊 TEST SUITE EXECUTION SUMMARY")
        
        report_data = []
        for idx, res in enumerate(results):
            target = st.session_state.targets[idx]
            if isinstance(res, Exception):
                report_data.append({
                    "Target App": target["name"],
                    "URL": target["url"],
                    "Status": "CRASHED/ERROR",
                    "Steps Taken": 0,
                    "Duration (s)": 0.0,
                    "Final State": False,
                    "Screenshot Path": "None"
                })
            else:
                report_data.append({
                    "Target App": target["name"],
                    "URL": res.get("target_url"),
                    "Status": res.get("status"),
                    "Steps Taken": res.get("total_steps"),
                    "Duration (s)": res.get("duration_seconds"),
                    "Final State": res.get("is_final"),
                    "Screenshot Path": res.get("screenshot_path") or "None"
                })
        
        df = pd.DataFrame(report_data)
        st.dataframe(df, use_container_width=True)
        
        # Consolidated Matrix console output printing for verification checks
        print("\n" + "="*50)
        print("📊 TEST SUITE EXECUTION SUMMARY")
        print("="*50)
        print(df.to_markdown(index=False))
        print("="*50 + "\n")
        
        st.markdown("#### Execution Summary Matrix (Markdown)")
        st.code(df.to_markdown(index=False), language="markdown")

        # 5. Consolidated Performance Telemetry Reports
        st.markdown("---")
        st.markdown("### 📊 CONSOLIDATED PERFORMANCE TELEMETRY REPORTS")
        for idx, res in enumerate(results):
            if not isinstance(res, Exception) and res.get("telemetry_report"):
                st.markdown(f"#### 🖥️ {st.session_state.targets[idx]['name']}")
                st.code(res.get("telemetry_report"))
