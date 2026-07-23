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
st.caption(
    "Powered by the USAC E-Rate Open Data SODA API."
)

LINE_ITEMS_API = "https://opendata.usac.org/resource/hbj5-2bpj.json"
BASIC_INFO_API = "https://opendata.usac.org/resource/9s6i-myen.json"

# -----------------------------------------------------------------------------
# 2. SIDEBAR INPUTS
# -----------------------------------------------------------------------------
st.sidebar.header("🔍 Search Parameters")
input_ben = st.sidebar.text_input(
    "Enter Billed Entity Number (BEN)", value="139692"
).strip()


# -----------------------------------------------------------------------------
# 3. DATA FETCHING ENGINE (ROBUST SODA QUERIES)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def fetch_ben_line_items(ben_str):
    """Fetches C1 line items using dual string/numeric BEN handling and broad service type matching."""
    clean_ben = str(ben_str).strip()
    
    # Query matching string OR numeric BEN, plus flexible C1 service type strings
    where_clause = (
        f"(ben = '{clean_ben}' OR ben = {clean_ben}) "
        f"AND (form_471_service_type_name like '%Internet%' OR form_471_service_type_name like '%Data%')"
    )
    
    params = {
        "$limit": 1000,
        "$where": where_clause,
        "$order": "funding_year DESC",
    }
    
    try:
        res = requests.get(LINE_ITEMS_API, params=params, timeout=15)
        if res.status_code == 200 and len(res.json()) > 0:
            return pd.DataFrame(res.json())
        
        # Fallback Query: Query without service type filter if standard search returns empty
        params["$where"] = f"ben = '{clean_ben}' OR ben = {clean_ben}"
        res_fallback = requests.get(LINE_ITEMS_API, params=params, timeout=15)
        return pd.DataFrame(res_fallback.json()) if res_fallback.status_code == 200 else pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching BEN data: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=1800)
def fetch_ben_metadata(ben_str):
    """Fetches Entity ZIP Code and State metadata."""
    clean_ben = str(ben_str).strip()
    params = {
        "$limit": 1,
        "$where": f"ben = '{clean_ben}' OR ben = {clean_ben}",
    }
    try:
        res = requests.get(BASIC_INFO_API, params=params, timeout=15)
        if res.status_code == 200 and len(res.json()) > 0:
            item = res.json()[0]
            raw_zip = item.get("org_zipcode") or item.get("zipcode") or ""
            clean_zip = str(raw_zip).split("-")[0].strip() if raw_zip else "N/A"
            return clean_zip, item.get("org_state", "N/A"), item.get("organization_name", "")
    except Exception:
        pass
    return "N/A", "N/A", ""


@st.cache_data(ttl=1800)
def fetch_zip_line_items(zip_code):
    """Fetches C1 Broadband line items for entities sharing the same physical ZIP code."""
    if not zip_code or zip_code == "N/A":
        return pd.DataFrame()

    # Step 1: Find BENs in the target ZIP
    params_zip = {
        "$limit": 500,
        "$where": f"org_zipcode like '{zip_code}%'",
        "$select": "ben",
    }
    try:
        res_basic = requests.get(BASIC_INFO_API, params=params_zip, timeout=15)
        if res_basic.status_code != 200 or not res_basic.json():
            return pd.DataFrame()

        bens_in_zip = list(set([str(item["ben"]) for item in res_basic.json() if "ben" in item]))
        if not bens_in_zip:
            return pd.DataFrame()

        # Step 2: Query FRN Line Items for all BENs in this ZIP
        formatted_bens = ", ".join([f"'{b}'" for b in bens_in_zip[:40]])
        params_lines = {
            "$limit": 2000,
            "$where": f"ben in({formatted_bens}) AND (form_471_service_type_name like '%Internet%' OR form_471_service_type_name like '%Data%')",
            "$order": "funding_year DESC",
        }
        res_lines = requests.get(LINE_ITEMS_API, params=params_lines, timeout=15)
        return pd.DataFrame(res_lines.json()) if res_lines.status_code == 200 else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def process_metrics(df):
    """Calculates Speed in Mbps and Monthly Cost per Mbps."""
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
# 4. MAIN APPLICATION
# -----------------------------------------------------------------------------
if not input_ben:
    st.info("👈 Enter a Billed Entity Number (BEN) in the sidebar to search.")
else:
    # 1. Load Form 471 Line Items
    raw_ben_df = fetch_ben_line_items(input_ben)
    processed_ben_df = process_metrics(raw_ben_df)

    # 2. Load Entity Metadata
    entity_zip, entity_state, meta_name = fetch_ben_metadata(input_ben)

    if processed_ben_df.empty and not meta_name:
        st.error(f"No USAC records found for BEN **{input_ben}**. Please verify the entity number.")
    else:
        # Extract Entity Name safely
        if not processed_ben_df.empty and "organization_name" in processed_ben_df.columns:
            entity_name = processed_ben_df["organization_name"].iloc[0]
        else:
            entity_name = meta_name if meta_name else f"Entity #{input_ben}"

        # Extract State/ZIP from Line Items if metadata table missed it
        if entity_state == "N/A" and not processed_ben_df.empty and "state" in processed_ben_df.columns:
            entity_state = processed_ben_df["state"].iloc[0]

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
            st.subheader("Historical Form 471 Category 1 Broadband Contracts")

            if processed_ben_df.empty:
                st.warning("No Category 1 Broadband line items found for this BEN.")
            else:
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

            if entity_zip == "N/A":
                st.warning("Could not establish a physical ZIP code for this BEN to perform local benchmarking.")
            else:
                zip_raw = fetch_zip_line_items(entity_zip)
                zip_df = process_metrics(zip_raw)

                if zip_df.empty:
                    st.info(f"No additional school contracts found in ZIP Code **{entity_zip}**.")
                else:
                    valid_zip_df = zip_df[zip_df["cost_per_mbps"] > 0]
                    avg_zip_rate = valid_zip_df["cost_per_mbps"].mean()

                    curr_rate = (
                        processed_ben_df.iloc[0].get("cost_per_mbps", 0)
                        if not processed_ben_df.empty
                        else 0
                    )

                    b1, b2 = st.columns(2)
                    b1.metric("Target BEN Rate", f"${curr_rate:.2f} / Mbps")
                    b2.metric(f"ZIP {entity_zip} Avg Rate", f"${avg_zip_rate:.2f} / Mbps")

                    st.markdown("---")
                    st.markdown("### 🏆 Active Telecom Providers in this ZIP Code")

                    provider_summary = (
                        valid_zip_df.groupby(["service_provider_name", "spin"])
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
                        zip_df[[c for c in zip_display_cols if c in zip_df.columns]].style.format({
                            "speed_mbps": "{:,.0f} Mbps",
                            "monthly_cost": "${:,.2f}",
                            "cost_per_mbps": "${:,.2f}",
                        }),
                        use_container_width=True,
                    )
