import io
import sys
import os
import glob
import asyncio
import streamlit as st
import pandas as pd
from navigator_agent import run_autonomous_navigator, load_unified_config

# Page configuration
st.set_page_config(
    page_title="urBuddi MCP Autonomous QA Workspace",
    page_icon="🤖",
    layout="wide"
)

# Custom orange/blue theme styling for premium aesthetics
st.markdown("""
    <style>
        .main-header {
            font-size: 2.2rem;
            font-weight: 700;
            color: #E86B24;
            margin-bottom: 0.5rem;
        }
        .subheader {
            font-size: 1.1rem;
            color: #1D3F75;
            margin-bottom: 2rem;
        }
        .stButton>button {
            background-color: #E86B24 !important;
            color: white !important;
            border-radius: 4px;
            font-weight: 600;
        }
        .stButton>button:hover {
            background-color: #c7561b !important;
            border-color: #c7561b !important;
        }
        .sidebar-header {
            font-weight: 700;
            color: #1D3F75;
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }
        .card {
            background-color: #f7f9fc;
            padding: 1rem;
            border-radius: 6px;
            border-left: 5px solid #E86B24;
            margin-bottom: 0.5rem;
        }
    </style>
""", unsafe_allow_html=True)

# App titles
st.markdown('<div class="main-header">🤖 urBuddi QA Host Workspace</div>', unsafe_allow_html=True)
st.markdown('<div class="subheader">MCP-Style Conversational QA Client with Telemetry Logging</div>', unsafe_allow_html=True)

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
st.write("Configure individual target applications, URLs, and natural language objectives for parallel execution:")

updated_targets = []
for idx, target in enumerate(st.session_state.targets):
    with st.container():
        st.markdown(f'<div class="card"><strong>App Target #{idx+1}: {target["name"]}</strong></div>', unsafe_allow_html=True)
        col1, col2, col3, col4 = st.columns([2, 3, 5, 1])
        with col1:
            name = st.text_input(f"App Target Name", value=target["name"], key=f"target_name_{idx}")
        with col2:
            url = st.text_input(f"Target URL Override", value=target["url"], key=f"target_url_{idx}")
        with col3:
            goal = st.text_input(f"Goal Objective", value=target["goal"], key=f"target_goal_{idx}")
        with col4:
            st.write("") # spacing
            st.write("") # spacing
            delete_clicked = st.button("🗑️ Delete", key=f"del_{idx}")
        
        if not delete_clicked:
            updated_targets.append({"name": name, "url": url, "goal": goal})

st.session_state.targets = updated_targets

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
    run_parallel = st.button("🚀 Run Parallel Test Suite")

if run_parallel:
    if not st.session_state.targets:
        st.warning("⚠️ No target applications configured. Please add at least one target.")
    else:
        st.markdown("---")
        st.markdown("### 📡 Parallel Execution Telemetry Stream")
        
        # Allocate dynamic tabs for each execution
        tab_names = [f"🖥️ {t['name']}" for t in st.session_state.targets]
        tabs = st.tabs(tab_names)
        
        log_placeholders = []
        status_placeholders = []
        image_placeholders = []
        
        for idx, tab in enumerate(tabs):
            with tab:
                st.markdown(f"**Target URL**: {st.session_state.targets[idx]['url']}")
                st.markdown(f"**Objective**: {st.session_state.targets[idx]['goal']}")
                status_placeholder = st.empty()
                log_placeholder = st.empty()
                image_placeholder = st.empty()
                
                status_placeholders.append(status_placeholder)
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
                status_placeholders[idx].info("⏳ Initializing isolated browser context...")
                
                log_cb = make_log_callback(idx)
                
                # Dynamic task definition
                tasks.append(
                    run_autonomous_navigator(
                        config_registry=config,
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
                screenshot_path = res.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    image_placeholders[idx].image(
                        screenshot_path,
                        caption=f"Visual Proof: {target_name}",
                        use_container_width=True
                    )
            else:
                status_placeholders[idx].warning(f"⚠️ Warning: Session finished without meeting target state (Steps: {res.get('total_steps')})")
                screenshot_path = res.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    image_placeholders[idx].image(
                        screenshot_path,
                        caption=f"Visual State proof: {target_name}",
                        use_container_width=True
                    )
        
        # 4. ENTERPRISE AUTOMATION STATUS REPORT
        st.markdown("---")
        st.markdown("### 📊 ENTERPRISE AUTOMATION STATUS REPORT")
        
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
        print("📊 CONSOLIDATED ENTERPRISE QA METRICS MATRIX")
        print("="*50)
        print(df.to_markdown(index=False))
        print("="*50 + "\n")
        
        st.markdown("#### Execution Summary Matrix (Markdown)")
        st.code(df.to_markdown(index=False), language="markdown")
