import pandas as pd
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="USAC E-Rate BEN Intelligence Portal",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📡 USAC E-Rate BEN Search & Regional Benchmarking")
st.caption("Lookup Form 471 Category 1 Broadband details by Billed Entity Number (BEN).")

USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Search Parameters")
input_ben = st.sidebar.text_input("Enter Billed Entity Number (BEN)", value="139692").strip()

# -----------------------------------------------------------------------------
# 3. API FETCHING & NORMALIZATION FUNCTIONS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_data(ben):
    """Queries USAC SODA API for all C1 line items associated with a BEN."""
    params = {
        "$limit": 1000,
        "$where": f"ben = '{ben}' AND form_471_service_type_name = 'Data Transmission and/or Internet Access'",
        "$order": "funding_year DESC",
    }
    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code == 200:
            return pd.DataFrame(res.json())
        else:
            st.error(f"USAC API Error ({res.status_code}): {res.text}")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def fetch_state_competitors(state_code, funding_year):
    """Queries USAC SODA API for state-wide C1 broadband line items for benchmarking."""
    params = {
        "$limit": 3000,
        "$where": f"state = '{state_code}' AND funding_year = '{funding_year}' AND form_471_service_type_name = 'Data Transmission and/or Internet Access'",
    }
    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code == 200:
            return pd.DataFrame(res.json())
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def process_metrics(df):
    """Calculates Speed in Mbps and Monthly Cost / Mbps."""
    if df.empty:
        return df

    df["monthly_cost"] = pd.to_numeric(df.get("monthly_recurring_eligible_cost", 0), errors="coerce").fillna(0)
    df["speed"] = pd.to_numeric(df.get("download_speed", 0), errors="coerce").fillna(0)

    def normalize_mbps(row):
        unit = str(row.get("download_speed_units", "")).lower()
        speed = row["speed"]
        if "gbps" in unit or "giga" in unit:
            return speed * 1000
        return speed

    df["speed_mbps"] = df.apply(normalize_mbps, axis=1)
    df["cost_per_mbps"] = df.apply(
        lambda r: (r["monthly_cost"] / r["speed_mbps"]) if r["speed_mbps"] > 0 else 0, axis=1
    )
    return df

# -----------------------------------------------------------------------------
# 4. MAIN APPLICATION
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Please enter a BEN in the sidebar to begin.")
else:
    raw_ben_data = fetch_ben_data(input_ben)
    ben_df = process_metrics(raw_ben_data)

    if ben_df.empty:
        st.warning(f"No Category 1 Broadband records found in USAC database for BEN: **{input_ben}**.")
    else:
        # Extract metadata
        entity_name = ben_df["organization_name"].iloc[0] if "organization_name" in ben_df.columns else "Unknown Entity"
        entity_state = ben_df["state"].iloc[0] if "state" in ben_df.columns else "N/A"
        latest_year = ben_df["funding_year"].iloc[0] if "funding_year" in ben_df.columns else "N/A"

        st.markdown(f"## 🏢 **{entity_name}**")
        st.markdown(f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | **Latest Recorded Filing:** `{latest_year}`")

        tab1, tab2 = st.tabs(["📋 Form 471 History & Line Items", "🗺️ State / Carrier Benchmarking"])

        # -----------------------------------------------------------------------------
        # TAB 1: FORM 471 DETAILS
        # -----------------------------------------------------------------------------
        with tab1:
            st.subheader("Historical Form 471 Category 1 Broadband Line Items")

            display_cols = [
                "funding_year",
                "funding_request_number",
                "service_provider_name",
                "spin",
                "speed_mbps",
                "monthly_cost",
                "cost_per_mbps",
                "form_471_product_name",
            ]

            cols_exist = [c for c in display_cols if c in ben_df.columns]
            clean_df = ben_df[cols_exist].copy()

            rename_map = {
                "funding_year": "Funding Year",
                "funding_request_number": "FRN",
                "service_provider_name": "Service Provider",
                "spin": "SPIN",
                "speed_mbps": "Speed (Mbps)",
                "monthly_cost": "Monthly Cost ($)",
                "cost_per_mbps": "Cost / Mbps ($)",
                "form_471_product_name": "Product Description",
            }
            clean_df = clean_df.rename(columns=rename_map)

            st.dataframe(
                clean_df.style.format({
                    "Speed (Mbps)": "{:,.0f} Mbps",
                    "Monthly Cost ($)": "${:,.2f}",
                    "Cost / Mbps ($)": "${:,.2f}",
                }),
                use_container_width=True,
            )

            st.download_button(
                label="📥 Export BEN Line Items (CSV)",
                data=clean_df.to_csv(index=False),
                file_name=f"BEN_{input_ben}_471_History.csv",
                mime="text/csv",
            )

        # -----------------------------------------------------------------------------
        # TAB 2: BENCHMARKING & CARRIERS
        # -----------------------------------------------------------------------------
        with tab2:
            st.subheader(f"Broadband Carrier Benchmarking for {entity_state} ({latest_year})")

            state_raw = fetch_state_competitors(entity_state, latest_year)
            state_df = process_metrics(state_raw)

            if state_df.empty:
                st.info(f"No additional state-wide comparisons available for {entity_state} in {latest_year}.")
            else:
                valid_state_df = state_df[state_df["cost_per_mbps"] > 0]
                avg_state_rate = valid_state_df["cost_per_mbps"].mean()

                latest_ben_row = ben_df.iloc[0]
                curr_rate = latest_ben_row.get("cost_per_mbps", 0)
                curr_speed = latest_ben_row.get("speed_mbps", 0)
                curr_provider = latest_ben_row.get("service_provider_name", "N/A")

                b1, b2 = st.columns(2)
                b1.metric("Current BEN Rate", f"${curr_rate:.2f} / Mbps", f"Provider: {curr_provider}")
                b2.metric(f"{entity_state} State Average Rate", f"${avg_state_rate:.2f} / Mbps")

                st.markdown("---")
                st.markdown(f"### 🏆 Top Telecom Providers in {entity_state}")

                provider_summary = (
                    valid_state_df.groupby(["service_provider_name", "spin"])
                    .agg(
                        avg_cost_per_mbps=("cost_per_mbps", "mean"),
                        max_speed_offered=("speed_mbps", "max"),
                        total_contracts=("ben", "count"),
                    )
                    .reset_index()
                    .sort_values(by="avg_cost_per_mbps", ascending=True)
                )

                provider_summary = provider_summary.rename(
                    columns={
                        "service_provider_name": "Carrier / Provider",
                        "spin": "SPIN",
                        "avg_cost_per_mbps": f"Avg $/Mbps in {entity_state}",
                        "max_speed_offered": "Max Speed Offered",
                        "total_contracts": "Total Contracts in State",
                    }
                )

                st.dataframe(
                    provider_summary.style.format({
                        f"Avg $/Mbps in {entity_state}": "${:,.2f}",
                        "Max Speed Offered": "{:,.0f} Mbps",
                    }),
                    use_container_width=True,
                )
