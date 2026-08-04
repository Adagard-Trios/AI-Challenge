"""
app.py
Streamlit Dashboard for Roger Platform
Interactive interface with Infinite Auto-Refresh & Smart Updates
"""
import streamlit as st
import json
import hashlib
from datetime import datetime
import plotly.graph_objects as go
import time

# Import Roger components
# NOTE: Ensure these imports work in your local environment
from src.graphs.RogerGraph import graph
from src.states.combinedAgentState import CombinedAgentState

# ============================================
# PAGE CONFIGURATION
# ============================================

st.set_page_config(
    page_title="Roger - Situational Awareness Platform",
    page_icon="🇱🇰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# CUSTOM CSS
# ============================================

st.markdown("""
<style>
    .main-header { font-size: 2.5rem; color: #FAFAFA; font-weight: bold; text-align: center; margin-bottom: 1rem; }
    .sub-header { font-size: 1.2rem; color: #aaaaaa; text-align: center; margin-bottom: 2rem; }
    .stApp { background-color: #0e1117; color: #FAFAFA; }
    
    /* Severity Colors for Badges */
    .severity-critical { color: #ff2b2b; font-weight: 800; }
    .severity-high { color: #ff4444; font-weight: bold; }
    .severity-medium { color: #ff9800; font-weight: bold; }
    .severity-low { color: #4caf50; font-weight: bold; }
    
    /* Opportunity Color */
    .impact-opportunity { color: #00CC96; font-weight: bold; }
    
    /* Loading Screen Animation */
    @keyframes pulse {
        0% { opacity: 0.5; }
        50% { opacity: 1; }
        100% { opacity: 0.5; }
    }
    .loading-text {
        color: #00CC96;
        font-family: monospace;
        font-size: 1.5rem;
        text-align: center;
        animation: pulse 2s infinite;
    }
    
    /* Card Styling */
    .event-card {
        border-left: 4px solid #444;
        padding: 10px;
        margin-bottom: 10px;
        background-color: #262730;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# HEADER
# ============================================

st.markdown('<div class="main-header">🇱🇰 Roger</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">National Situational Awareness Platform</div>', unsafe_allow_html=True)

# ============================================
# SIDEBAR
# ============================================

with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Auto-refresh interval
    refresh_rate = st.slider("Polling Interval (s)", 5, 60, 10)
    
    st.divider()
    
    # Control Buttons
    col_start, col_stop = st.columns(2)
    with col_start:
        if st.button("▶ START", type="primary", use_container_width=True):
            st.session_state.monitoring_active = True
            st.rerun()
            
    with col_stop:
        if st.button("⏹ STOP", use_container_width=True):
            st.session_state.monitoring_active = False
            st.rerun()

    st.divider()
    st.info("""
    **Team Adagard** Open Innovation Track
    
    Roger transforms national-scale noise into actionable business intelligence using autonomous multi-agent architecture.
    """)
    st.code("START → Fan-Out → [Agents] → Fan-In → Dashboard → Loop", language="text")

# ============================================
# SESSION STATE INITIALIZATION
# ============================================

if "monitoring_active" not in st.session_state:
    st.session_state.monitoring_active = False
if "latest_result" not in st.session_state:
    st.session_state.latest_result = None
if "last_hash" not in st.session_state:
    st.session_state.last_hash = ""
if "execution_count" not in st.session_state:
    st.session_state.execution_count = 0

# ============================================
# HELPER FUNCTIONS
# ============================================

def calculate_hash(data_dict):
    """Creates a hash of the dashboard data to detect changes."""
    # We focus on the snapshot and the feed length/content
    snapshot = data_dict.get("risk_dashboard_snapshot", {})
    feed = data_dict.get("final_ranked_feed", [])
    
    # Create a simplified string representation to hash
    content_str = f"{snapshot.get('last_updated')}-{len(feed)}-{snapshot.get('opportunity_index')}"
    return hashlib.md5(content_str.encode()).hexdigest()

def render_dashboard(container, result):
    """Renders the entire dashboard into the provided container."""
    snapshot = result.get("risk_dashboard_snapshot", {})
    feed = result.get("final_ranked_feed", [])
    
    # Clear the container to ensure clean re-render
    container.empty()
    
    with container.container():
        st.divider()
        
        # -------------------------------------------------------------------------
        # 1. METRICS ROW
        # -------------------------------------------------------------------------
        st.subheader("📊 Operational Metrics")
        m1, m2, m3, m4 = st.columns(4)
        
        with m1:
            st.metric("Logistics Friction", f"{snapshot.get('logistics_friction', 0):.3f}", help="Route risk score")
        with m2:
            st.metric("Compliance Volatility", f"{snapshot.get('compliance_volatility', 0):.3f}", help="Regulatory risk")
        with m3:
            st.metric("Market Instability", f"{snapshot.get('market_instability', 0):.3f}", help="Economic volatility")
        with m4:
            opp_val = snapshot.get("opportunity_index", 0.0)
            st.metric("Opportunity Index", f"{opp_val:.3f}", delta="Growth Signal" if opp_val > 0.5 else "Neutral", delta_color="normal")

        # -------------------------------------------------------------------------
        # 2. RADAR CHART
        # -------------------------------------------------------------------------
        st.divider()
        c1, c2 = st.columns([1, 1])
        
        with c1:
            st.subheader("📡 Risk vs. Opportunity Radar")
            
            categories = ['Logistics', 'Compliance', 'Market', 'Social', 'Weather']
            risk_vals = [
                snapshot.get('logistics_friction', 0),
                snapshot.get('compliance_volatility', 0),
                snapshot.get('market_instability', 0),
                0.4, 0.2 
            ]
            
            fig = go.Figure()
            
            # Risk Layer
            fig.add_trace(go.Scatterpolar(
                r=risk_vals, theta=categories, fill='toself', name='Operational Risk',
                line_color='#ff4444'
            ))
            
            # Opportunity Layer
            fig.add_trace(go.Scatterpolar(
                r=[opp_val] * 5, theta=categories, name='Opportunity Threshold',
                line_color='#00CC96', opacity=0.7, line=dict(dash='dot')
            ))
            
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                height=350,
                margin=dict(l=40, r=40, t=20, b=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color="white")
            )
            st.plotly_chart(fig, use_container_width=True)

        # -------------------------------------------------------------------------
        # 3. INTELLIGENCE FEED
        # -------------------------------------------------------------------------
        with c2:
            st.subheader("📰 Intelligence Feed")
            
            tab_all, tab_risk, tab_opp = st.tabs(["All Events", "Risks ⚠️", "Opportunities 🚀"])
            
            def render_feed(filter_type=None):
                if not feed:
                    st.info("No events detected.")
                    return

                count = 0
                for event in feed[:15]: 
                    imp = event.get("impact_type", "risk")
                    if filter_type and imp != filter_type: continue
                    
                    border_color = "#ff4444" if imp == "risk" else "#00CC96"
                    icon = "⚠️" if imp == "risk" else "🚀"
                    
                    summary = event.get("content_summary", "")
                    domain = event.get("target_agent", "unknown").upper()
                    score = event.get("confidence_score", 0.0)
                    
                    st.markdown(
                        f"""
                        <div style="border-left: 4px solid {border_color}; padding: 10px; margin-bottom: 10px; background-color: #262730; border-radius: 4px;">
                            <div style="font-size: 0.8em; color: #aaa; display: flex; justify-content: space-between;">
                                <span>{domain}</span>
                                <span>SCORE: {score:.2f}</span>
                            </div>
                            <div style="margin-top: 4px; font-weight: 500;">
                                {icon} {summary}
                            </div>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                    count += 1
                
                if count == 0:
                    st.caption("No events in this category.")

            with tab_all: render_feed()
            with tab_risk: render_feed("risk")
            with tab_opp: render_feed("opportunity")
            
        st.divider()
        st.caption(f"Last Updated: {datetime.utcnow().strftime('%H:%M:%S UTC')} | Run Count: {st.session_state.execution_count}")

# ============================================
# MAIN EXECUTION LOGIC
# ============================================

# We use a placeholder that we can overwrite dynamically
dashboard_placeholder = st.empty()

if st.session_state.monitoring_active:
    
    # ---------------------------------------------------------
    # PHASE 1: INITIAL LOAD (Runs only if we have NO data)
    # ---------------------------------------------------------
    if st.session_state.latest_result is None:
        with dashboard_placeholder.container():
            st.markdown("<br><br><br>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.markdown('<div class="loading-text">INITIALIZING NEURAL AGENTS...</div>', unsafe_allow_html=True)
                st.markdown('<div style="text-align:center; color:#666;">Connecting to Roger Graph Network</div>', unsafe_allow_html=True)
                progress_bar = st.progress(0)
                
                # Visual effect for initialization
                steps = ["Loading Social Graph...", "Connecting to Market Data...", "Calibrating Risk Radar...", "Starting Fan-Out Sequence..."]
                for i, step in enumerate(steps):
                    time.sleep(0.3)
                    progress_bar.progress((i + 1) * 25)

            # --- PERFORM FIRST FETCH ---
            try:
                current_state = CombinedAgentState(max_runs=1, run_count=0)
                result = graph.invoke(current_state)
                
                # Save to session state
                st.session_state.latest_result = result
                st.session_state.last_hash = calculate_hash(result)
                st.session_state.execution_count = 1
                
            except Exception as e:
                st.error(f"Initialization Error: {e}")
                st.session_state.monitoring_active = False
                st.stop()

    # ---------------------------------------------------------
    # PHASE 2: CONTINUOUS MONITORING LOOP
    # ---------------------------------------------------------
    # By this point, st.session_state.latest_result is GUARANTEED to have data.
    
    while st.session_state.monitoring_active:
        
        # 1. RENDER CURRENT DATA
        # We render whatever is in the state immediately. 
        # This replaces the loading screen or the previous frame.
        render_dashboard(dashboard_placeholder, st.session_state.latest_result)
        
        # 2. WAIT (The "Background" part)
        # The UI is now visible to the user while we sleep.
        time.sleep(refresh_rate)
        
        # 3. FETCH NEW DATA
        try:
            current_state = CombinedAgentState(max_runs=1, run_count=st.session_state.execution_count)
            # Run the graph silently in background
            new_result = graph.invoke(current_state)
            
            # 4. CHECK FOR DIFFERENCES
            new_hash = calculate_hash(new_result)
            
            if new_hash != st.session_state.last_hash:
                # DATA CHANGED: Update state
                st.session_state.last_hash = new_hash
                st.session_state.latest_result = new_result
                st.session_state.execution_count += 1
                
                # Optional: Pop a toast
                st.toast(f"New Intel Detected ({len(new_result.get('final_ranked_feed', []))} events)", icon="⚡")
                
                # The loop continues... 
                # The NEXT iteration (Step 1) will render this new data.
            else:
                # NO CHANGE:
                # We do nothing. The loop continues. 
                # Step 1 will simply re-render the existing stable data.
                pass
                
        except Exception as e:
            st.error(f"Monitoring Error: {e}")
            time.sleep(5) # Wait before retrying on error

else:
    # ---------------------------------------------------------
    # IDLE STATE
    # ---------------------------------------------------------
    with dashboard_placeholder.container():
        st.markdown("<br><br>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 4, 1])
        with col2:
            st.info("System Standby. Click '▶ START' in the sidebar to begin autonomous monitoring.")
            
            if st.session_state.latest_result:
                st.markdown("### Last Session Snapshot:")
                # We use a temporary container here just for the snapshot
                with st.container():
                     render_dashboard(st.empty(), st.session_state.latest_result)
