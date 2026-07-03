import io
import sys
import os
import glob
import asyncio
import streamlit as st
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
    default_url = config.get("environment", {}).get("default_url", "https://dev.urbuddi.com/login")
    default_steps = config.get("environment", {}).get("max_retry_steps", 15)
    
    # Render config inputs
    target_url = st.text_input("Target URL Override", value=default_url)
    max_steps = st.number_input("Max Execution Steps", min_value=1, max_value=30, value=int(default_steps))
    
    browser_mode = st.selectbox("Browser Visibility", ["Headed (Visible Browser)", "Headless (Run in Background)"], index=0)
    headless = True if browser_mode == "Headless (Run in Background)" else False

    st.markdown("---")
    st.markdown('<div class="sidebar-header">🔐 Admin Credentials</div>', unsafe_allow_html=True)
    static_user = st.text_input("Username / Email", value=config.get("test_data", {}).get("username", "nafreen@gmail.com"))
    static_pass = st.text_input("Password", value=config.get("test_data", {}).get("password", "nafreen@123"), type="password")

    # Synchronize streamlit choices back to the config structure
    config["environment"]["target_url"] = target_url
    config["environment"]["max_retry_steps"] = max_steps
    config["environment"]["headless"] = headless
    config["test_data"]["username"] = static_user
    config["test_data"]["password"] = static_pass

# 2. Chat/Conversation State Initialization
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display conversation messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Custom context manager to intercept stdout and stream directly to Streamlit
class RealTimeStdoutRedirect:
    def __init__(self, st_placeholder):
        self.placeholder = st_placeholder
        self.buffer = io.StringIO()

    def write(self, data):
        self.buffer.write(data)
        # Render the console stream as a raw code block
        self.placeholder.code(self.buffer.getvalue())

    def flush(self):
        pass

# 3. Chat Input Trigger
if user_prompt := st.chat_input("Ask the agent to perform a task (e.g. 'Log in and add a new employee profile')"):
    # Display user objective in chat
    with st.chat_message("user"):
        st.write(user_prompt)
    st.session_state.messages.append({"role": "user", "content": user_prompt})

    # Prepare status panel and terminal output streaming box
    with st.chat_message("assistant"):
        st.markdown("### 📡 Agent Telemetry Stream")
        status_box = st.empty()
        console_box = st.empty()
        
        status_box.info("🚀 Launching Playwright browser driver...")
        
        # Capture stdout stream and execute the agent loop
        old_stdout = sys.stdout
        sys.stdout = RealTimeStdoutRedirect(console_box)
        
        try:
            status_box.info("🧠 Driving perception-action loop... (Processing Step Actions)")
            # Run the navigator loop asynchronously
            asyncio.run(run_autonomous_navigator(config, user_prompt))
            status_box.success("🎉 Execution finished cleanly!")
        except Exception as e:
            status_box.error(f"❌ Execution loop crashed: {e}")
            print(f"\n❌ Loop crashed: {e}", file=sys.stderr)
        finally:
            # Restore stdout
            sys.stdout = old_stdout

        # 4. Post-run Artifact Scan & Screenshot Render
        st.markdown("### 📸 Visual Execution Proof")
        screenshot_pattern = "screenshots/*.png"
        screenshots = glob.glob(screenshot_pattern)
        
        if screenshots:
            # Fetch latest screenshot file dynamically by modtime
            latest_screenshot = max(screenshots, key=os.path.getmtime)
            st.image(
                latest_screenshot, 
                caption=f"Visual State proof: {os.path.basename(latest_screenshot)}",
                use_container_width=True
            )
            st.success(f"Successfully loaded proof: {latest_screenshot}")
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Task execution finished. Latest visual proof loaded: {os.path.basename(latest_screenshot)}"
            })
        else:
            st.warning("⚠️ No execution proof screenshot found in screenshots/ folder.")
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Task execution finished. No screenshot proof was captured."
            })
