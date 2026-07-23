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

st.title("📡 USAC E-Rate Form 471 BEN Search & Local Benchmarking")
st.caption("Powered by USAC E-Rate Recipient Details & Commitments Open Data API.")

# Master Dataset: Combines Form 471 Line Items + Recipient Entity Info + Physical ZIPs
MASTER_USAC_API = "https://opendata.usac.org/resource/avi8-svp9.json"
FALLBACK_LINE_ITEMS_API = "https://opendata.usac.org/resource/hbj5-2bpj.json"

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
def fetch_ben_data(ben_str):
    """Fetches C1 broadband records for a BEN using correct USAC SODA field names (ben_no & ben)."""
    clean_ben = str(ben_str).strip()

    # Strategy 1: Search Master Dataset (avi8-svp9) using ben_no & ben
    where_clause = (
        f"(ben_no = '{clean_ben}' OR ben = '{clean_ben}') "
        f"AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')"
    )
    params = {
        "$limit": 1000,
        "$where": where_clause,
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(MASTER_USAC_API, params=params, timeout=15)
        if res.status_code == 200 and len(res.json()) > 0:
            return pd.DataFrame(res.json())

        # Strategy 2: Query Line Items Endpoint (hbj5-2bpj) using correct field 'ben_no'
        line_params = {
            "$limit": 1000,
            "$where": f"ben_no = '{clean_ben}'",
            "$order": "funding_year DESC",
        }
        res_fallback = requests.get(FALLBACK_LINE_ITEMS_API, params=line_params, timeout=15)
        if res_fallback.status_code == 200 and len(res_fallback.json()) > 0:
            return pd.DataFrame(res_fallback.json())

    except Exception as e:
        st.error(f"USAC API Connection Error: {e}")

    return pd.DataFrame()


@st.cache_data(ttl=1800)
def fetch_zip_benchmarks(zip_code):
    """Queries broadband benchmarks across entities sharing the same physical ZIP code."""
    if not zip_code or zip_code in ["N/A", "None", ""]:
        return pd.DataFrame()

    clean_zip = str(zip_code).split("-")[0].strip()
    where_clause = (
        f"ros_physical_zipcode like '{clean_zip}%' "
        f"AND (service_type_name like '%Internet%' OR service_type_name like '%Data%')"
    )
    params = {
        "$limit": 2000,
        "$where": where_clause,
        "$order": "funding_year DESC",
    }

    try:
        res = requests.get(MASTER_USAC_API, params=params, timeout=15)
        if res.status_code == 200 and len(res.json()) > 0:
            return pd.DataFrame(res.json())
    except Exception:
        pass

    return pd.DataFrame()


def process_metrics(df):
    """Normalizes bandwidth speeds to Mbps and calculates Monthly Cost / Mbps."""
    if df.empty:
        return df

    # Normalize column names across endpoints
    df = df.rename(
        columns={
            "ben_name": "organization_name",
            "ros_entity_name": "organization_name_ros",
            "ros_physical_zipcode": "zipcode",
            "ros_physical_state": "state",
        }
    )

    # Cost calculation
    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    ).fillna(0)
    
    # Speed calculation
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
# 4. MAIN APPLICATION
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Enter a Billed Entity Number (BEN) in the sidebar to search.")
else:
    raw_ben_df = fetch_ben_data(input_ben)
    processed_ben_df = process_metrics(raw_ben_df)

    if processed_ben_df.empty:
        st.error(
            f"No E-Rate Category 1 Broadband records were found for BEN **{input_ben}**. "
            f"Please confirm the Billed Entity Number."
        )
    else:
        # Extract metadata dynamically
        org_name = (
            processed_ben_df.get("organization_name", pd.Series(["Unknown Entity"])).iloc[0]
            or processed_ben_df.get("organization_name_ros", pd.Series(["Unknown Entity"])).iloc[0]
        )
        entity_zip = str(processed_ben_df.get("zipcode", pd.Series(["N/A"])).iloc[0]).split("-")[0].strip()
        entity_state = processed_ben_df.get("state", pd.Series(["N/A"])).iloc[0]
        latest_year = processed_ben_df.get("funding_year", pd.Series(["N/A"])).iloc[0]

        st.markdown(f"## 🏢 **{org_name}**")
        st.markdown(
            f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | "
            f"**ZIP Code:** `{entity_zip}` | **Latest Year:** `{latest_year}`"
        )

        tab1, tab2 = st.tabs([
            "📋 Form 471 History & Line Items",
            "🗺️ ZIP Code Provider Benchmarking",
        ])

        # -----------------------------------------------------------------------------
        # TAB 1: FORM 471 DETAILS
        # -----------------------------------------------------------------------------
        with tab1:
            st.subheader("Historical Form 471 Category 1 Broadband Contracts")

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

            cols_exist = [c for c in display_cols if c in processed_ben_df.columns]
            clean_df = processed_ben_df[cols_exist].copy()

            clean_df = clean_df.rename(
                columns={
                    "funding_year": "Funding Year",
                    "funding_request_number": "FRN",
                    "service_provider_name": "Service Provider",
                    "spin": "SPIN",
                    "speed_mbps": "Speed (Mbps)",
                    "monthly_cost": "Monthly Cost ($)",
                    "cost_per_mbps": "Cost / Mbps ($)",
                    "product_type": "Product Description",
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
                label="📥 Export BEN Line Items (CSV)",
                data=clean_df.to_csv(index=False),
                file_name=f"BEN_{input_ben}_471_History.csv",
                mime="text/csv",
            )

        # -----------------------------------------------------------------------------
        # TAB 2: LOCAL BENCHMARKING
        # -----------------------------------------------------------------------------
        with tab2:
            st.subheader(f"Local Carrier Benchmarking in ZIP Code: {entity_zip}")

            zip_raw = fetch_zip_benchmarks(entity_zip)
            zip_df = process_metrics(zip_raw)

            if zip_df.empty:
                st.info(f"No additional local school contracts were found for ZIP Code **{entity_zip}**.")
            else:
                valid_zip_df = zip_df[zip_df["cost_per_mbps"] > 0]
                avg_zip_rate = valid_zip_df["cost_per_mbps"].mean() if not valid_zip_df.empty else 0

                curr_rate = processed_ben_df.iloc[0].get("cost_per_mbps", 0)

                b1, b2 = st.columns(2)
                b1.metric("Target BEN Rate", f"${curr_rate:.2f} / Mbps")
                b2.metric(f"ZIP {entity_zip} Avg Rate", f"${avg_zip_rate:.2f} / Mbps")

                st.markdown("---")
                st.markdown("### 🏆 Active Broadband Providers in this ZIP Code")

                provider_summary = (
                    valid_zip_df.groupby(["service_provider_name", "spin"])
                    .agg(
                        avg_cost_per_mbps=("cost_per_mbps", "mean"),
                        max_speed_offered=("speed_mbps", "max"),
                        total_contracts=("funding_request_number", "nunique"),
                    )
                    .reset_index()
                    .sort_values(by="avg_cost_per_mbps", ascending=True)
                )

                provider_summary = provider_summary.rename(
                    columns={
                        "service_provider_name": "Carrier / Provider",
                        "spin": "SPIN",
                        "avg_cost_per_mbps": "Avg $/Mbps in ZIP",
                        "max_speed_offered": "Max Speed Offered",
                        "total_contracts": "Contracts Count",
                    }
                )

                st.dataframe(
                    provider_summary.style.format({
                        "Avg $/Mbps in ZIP": "${:,.2f}",
                        "Max Speed Offered": "{:,.0f} Mbps",
                    }),
                    use_container_width=True,
                )
