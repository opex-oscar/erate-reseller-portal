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

st.title("📡 USAC E-Rate BEN Search & ZIP Code Benchmarking")
st.caption(
    "Lookup Form 471 C1 Broadband details by BEN and compare regional carrier pricing within the same ZIP code."
)

USAC_API_URL = "https://opendata.usac.org/resource/hbj5-2bpj.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Search Parameters")
input_ben = st.sidebar.text_input(
    "Enter Billed Entity Number (BEN)", value="139692"
).strip()
reseller_rate = st.sidebar.number_input(
    "Your Proposed Target Rate ($/Mbps/mo)",
    min_value=0.10,
    max_value=25.00,
    value=1.50,
    step=0.25,
)


# -----------------------------------------------------------------------------
# 3. HELPER & DATA FETCHING FUNCTIONS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_history(ben):
    """Fetches all C1 Form 471 line items across ALL funding years for a given BEN."""
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
def fetch_zip_competitors(zip_code):
    """Fetches all C1 lines items for schools within the same ZIP code across recent years."""
    params = {
        "$limit": 2000,
        "$where": f"ros_physical_zipcode = '{zip_code}' AND form_471_service_type_name = 'Data Transmission and/or Internet Access'",
        "$order": "funding_year DESC",
    }
    try:
        res = requests.get(USAC_API_URL, params=params, timeout=15)
        if res.status_code == 200:
            return pd.DataFrame(res.json())
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def process_broadband_metrics(df):
    """Processes speeds into Mbps and calculates Monthly Cost per Mbps."""
    if df.empty:
        return df

    df["monthly_cost"] = pd.to_numeric(
        df.get("monthly_recurring_eligible_cost", 0), errors="coerce"
    )
    df["speed"] = pd.to_numeric(df.get("download_speed", 0), errors="coerce")

    def normalize_mbps(row):
        unit = str(row.get("download_speed_units", "")).lower()
        speed = row["speed"]
        if "gbps" in unit or "giga" in unit:
            return speed * 1000
        return speed

    df["speed_mbps"] = df.apply(normalize_mbps, axis=1)
    df["cost_per_mbps"] = df.apply(
        lambda r: (
            r["monthly_cost"] / r["speed_mbps"] if r["speed_mbps"] > 0 else 0
        ),
        axis=1,
    )
    return df


# -----------------------------------------------------------------------------
# 4. MAIN APP CONTROLLER
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Please enter a BEN in the sidebar to begin.")
else:
    raw_ben_data = fetch_ben_history(input_ben)
    processed_ben_df = process_broadband_metrics(raw_ben_data)

    if processed_ben_df.empty:
        st.warning(
            f"No Category 1 Broadband records found in USAC database for BEN: **{input_ben}**."
        )
        st.caption(
            "Note: Verify if this entity uses Category 1 services or if filings exist under a parent District BEN."
        )
    else:
        # Extract Entity Information
        entity_name = processed_ben_df["organization_name"].iloc[0]
        entity_state = processed_ben_df.get("state", pd.Series(["N/A"])).iloc[0]
        entity_zip = processed_ben_df.get(
            "ros_physical_zipcode", pd.Series(["N/A"])
        ).iloc[0]

        st.markdown(f"## 🏢 **{entity_name}**")
        st.markdown(
            f"**BEN:** `{input_ben}` | **State:** `{entity_state}` | **ZIP Code:** `{entity_zip}`"
        )

        tab1, tab2 = st.tabs([
            "📋 Form 471 History & Line Items",
            "🗺️ ZIP Code Provider Benchmarking",
        ])

        # -----------------------------------------------------------------------------
        # TAB 1: FORM 471 DETAILS
        # -----------------------------------------------------------------------------
        with tab1:
            st.subheader("Historical Form 471 C1 Broadband Contracts")

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

            cols_exist = [
                c for c in display_cols if c in processed_ben_df.columns
            ]
            clean_df = processed_ben_df[cols_exist].copy()

            # Rename for display
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
        # TAB 2: ZIP CODE BENCHMARKING & RECOMMENDATIONS
        # -----------------------------------------------------------------------------
        with tab2:
            st.subheader(
                f"Regional Carrier Benchmarking in ZIP Code: {entity_zip}"
            )

            if entity_zip == "N/A" or not entity_zip:
                st.warning("No ZIP code found on record for this BEN.")
            else:
                zip_data = fetch_zip_competitors(entity_zip)
                zip_df = process_broadband_metrics(zip_data)

                if zip_df.empty:
                    st.info(
                        f"No surrounding school filings found in ZIP Code **{entity_zip}**."
                    )
                else:
                    # Filter out zero values for stats
                    valid_zip_df = zip_df[zip_df["cost_per_mbps"] > 0]
                    avg_zip_rate = valid_zip_df["cost_per_mbps"].mean()

                    # Find current BEN latest rate
                    latest_ben_row = processed_ben_df.iloc[0]
                    curr_rate = latest_ben_row.get("cost_per_mbps", 0)
                    curr_speed = latest_ben_row.get("speed_mbps", 0)
                    curr_cost = latest_ben_row.get("monthly_cost", 0)

                    # Benchmarking Summary Metrics
                    b1, b2, b3 = st.columns(3)
                    b1.metric("Current BEN Rate", f"${curr_rate:.2f} / Mbps")
                    b2.metric("ZIP Code Avg Rate", f"${avg_zip_rate:.2f} / Mbps")
                    b3.metric(
                        "Your Proposed Target Rate", f"${reseller_rate:.2f} / Mbps"
                    )

                    st.markdown("---")
                    st.markdown("### 🏆 Active Telecom Providers in this ZIP Code")

                    # Aggregate Providers operating in this ZIP Code
                    provider_summary = (
                        valid_zip_df.groupby(
                            ["service_provider_name", "spin"]
                        )
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
                            "avg_cost_per_mbps": "Avg $/Mbps in ZIP",
                            "max_speed_offered": "Max Speed Offered",
                            "total_contracts": "Local Contracts Count",
                        }
                    )

                    st.dataframe(
                        provider_summary.style.format({
                            "Avg $/Mbps in ZIP": "${:,.2f}",
                            "Max Speed Offered": "{:,.0f} Mbps",
                        }),
                        use_container_width=True,
                    )

                    st.markdown("---")
                    st.markdown("### 💡 Recommended Upgrade & Reseller Opportunities")

                    # Recommendation Engine
                    if curr_speed > 0:
                        target_cost_same_speed = curr_speed * reseller_rate
                        target_cost_double_speed = (curr_speed * 2) * reseller_rate

                        st.success(f"""
                        **Carrier Recommendation for {entity_name}:**
                        * **Current Setup:** {curr_speed:,.0f} Mbps @ **${curr_cost:,.2f}/month** (${curr_rate:.2f}/Mbps)
                        * **Option A (Cost Savings at Same Speed):** Keep **{curr_speed:,.0f} Mbps** at your wholesale rate of **${reseller_rate:.2f}/Mbps** $\rightarrow$ **${target_cost_same_speed:,.2f}/month** (Save **${curr_cost - target_cost_same_speed:,.2f}/mo**).
                        * **Option B (Bandwidth Upgrade):** Double speed to **{curr_speed * 2:,.0f} Mbps** at your wholesale rate $\rightarrow$ **${target_cost_double_speed:,.2f}/month**.
                        """)

                    st.markdown("### All ZIP Code School Contracts")
                    zip_display_cols = [
                        "funding_year",
                        "organization_name",
                        "service_provider_name",
                        "speed_mbps",
                        "monthly_cost",
                        "cost_per_mbps",
                    ]
                    st.dataframe(
                        zip_df[
                            [c for c in zip_display_cols if c in zip_df.columns]
                        ].style.format({
                            "speed_mbps": "{:,.0f} Mbps",
                            "monthly_cost": "${:,.2f}",
                            "cost_per_mbps": "${:,.2f}",
                        }),
                        use_container_width=True,
                    )
