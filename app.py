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

st.title("📡 USAC E-Rate Form 471 BEN Search & Benchmarking")
st.caption("Powered by USAC E-Rate Open Data (Form 471 FRN Line Items).")

# Direct USAC Form 471 FRN Line Items SODA Endpoint
USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Search Parameters")
input_ben = st.sidebar.text_input(
    "Enter Billed Entity Number (BEN)", value="139692"
).strip()


# -----------------------------------------------------------------------------
# 3. DATA FETCHING ENGINE
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_line_items(ben_str):
    """Fetches line items directly for target BEN without fragile SQL syntax."""
    clean_ben = str(ben_str).strip()

    # Query directly by parameter to avoid SODA engine SQL string formatting errors
    params = {
        "$limit": 2000,
        "ben": clean_ben,
        "$order": "funding_year DESC",
    }

    try:
        response = requests.get(USAC_API_URL, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if not data:
                return pd.DataFrame(), f"No records found in USAC database for BEN {clean_ben}."
            
            df = pd.DataFrame(data)
            return df, None
        else:
            return pd.DataFrame(), f"USAC API Error (HTTP {response.status_code}): {response.text}"
    except Exception as e:
        return pd.DataFrame(), f"Network connection failed: {str(e)}"


@st.cache_data(ttl=1800)
def fetch_state_benchmarks(state_code, funding_year):
    """Fetches state-wide broadband contracts for comparative benchmarking."""
    if not state_code or state_code == "N/A":
        return pd.DataFrame()

    params = {
        "$limit": 3000,
        "state": state_code,
        "funding_year": str(funding_year),
    }

    try:
        response = requests.get(USAC_API_URL, params=params, timeout=15)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
    except Exception:
        pass
    return pd.DataFrame()


def process_and_filter_metrics(df):
    """Filters C1 Broadband services and calculates Cost/Mbps metrics."""
    if df.empty:
        return df

    # Filter for Category 1 Internet / Data Transmission
    if "form_471_service_type_name" in df.columns:
        c1_mask = df["form_471_service_type_name"].astype(str).str.contains(
            "Internet|Data Transmission", case=False, na=False
        )
        df = df[c1_mask].copy()

    if df.empty:
        return df

    # Monthly Cost Conversion
    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    ).fillna(0)

    # Speed Conversion
    df["speed"] = pd.to_numeric(
        df.get("download_speed", 0), errors="coerce"
    ).fillna(0)

    def calculate_mbps(row):
        unit = str(row.get("download_speed_units", "")).lower()
        speed = row["speed"]
        if "gbps" in unit or "giga" in unit:
            return speed * 1000
        return speed

    df["speed_mbps"] = df.apply(calculate_mbps, axis=1)
    df["cost_per_mbps"] = df.apply(
        lambda r: (r["monthly_cost"] / r["speed_mbps"]) if r["speed_mbps"] > 0 else 0,
        axis=1,
    )
    return df


# -----------------------------------------------------------------------------
# 4. MAIN APPLICATION
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Enter a Billed Entity Number (BEN) in the sidebar to run search.")
else:
    with st.spinner(f"Querying USAC Open Data for BEN {input_ben}..."):
        raw_ben_df, error_msg = fetch_ben_line_items(input_ben)

    if error_msg:
        st.error(error_msg)
    else:
        processed_df = process_and_filter_metrics(raw_ben_df)

        if processed_df.empty:
            st.warning(f"Found BEN **{input_ben}**, but no Category 1 Broadband line items were identified.")
        else:
            # Extract Metadata
            entity_name = processed_df["organization_name"].iloc[0] if "organization_name" in processed_df.columns else f"BEN {input_ben}"
            entity_state = processed_df["state"].iloc[0] if "state" in processed_df.columns else "N/A"
            latest_year = processed_df["funding_year"].iloc[0] if "funding_year" in processed_df.columns else "N/A"

            st.markdown(f"## 🏢 **{entity_name}**")
            st.markdown(f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | **Latest Recorded Year:** `{latest_year}`")

            tab1, tab2 = st.tabs(["📋 Form 471 Line Items", "🗺️ State Broadband Benchmarking"])

            # -----------------------------------------------------------------------------
            # TAB 1: FORM 471 DETAILS
            # -----------------------------------------------------------------------------
            with tab1:
                st.subheader("Historical Form 471 Category 1 Contracts")

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

                cols_exist = [c for c in display_cols if c in processed_df.columns]
                clean_df = processed_df[cols_exist].copy()

                clean_df = clean_df.rename(
                    columns={
                        "funding_year": "Funding Year",
                        "funding_request_number": "FRN",
                        "service_provider_name": "Service Provider",
                        "spin": "SPIN",
                        "speed_mbps": "Speed (Mbps)",
                        "monthly_cost": "Monthly Cost ($)",
                        "cost_per_mbps": "Cost / Mbps ($)",
                        "form_471_product_name": "Product Description",
                    }
                )

                st.dataframe(
                    clean_df.style.format({
                        "Speed (Mbps)": "{:,.0f} Mbps",
                        "Monthly Cost ($)": "${:,.2f}",
                        "Cost / Mbps ($)": "${:,.2f}",
                    }),
                    use_container_width=True,
                )

                st.download_button(
                    label="📥 Export Line Items (CSV)",
                    data=clean_df.to_csv(index=False),
                    file_name=f"BEN_{input_ben}_Form471_History.csv",
                    mime="text/csv",
                )

            # -----------------------------------------------------------------------------
            # TAB 2: STATE BENCHMARKING
            # -----------------------------------------------------------------------------
            with tab2:
                st.subheader(f"Broadband Carrier Benchmarking for State: {entity_state}")

                state_raw = fetch_state_benchmarks(entity_state, latest_year)
                state_df = process_and_filter_metrics(state_raw)

                if state_df.empty:
                    st.info(f"No additional state comparison data returned for {entity_state} in {latest_year}.")
                else:
                    valid_state_df = state_df[state_df["cost_per_mbps"] > 0]
                    avg_state_rate = valid_state_df["cost_per_mbps"].mean() if not valid_state_df.empty else 0

                    curr_rate = processed_df.iloc[0].get("cost_per_mbps", 0)

                    b1, b2 = st.columns(2)
                    b1.metric("Target BEN Rate", f"${curr_rate:.2f} / Mbps")
                    b2.metric(f"{entity_state} Average Rate ({latest_year})", f"${avg_state_rate:.2f} / Mbps")

                    st.markdown("---")
                    st.markdown(f"### 🏆 Top Broadband Carriers in {entity_state}")

                    provider_summary = (
                        valid_state_df.groupby(["service_provider_name", "spin"])
                        .agg(
                            avg_cost_per_mbps=("cost_per_mbps", "mean"),
                            max_speed_offered=("speed_mbps", "max"),
                            total_contracts=("funding_request_number", "count"),
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
                            "total_contracts": "Contract Count",
                        }
                    )

                    st.dataframe(
                        provider_summary.style.format({
                            f"Avg $/Mbps in {entity_state}": "${:,.2f}",
                            "Max Speed Offered": "{:,.0f} Mbps",
                        }),
                        use_container_width=True,
                    )
