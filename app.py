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

st.title("📡 USAC E-Rate Form 471 BEN Intelligence & ZIP Benchmarking")
st.caption("Powered by USAC E-Rate Recipient Details & FRN Open Data (ALL Funding Years).")

# Master Recipient Dataset (contains physical ZIP codes, BENs, speeds, and costs)
MASTER_USAC_API = "https://opendata.usac.org/resource/avi8-svp9.json"
# Backup FRN Line Items Dataset
LINE_ITEMS_API = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Entity Lookup")
input_ben = st.sidebar.text_input(
    "Enter Billed Entity Number (BEN)", value="139468"
).strip()

st.sidebar.info("💡 Funding year filtering has been disabled. Query pulls all available historical years.")

# -----------------------------------------------------------------------------
# 3. DATA FETCHING ENGINE (UNFILTERED BY YEAR)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_all_ben_data(ben_str):
    """Fetches ALL historical Category 1 broadband line items for a BEN across all years."""
    clean_ben = str(ben_str).strip()
    if not clean_ben:
        return pd.DataFrame(), "Please supply a valid BEN."

    # Search Master API without funding year restriction
    params = {
        "$limit": 5000,
        "$where": f"(ben_no = '{clean_ben}' OR ben = '{clean_ben}') AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')",
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(MASTER_USAC_API, params=params, timeout=20)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                return pd.DataFrame(data), None

        # Fallback to Line Items API if Master returns 0 rows
        fallback_params = {
            "$limit": 5000,
            "$where": f"ben = '{clean_ben}' AND (form_471_service_type_name like '%Internet%' OR form_471_service_type_name like '%Data%')",
            "$order": "funding_year DESC",
        }
        res_fb = requests.get(LINE_ITEMS_API, params=fallback_params, timeout=20)
        if res_fb.status_code == 200:
            fb_data = res_fb.json()
            if isinstance(fb_data, list) and len(fb_data) > 0:
                return pd.DataFrame(fb_data), None

        return pd.DataFrame(), f"No records found for BEN **{clean_ben}**."
    except Exception as e:
        return pd.DataFrame(), f"API Connection error: {str(e)}"


@st.cache_data(ttl=1800)
def fetch_zip_peers(zip_code):
    """Fetches all Category 1 broadband line items across ALL years for entities sharing the same ZIP."""
    if not zip_code or zip_code in ["N/A", "None", "", "nan"]:
        return pd.DataFrame()

    clean_zip = str(zip_code).split("-")[0].strip()
    params = {
        "$limit": 5000,
        "$where": f"ros_physical_zipcode like '{clean_zip}%' AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')",
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
    """Normalizes field names, bandwidth speeds (Mbps), and calculates Cost / Mbps."""
    if df.empty or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    # Field normalization across API schema variations
    df = df.rename(
        columns={
            "ben_name": "organization_name",
            "ros_entity_name": "organization_name_ros",
            "ros_physical_zipcode": "zipcode",
            "ros_physical_state": "state",
        }
    )

    # Cost calculation
    cost_col = "monthly_recurring_eligible_cost" if "monthly_recurring_eligible_cost" in df.columns else "monthly_cost"
    df["monthly_cost"] = pd.to_numeric(df.get(cost_col, 0), errors="coerce").fillna(0)

    # Speed calculation
    df["speed"] = pd.to_numeric(df.get("download_speed", 0), errors="coerce").fillna(0)

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
if not input_ben:
    st.info("👈 Enter a Billed Entity Number (BEN) in the sidebar to search.")
else:
    with st.spinner(f"Querying USAC Open Data across all funding years for BEN {input_ben}..."):
        raw_ben_df, err = fetch_all_ben_data(input_ben)

    if err:
        st.error(err)
    else:
        df = process_metrics(raw_ben_df)

        if df.empty:
            st.warning(f"Entity **{input_ben}** was found, but no Category 1 Broadband line items were identified.")
        else:
            # Extract Metadata safely
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
                "📊 Yearly Historical Comparison (All Years as Columns)",
                "🗺️ ZIP Code Peer School Benchmarks",
            ])

            # -----------------------------------------------------------------------------
            # TAB 1: ALL YEARS PIVOTED IN COLUMNS
            # -----------------------------------------------------------------------------
            with tab1:
                st.subheader("Historical Category 1 Broadband Overview Across All Years")

                valid_df = df[df["cost_per_mbps"] > 0].copy()

                if valid_df.empty:
                    st.info("No line items with valid cost and bandwidth data available for aggregation.")
                else:
                    # Metric Pivot Table with Years as Columns
                    pivot_cost = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="monthly_cost",
                        aggfunc="mean"
                    )

                    pivot_mbps = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="speed_mbps",
                        aggfunc="max"
                    )

                    pivot_rate = valid_df.pivot_table(
                        index=["service_provider_name"],
                        columns="funding_year",
                        values="cost_per_mbps",
                        aggfunc="mean"
                    )

                    st.markdown("### 💰 Average Cost / Mbps ($) by Service Provider & Year")
                    st.dataframe(pivot_rate.style.format("${:,.2f}", na_rep="-"), use_container_width=True)

                    st.markdown("### ⚡ Maximum Bandwidth Speed (Mbps) by Service Provider & Year")
                    st.dataframe(pivot_mbps.style.format("{:,.0f} Mbps", na_rep="-"), use_container_width=True)

                    st.markdown("### 💵 Monthly Recurring Cost ($) by Service Provider & Year")
                    st.dataframe(pivot_cost.style.format("${:,.2f}", na_rep="-"), use_container_width=True)

                st.markdown("---")
                st.markdown("### Complete Historical Line Items Log")
                display_cols = [
                    "funding_year",
                    "funding_request_number",
                    "service_provider_name",
                    "spin",
                    "speed_mbps",
                    "monthly_cost",
                    "cost_per_mbps",
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
            # TAB 2: LOCAL PEER COMPARISON IN ZIP CODE
            # -----------------------------------------------------------------------------
            with tab2:
                st.subheader(f"Broadband Benchmarks for Schools & Libraries in ZIP Code: {entity_zip}")

                if entity_zip in ["N/A", "None", "", "nan"]:
                    st.warning("Could not establish a physical ZIP code for this entity to fetch local peer data.")
                else:
                    zip_raw = fetch_zip_peers(entity_zip)
                    zip_df = process_metrics(zip_raw)

                    if zip_df.empty:
                        st.info(f"No peer school records found in ZIP Code **{entity_zip}** across all funding years.")
                    else:
                        valid_zip_df = zip_df[zip_df["cost_per_mbps"] > 0]

                        target_avg_rate = valid_df["cost_per_mbps"].mean() if not valid_df.empty else 0
                        zip_avg_rate = valid_zip_df["cost_per_mbps"].mean() if not valid_zip_df.empty else 0

                        c1, c2, c3 = st.columns(3)
                        c1.metric("Target BEN Avg $/Mbps", f"${target_avg_rate:.2f}")
                        c2.metric(f"ZIP {entity_zip} Peer Avg $/Mbps", f"${zip_avg_rate:.2f}")
                        c3.metric("Total ZIP Peer Line Items", f"{len(zip_df):,}")

                        st.markdown("---")
                        st.markdown(f"### 🏆 Local Service Providers Serving ZIP {entity_zip}")

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
