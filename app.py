import pandas as pd
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="USAC E-Rate C1 Broadband Benchmarks",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📡 USAC E-Rate Category 1 Broadband Benchmarking")
st.caption("Form 471 Internet & Data Transmission Benchmark Engine.")

USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. URL QUERY PARSING & SIDEBAR INPUTS
# -----------------------------------------------------------------------------
# Parse query parameters or set defaults
query_params = st.query_params

default_ben = query_params.get("ben", "139468")
default_state = query_params.get("state", "NJ").upper()
default_year = query_params.get("year", "2025") # Note: FY2026 filings populate progressively

st.sidebar.header("🔍 Search Filters")
search_mode = st.sidebar.radio(
    "Search Mode",
    ["Lookup by BEN Number", "State-Wide Benchmarks (e.g., NJ)"]
)

if search_mode == "Lookup by BEN Number":
    input_ben = st.sidebar.text_input("Billed Entity Number (BEN)", value=default_ben).strip()
    target_state = None
else:
    input_ben = None
    target_state = st.sidebar.text_input("State Code (2-Letters)", value=default_state).strip().upper()

target_year = st.sidebar.selectbox(
    "Funding Year",
    ["2026", "2025", "2024", "2023"],
    index=1
)

# -----------------------------------------------------------------------------
# 3. DATA FETCHING ENGINE
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_data(ben_id):
    """Fetches FRN Line Items for a specific BEN."""
    params = {
        "$limit": 1000,
        "ben": str(ben_id).strip(),
        "$order": "funding_year DESC",
    }
    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code == 200:
            return pd.DataFrame(res.json()), None
        return pd.DataFrame(), f"API returned status HTTP {res.status_code}"
    except Exception as e:
        return pd.DataFrame(), f"Connection error: {e}"

@st.cache_data(ttl=1800)
def fetch_state_data(state_code, year):
    """Fetches C1 Broadband records for an entire State and Funding Year."""
    params = {
        "$limit": 2500,
        "state": str(state_code).upper(),
        "funding_year": str(year),
        "$where": "(form_471_service_type_name like '%Internet%' OR form_471_service_type_name like '%Data%')",
    }
    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if not data:
                return pd.DataFrame(), f"No records found for state **{state_code}** in FY{year}."
            return pd.DataFrame(data), None
        return pd.DataFrame(), f"USAC API Error ({res.status_code}): {res.text}"
    except Exception as e:
        return pd.DataFrame(), f"Connection error: {e}"

def process_metrics(df):
    """Filters C1 Data and calculates Cost/Mbps."""
    if df.empty:
        return df

    if "form_471_service_type_name" in df.columns:
        c1_mask = df["form_471_service_type_name"].astype(str).str.contains(
            "Internet|Data Transmission", case=False, na=False
        )
        df = df[c1_mask].copy()

    if df.empty:
        return df

    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    ).fillna(0)

    df["speed"] = pd.to_numeric(
        df.get("download_speed", 0), errors="coerce"
    ).fillna(0)

    def normalize_mbps(row):
        unit = str(row.get("download_speed_units", "")).lower()
        speed = row["speed"]
        if "gbps" in unit or "giga" in unit:
            return speed * 1000
        return speed

    df["speed_mbps"] = df.apply(normalize_mbps, axis=1)
    df["cost_per_mbps"] = df.apply(
        lambda r: (r["monthly_cost"] / r["speed_mbps"]) if r["speed_mbps"] > 0 else 0,
        axis=1,
    )
    return df

# -----------------------------------------------------------------------------
# 4. MAIN RENDER
# -----------------------------------------------------------------------------
if search_mode == "Lookup by BEN Number":
    if not input_ben:
        st.info("👈 Enter a BEN number in the sidebar.")
    else:
        with st.spinner(f"Loading data for BEN {input_ben}..."):
            raw_df, err = fetch_ben_data(input_ben)

        if err:
            st.error(err)
        elif raw_df.empty:
            st.warning(f"No records found for BEN **{input_ben}**.")
        else:
            df = process_metrics(raw_df)
            entity_name = df["organization_name"].iloc[0] if "organization_name" in df.columns else f"BEN {input_ben}"
            entity_state = df["state"].iloc[0] if "state" in df.columns else "N/A"

            st.markdown(f"## 🏢 **{entity_name}**")
            st.markdown(f"**BEN:** `{input_ben}` | **State:** `{entity_state}`")

            st.subheader("Historical C1 Form 471 Line Items")
            st.dataframe(df[["funding_year", "service_provider_name", "speed_mbps", "monthly_cost", "cost_per_mbps"]], use_container_width=True)

else:
    # State-Wide Benchmarks (e.g., NJ 2026/2025)
    with st.spinner(f"Fetching C1 Broadband records for {target_state} (FY{target_year})..."):
        raw_df, err = fetch_state_data(target_state, target_year)

    if err:
        st.error(err)
    elif raw_df.empty:
        st.warning(f"No C1 Broadband filings recorded yet for state **{target_state}** in funding year **{target_year}**. Try switching to FY2025.")
    else:
        df = process_metrics(raw_df)
        valid_df = df[df["cost_per_mbps"] > 0]

        st.markdown(f"## 🗺️ State Benchmark Report: **{target_state} ({target_year})**")
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Line Items Evaluated", f"{len(df):,}")
        m2.metric("Average State Rate", f"${valid_df['cost_per_mbps'].mean():.2f} / Mbps")
        m3.metric("Median State Rate", f"${valid_df['cost_per_mbps'].median():.2f} / Mbps")

        st.markdown("---")
        st.subheader(f"🏆 Active Service Providers in {target_state}")

        provider_summary = (
            valid_df.groupby(["service_provider_name", "spin"])
            .agg(
                avg_cost_per_mbps=("cost_per_mbps", "mean"),
                max_speed_offered=("speed_mbps", "max"),
                total_contracts=("funding_request_number", "nunique"),
            )
            .reset_index()
            .sort_values(by="avg_cost_per_mbps", ascending=True)
        )

        st.dataframe(
            provider_summary.style.format({
                "avg_cost_per_mbps": "${:,.2f}",
                "max_speed_offered": "{:,.0f} Mbps",
            }),
            use_container_width=True,
        )
