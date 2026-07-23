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

# Primary Endpoint: USAC Form 471 FRN Line Items
USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS & NAVIGATION
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Search Mode")
search_mode = st.sidebar.radio(
    "Select Query Type",
    ["Lookup by BEN Number", "State-Wide Benchmarks (e.g., NJ)"]
)

st.sidebar.markdown("---")

if search_mode == "Lookup by BEN Number":
    input_ben = st.sidebar.text_input(
        "Billed Entity Number (BEN)", value="139468"
    ).strip()
    target_state = None
else:
    input_ben = None
    target_state = st.sidebar.text_input(
        "State Code (2 Letters)", value="NJ"
    ).strip().upper()

target_year = st.sidebar.selectbox(
    "Funding Year",
    ["2026", "2025", "2024", "2023"],
    index=1  # FY2025 default as FY2026 filings are progressively committed
)

# -----------------------------------------------------------------------------
# 3. DEFENSIVE DATA FETCHING ENGINE
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_line_items(ben_num):
    """Fetches line items for a specific BEN with defensive response checking."""
    if not ben_num:
        return pd.DataFrame(), "Please enter a valid BEN number."

    params = {
        "$limit": 1000,
        "ben": str(ben_num).strip(),
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code != 200:
            return pd.DataFrame(), f"USAC API Error HTTP {res.status_code}"

        data = res.json()

        # Validate that API returned a list of records, not an error dict
        if not isinstance(data, list):
            msg = data.get("message", "Invalid API response format.") if isinstance(data, dict) else "Unknown API error"
            return pd.DataFrame(), f"USAC API Error: {msg}"

        if len(data) == 0:
            return pd.DataFrame(), f"No records found in USAC database for BEN **{ben_num}**."

        return pd.DataFrame(data), None

    except Exception as e:
        return pd.DataFrame(), f"Network connection failed: {str(e)}"


@st.cache_data(ttl=1800)
def fetch_state_line_items(state_code, year):
    """Fetches C1 broadband records for an entire state with defensive checking."""
    if not state_code or len(state_code) != 2:
        return pd.DataFrame(), "Please enter a valid 2-letter state code (e.g., NJ)."

    params = {
        "$limit": 2000,
        "state": str(state_code).upper(),
        "funding_year": str(year),
        "$where": "(form_471_service_type_name like '%Internet%' OR form_471_service_type_name like '%Data%')",
    }

    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code != 200:
            return pd.DataFrame(), f"USAC API Error HTTP {res.status_code}"

        data = res.json()

        if not isinstance(data, list):
            msg = data.get("message", "Invalid API response format.") if isinstance(data, dict) else "Unknown API error"
            return pd.DataFrame(), f"USAC API Error: {msg}"

        if len(data) == 0:
            return pd.DataFrame(), f"No C1 Broadband records found for state **{state_code}** in FY{year}."

        return pd.DataFrame(data), None

    except Exception as e:
        return pd.DataFrame(), f"Network connection failed: {str(e)}"


def process_metrics(df):
    """Safely normalizes bandwidth speeds and calculates cost metrics."""
    if df.empty or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    # Filter for Category 1 Internet/Data Transmission
    if "form_471_service_type_name" in df.columns:
        c1_mask = df["form_471_service_type_name"].astype(str).str.contains(
            "Internet|Data Transmission", case=False, na=False
        )
        df = df[c1_mask].copy()

    if df.empty:
        return df

    # Safe numeric conversion
    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    ).fillna(0)

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
# 4. MAIN RENDER ENGINE
# -----------------------------------------------------------------------------
if search_mode == "Lookup by BEN Number":
    if not input_ben:
        st.info("👈 Enter a BEN number in the sidebar to search.")
    else:
        with st.spinner(f"Querying USAC Open Data for BEN {input_ben}..."):
            raw_df, err = fetch_ben_line_items(input_ben)

        if err:
            st.error(err)
        else:
            df = process_metrics(raw_df)

            if df.empty:
                st.warning(f"BEN **{input_ben}** was found, but no Category 1 Broadband line items exist.")
            else:
                entity_name = df["organization_name"].iloc[0] if "organization_name" in df.columns else f"BEN {input_ben}"
                entity_state = df["state"].iloc[0] if "state" in df.columns else "N/A"
                latest_yr = df["funding_year"].iloc[0] if "funding_year" in df.columns else "N/A"

                st.markdown(f"## 🏢 **{entity_name}**")
                st.markdown(f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | **Latest Year:** `{latest_yr}`")

                st.subheader("Historical C1 Form 471 Line Items")

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
                cols_exist = [c for c in display_cols if c in df.columns]

                st.dataframe(
                    df[cols_exist].style.format({
                        "speed_mbps": "{:,.0f} Mbps",
                        "monthly_cost": "${:,.2f}",
                        "cost_per_mbps": "${:,.2f}",
                    }),
                    use_container_width=True,
                )

else:
    # State-Wide Benchmark Mode (e.g., NJ 2025/2026)
    with st.spinner(f"Fetching C1 Broadband records for state {target_state} (FY{target_year})..."):
        raw_df, err = fetch_state_line_items(target_state, target_year)

    if err:
        st.error(err)
    else:
        df = process_metrics(raw_df)

        if df.empty:
            st.warning(f"No C1 Broadband filings recorded for state **{target_state}** in FY**{target_year}**. Try selecting FY2025 in the sidebar.")
        else:
            valid_df = df[df["cost_per_mbps"] > 0]

            st.markdown(f"## 🗺️ State Benchmark Report: **{target_state} ({target_year})**")

            m1, m2, m3 = st.columns(3)
            m1.metric("Line Items Analyzed", f"{len(df):,}")
            m2.metric("Average $/Mbps Rate", f"${valid_df['cost_per_mbps'].mean():.2f}")
            m3.metric("Median $/Mbps Rate", f"${valid_df['cost_per_mbps'].median():.2f}")

            st.markdown("---")
            st.subheader(f"🏆 Active Broadband Carriers in {target_state}")

            if not valid_df.empty and "service_provider_name" in valid_df.columns:
                provider_summary = (
                    valid_df.groupby(["service_provider_name", "spin"])
                    .agg(
                        avg_cost_per_mbps=("cost_per_mbps", "mean"),
                        max_speed_offered=("speed_mbps", "max"),
                        total_contracts=("funding_request_number", "nunique") if "funding_request_number" in valid_df.columns else ("monthly_cost", "count"),
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
