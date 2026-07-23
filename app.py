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

    # Note: funding_year is numeric in USAC SODA, so remove quotes around {year}
    where_clause = f"state = '{state}' AND funding_year = {year} AND form_471_service_type_name = '{svc_type}'"

    params = {
        "$limit": 3000,
        "$where": where_clause,
    }

    try:
        response = requests.get(USAC_API_URL, params=params, timeout=15)
        if response.status_code == 200:
            return pd.DataFrame(response.json())
        else:
            # Displays the exact reason Socrata rejected the query
            st.error(
                f"USAC API Error {response.status_code}: {response.text}"
            )
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Failed to connect to USAC SODA API: {e}")
        return pd.DataFrame()

    st.info(
        f"**Net District Out-of-Pocket Cost:** With an **{e_rate_discount}% E-Rate Discount**, "
        f"the district's net monthly payment under your SPIN **({master_spin})** will be **${out_of_pocket_prop:,.2f}/mo**."
    )
