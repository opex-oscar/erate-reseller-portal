import pandas as pd
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Master Reseller E-Rate Portal",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📡 Master Reseller E-Rate Intelligence Portal")
st.caption(
    "Automated USAC Open Data analysis for Category 1 displacement & Category 2 hardware refreshes."
)

# -----------------------------------------------------------------------------
# 2. CONSTANTS & API CONFIGURATION
# -----------------------------------------------------------------------------
USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# Sample EOL Matrix for C2 Hardware
C2_EOL_MATRIX = {
    "WS-C2960X": {"oem": "Cisco", "status": "EOL", "next_gen": "Catalyst 9200"},
    "AP-305": {"oem": "Aruba", "status": "EOL", "next_gen": "AP-635"},
    "FG-100D": {"oem": "Fortinet", "status": "EOL", "next_gen": "FG-100F"},
    "N2048": {"oem": "Dell", "status": "EOL", "next_gen": "N2248X-ON"},
}

# -----------------------------------------------------------------------------
# 3. SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
st.sidebar.header("🎯 Target Parameters")

master_spin = st.sidebar.text_input(
    "Your Master Reseller SPIN", value="143000000"
)
target_state = st.sidebar.selectbox(
    "Select State",
    [
        "NJ",
        "NY",
        "PA",
        "CA",
        "TX",
        "FL",
        "IL",
        "OH",
        "GA",
        "NC",
        "VA",
        "MI",
        "MA",
    ],
    index=0,
)
funding_year = st.sidebar.selectbox(
    "Funding Year", ["2026", "2025", "2024", "2023"], index=0
)
reseller_rate_mbps = st.sidebar.number_input(
    "Your Wholesale Target Rate ($/Mbps/mo)",
    min_value=0.10,
    max_value=20.00,
    value=1.50,
    step=0.25,
)

# -----------------------------------------------------------------------------
# 4. DATA INGESTION ENGINE (USAC API)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_usac_data(state, year, category):
    """Fetches FRN Line Item data from USAC SODA API based on Category."""
    svc_type = (
        "Data Transmission and/or Internet Access"
        if category == "C1"
        else "Internal Connections"
    )

    where_clause = f"state = '{state}' AND funding_year = '{year}' AND form_471_service_type_name = '{svc_type}'"
    params = {
        "$limit": 3000,
        "$where": where_clause,
        "$select": "ben, organization_name, state, funding_year, spin, service_provider_name, download_speed, download_speed_units, monthly_recurring_eligible_cost, total_cost, manufacturer, model",
    }

    try:
        response = requests.get(USAC_API_URL, params=params, timeout=10)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            st.error(f"USAC API Error: {response.status_code}")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Failed to connect to USAC SODA API: {e}")
        return pd.DataFrame()


# -----------------------------------------------------------------------------
# 5. DASHBOARD TABS
# -----------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs([
    "🌐 Category 1 (Internet Displacement)",
    "🛠️ Category 2 (Hardware EOL Refresh)",
    "💼 Contract Migration Calculator",
])

# -----------------------------------------------------------------------------
# TAB 1: CATEGORY 1 (INTERNET DISPLACEMENT)
# -----------------------------------------------------------------------------
with tab1:
    st.subheader(
        f"Category 1 Internet Broadband Benchmarks - {target_state} ({funding_year})"
    )

    c1_raw = load_usac_data(target_state, funding_year, "C1")

    if not c1_raw.empty:
        # Data Processing
        df = c1_raw.copy()
        df["monthly_cost"] = pd.to_numeric(
            df["monthly_recurring_eligible_cost"], errors="coerce"
        )
        df["speed"] = pd.to_numeric(df["download_speed"], errors="coerce")

        def get_mbps(row):
            unit = str(row["download_speed_units"]).lower()
            return (
                row["speed"] * 1000
                if "gbps" in unit or "giga" in unit
                else row["speed"]
            )

        df["speed_mbps"] = df.apply(get_mbps, axis=1)
        df = df[(df["speed_mbps"] > 0) & (df["monthly_cost"] > 0)]
        df["cost_per_mbps"] = df["monthly_cost"] / df["speed_mbps"]

        state_avg = df["cost_per_mbps"].mean()

        # Key Metrics Banner
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Analyzed Accounts", len(df))
        m2.metric("State Avg Cost / Mbps", f"${state_avg:.2f}")
        m3.metric("Your Wholesale Rate", f"${reseller_rate_mbps:.2f}")
        
        # High Cost Candidates
        high_cost_df = df[df["cost_per_mbps"] > reseller_rate_mbps].copy()
        high_cost_df["annual_savings"] = (
            high_cost_df["cost_per_mbps"] - reseller_rate_mbps
        ) * high_cost_df["speed_mbps"] * 12
        m4.metric("Displacement Opportunities", len(high_cost_df))

        st.markdown("---")
        st.markdown("### 🎯 Prime Accounts Paying Above Wholesale Rates")

        display_df = high_cost_df[[
            "organization_name",
            "service_provider_name",
            "spin",
            "speed_mbps",
            "monthly_cost",
            "cost_per_mbps",
            "annual_savings",
        ]].sort_values(by="annual_savings", ascending=False)

        st.dataframe(
            display_df.style.format({
                "speed_mbps": "{:,.0f} Mbps",
                "monthly_cost": "${:,.2f}",
                "cost_per_mbps": "${:,.2f}",
                "annual_savings": "${:,.2f}",
            }),
            use_container_width=True,
        )

        st.download_button(
            label="📥 Export Target Lead List (CSV)",
            data=display_df.to_csv(index=False),
            file_name=f"E-Rate_C1_Targets_{target_state}_{funding_year}.csv",
            mime="text/csv",
        )
    else:
        st.warning("No Category 1 records found for selected filters.")

# -----------------------------------------------------------------------------
# TAB 2: CATEGORY 2 (HARDWARE REFRESH)
# -----------------------------------------------------------------------------
with tab2:
    st.subheader(f"Category 2 EOL Hardware Detection - {target_state}")

    c2_raw = load_usac_data(target_state, funding_year, "C2")

    if not c2_raw.empty:

        def check_eol(model_str):
            if not model_str:
                return "Unknown", "N/A"
            for part, info in C2_EOL_MATRIX.items():
                if part.lower() in str(model_str).lower():
                    return info["status"], info["next_gen"]
            return "Active", "N/A"

        c2_df = c2_raw.copy()
        c2_df[["eol_status", "next_gen_recommendation"]] = c2_df[
            "model"
        ].apply(lambda x: pd.Series(check_eol(x)))

        eol_hits = c2_df[c2_df["eol_status"] == "EOL"]

        st.metric("Detected EOL Systems", len(eol_hits))

        st.markdown("### ⚠️ Sunset Hardware Flagged for Upgrade")
        st.dataframe(
            eol_hits[[
                "organization_name",
                "manufacturer",
                "model",
                "next_gen_recommendation",
                "spin",
                "service_provider_name",
            ]],
            use_container_width=True,
        )
    else:
        st.warning("No Category 2 records found for selected filters.")

# -----------------------------------------------------------------------------
# TAB 3: CONTRACT MIGRATION CALCULATOR
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("💼 Customer Proposal & SPIN Swap Generator")

    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input(
            "School District Name", "Example Public Schools"
        )
        curr_monthly = st.number_input(
            "Current Monthly Contract Cost ($)", value=4500.00
        )
        curr_bandwidth = st.number_input(
            "Current Bandwidth (Mbps)", value=1000
        )

    with col2:
        proposed_rate = st.number_input(
            "Your Proposed $/Mbps Rate ($)", value=2.50
        )
        e_rate_discount = st.slider("District E-Rate Discount %", 20, 90, 80)

    # Math Engine
    curr_rate = curr_monthly / curr_bandwidth if curr_bandwidth > 0 else 0
    prop_monthly = curr_bandwidth * proposed_rate
    monthly_savings = curr_monthly - prop_monthly
    annual_savings = monthly_savings * 12

    out_of_pocket_prop = prop_monthly * (1 - (e_rate_discount / 100))

    st.markdown("---")
    st.markdown(f"### Proposal Summary for **{client_name}**")

    p1, p2, p3 = st.columns(3)
    p1.metric(
        "Current $/Mbps Rate",
        f"${curr_rate:.2f}",
        f"{curr_rate - proposed_rate:+.2f} diff",
    )
    p2.metric(
        "Monthly Client Savings",
        f"${monthly_savings:,.2f}",
        f"{((monthly_savings)/curr_monthly)*100:.1f}% reduction",
    )
    p3.metric("Annual District Savings", f"${annual_savings:,.2f}")

    st.info(
        f"**Net District Out-of-Pocket Cost:** With an **{e_rate_discount}% E-Rate Discount**, "
        f"the district's net monthly payment under your SPIN **({master_spin})** will be **${out_of_pocket_prop:,.2f}/mo**."
    )