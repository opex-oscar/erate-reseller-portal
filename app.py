import pandas as pd
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & METADATA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="USAC E-Rate C1 Broadband Benchmarks",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📡 USAC E-Rate C1 Broadband BEN & ZIP Benchmarking")
st.caption("Powered by USAC E-Rate Recipient Details & Commitments API (Unfiltered Historical Years).")

# Master Dataset: Contains BENs, FRN Line Items, Speeds, Costs, and Physical ZIP Codes
MASTER_USAC_API = "https://opendata.usac.org/resource/avi8-svp9.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Entity Search")

# Default search BEN (Bald Knob School District: 139468)
input_ben = st.sidebar.text_input(
    "Enter Billed Entity Number (BEN)", value="139468"
).strip()

st.sidebar.markdown("---")
st.sidebar.info("ℹ️ **All Funding Years Included:** Data is pulled across all historical years in USAC records.")

# -----------------------------------------------------------------------------
# 3. DEFENSIVE API ENGINE (ALL YEARS)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_all_years(ben_str):
    """Fetches ALL historical Category 1 broadband line items for a target BEN."""
    clean_ben = str(ben_str).strip()
    if not clean_ben:
        return pd.DataFrame(), "Please enter a valid Billed Entity Number (BEN)."

    # Query across all years without funding_year filters
    where_clause = (
        f"(ben_no = '{clean_ben}' OR ben = '{clean_ben}' OR ros_entity_number = '{clean_ben}') "
        f"AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')"
    )
    
    params = {
        "$limit": 5000,
        "$where": where_clause,
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(MASTER_USAC_API, params=params, timeout=20)
        if res.status_code != 200:
            return pd.DataFrame(), f"USAC API Error HTTP {res.status_code}"

        data = res.json()
        if isinstance(data, dict) and "message" in data:
            return pd.DataFrame(), f"USAC API Error: {data['message']}"
            
        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame(), f"No E-Rate Category 1 records found in USAC database for BEN **{clean_ben}**."

        return pd.DataFrame(data), None

    except Exception as e:
        return pd.DataFrame(), f"Network connection error: {str(e)}"


@st.cache_data(ttl=1800)
def fetch_zip_peer_schools(zip_code):
    """Fetches all C1 broadband line items across all years for schools in the same physical ZIP."""
    if not zip_code or zip_code in ["N/A", "None", "", "nan"]:
        return pd.DataFrame()

    clean_zip = str(zip_code).split("-")[0].strip()
    
    where_clause = (
        f"ros_physical_zipcode like '{clean_zip}%' "
        f"AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')"
    )
    
    params = {
        "$limit": 5000,
        "$where": where_clause,
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(MASTER_USAC_API, params=params, timeout=20)
        if res.status_code == 200 and isinstance(res.json(), list):
            return pd.DataFrame(res.json())
    except Exception:
        pass

    return pd.DataFrame()


def process_metrics(df):
    """Normalizes field schema, calculates bandwidth speeds (Mbps), and monthly $/Mbps."""
    if df.empty or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    # Standardize column naming variations across USAC datasets
    df = df.rename(
        columns={
            "ben_name": "organization_name",
            "ros_entity_name": "organization_name_ros",
            "ros_physical_zipcode": "zipcode",
            "ros_physical_state": "state",
        }
    )

    # Convert numeric fields safely
    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    ).fillna(0)

    df["speed"] = pd.to_numeric(
        df.get("download_speed", 0), errors="coerce"
    ).fillna(0)

    # Normalize speed to Mbps
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
    
    # Ensure funding_year is clean string
    if "funding_year" in df.columns:
        df["funding_year"] = df["funding_year"].astype(str)

    return df


# -----------------------------------------------------------------------------
# 4. MAIN APPLICATION RENDER
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Enter a Billed Entity Number (BEN) in the sidebar to search.")
else:
    with st.spinner(f"Querying USAC Open Data across all historical years for BEN {input_ben}..."):
        raw_df, err_msg = fetch_ben_all_years(input_ben)

    if err_msg:
        st.error(err_msg)
    else:
        df = process_metrics(raw_df)

        if df.empty:
            st.warning(f"No C1 Broadband records could be processed for BEN **{input_ben}**.")
        else:
            # Resolve entity name and ZIP metadata dynamically
            entity_name = (
                df.get("organization_name", pd.Series(["Unknown"])).iloc[0]
                or df.get("organization_name_ros", pd.Series(["Unknown"])).iloc[0]
            )
            entity_zip = str(df.get("zipcode", pd.Series(["N/A"])).iloc[0]).split("-")[0].strip()
            entity_state = df.get("state", pd.Series(["N/A"])).iloc[0]

            st.markdown(f"## 🏢 **{entity_name}**")
            st.markdown(
                f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | **Physical ZIP Code:** `{entity_zip}`"
            )

            tab1, tab2 = st.tabs([
                "📊 Yearly Comparison (All Years as Columns)",
                "🗺️ ZIP Code Peer School Benchmarks",
            ])

            # -----------------------------------------------------------------------------
            # TAB 1: ALL YEARS PIVOTED AS COLUMNS
            # -----------------------------------------------------------------------------
            with tab1:
                st.subheader("Historical Category 1 Broadband Metrics (Years in Columns)")

                valid_df = df[df["cost_per_mbps"] > 0].copy()

                if valid_df.empty:
                    st.info("No contracts with valid bandwidth and cost metrics available for aggregation.")
                else:
                    # Matrix 1: Cost / Mbps ($) across Years
                    pivot_rate = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="cost_per_mbps",
                        aggfunc="mean"
                    )

                    # Matrix 2: Max Bandwidth Speed (Mbps) across Years
                    pivot_speed = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="speed_mbps",
                        aggfunc="max"
                    )

                    # Matrix 3: Monthly Recurring Cost ($) across Years
                    pivot_cost = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="monthly_cost",
                        aggfunc="mean"
                    )

                    st.markdown("### 💵 Average Cost / Mbps ($) by Service Provider & Year")
                    st.dataframe(pivot_rate.style.format("${:,.2f}", na_rep="-"), use_container_width=True)

                    st.markdown("### ⚡ Maximum Bandwidth (Mbps) by Service Provider & Year")
                    st.dataframe(pivot_speed.style.format("{:,.0f} Mbps", na_rep="-"), use_container_width=True)

                    st.markdown("### 💰 Monthly Recurring Cost ($) by Service Provider & Year")
                    st.dataframe(pivot_cost.style.format("${:,.2f}", na_rep="-"), use_container_width=True)

                st.markdown("---")
                st.markdown("### Complete Historical Form 471 Line Items Log")
                
                display_cols = [
                    "funding_year",
                    "funding_request_number",
                    "service_provider_name",
                    "spin",
                    "speed_mbps",
                    "monthly_cost",
                    "cost_per_mbps",
                    "product_type",
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

            # -----------------------------------------------------------------------------
            # TAB 2: LOCAL ZIP CODE PEER BENCHMARKING
            # -----------------------------------------------------------------------------
            with tab2:
                st.subheader(f"Local Peer Schools & Libraries in ZIP Code: {entity_zip}")

                if entity_zip in ["N/A", "None", "", "nan"]:
                    st.warning("Could not identify a physical ZIP code for this entity to fetch peer records.")
                else:
                    zip_raw = fetch_zip_peer_schools(entity_zip)
                    zip_df = process_metrics(zip_raw)

                    if zip_df.empty:
                        st.info(f"No peer school or library records found in ZIP Code **{entity_zip}** across all funding years.")
                    else:
                        valid_zip_df = zip_df[zip_df["cost_per_mbps"] > 0]

                        target_avg_rate = valid_df["cost_per_mbps"].mean() if not valid_df.empty else 0
                        zip_avg_rate = valid_zip_df["cost_per_mbps"].mean() if not valid_zip_df.empty else 0

                        c1, c2, c3 = st.columns(3)
                        c1.metric("Target BEN Avg $/Mbps", f"${target_avg_rate:.2f}")
                        c2.metric(f"ZIP {entity_zip} Peer Avg $/Mbps", f"${zip_avg_rate:.2f}")
                        c3.metric("Total Local Line Items", f"{len(zip_df):,}")

                        st.markdown("---")
                        st.markdown(f"### 🏆 Carriers Serving Schools in ZIP {entity_zip}")

                        provider_zip_summary = (
                            valid_zip_df.groupby(["service_provider_name", "spin"])
                            .agg(
                                avg_cost_per_mbps=("cost_per_mbps", "mean"),
                                max_speed_offered=("speed_mbps", "max"),
                                total_records=("monthly_cost", "count"),
                            )
                            .reset_index()
                            .sort_values(by="avg_cost_per_mbps", ascending=True)
                        )

                        st.dataframe(
                            provider_zip_summary.style.format({
                                "avg_cost_per_mbps": "${:,.2f}",
                                "max_speed_offered": "{:,.0f} Mbps",
                            }),
                            use_container_width=True,
                        )

                        st.markdown("---")
                        st.markdown(f"### All Schools & Libraries Contracts in ZIP {entity_zip} (All Years)")

                        peer_cols = [
                            "funding_year",
                            "organization_name",
                            "service_provider_name",
                            "speed_mbps",
                            "monthly_cost",
                            "cost_per_mbps",
                        ]
                        peer_cols_exist = [c for c in peer_cols if c in zip_df.columns]

                        st.dataframe(
                            zip_df[peer_cols_exist].style.format({
                                "speed_mbps": "{:,.0f} Mbps",
                                "monthly_cost": "${:,.2f}",
                                "cost_per_mbps": "${:,.2f}",
                            }),
                            use_container_width=True,
                        )
