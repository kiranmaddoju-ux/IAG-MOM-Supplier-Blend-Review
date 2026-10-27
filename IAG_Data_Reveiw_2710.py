import streamlit as st
import pandas as pd
import numpy as np
import io

# ----------------------------------------------------
# 1. Page Configuration
# ----------------------------------------------------
st.set_page_config(page_title="IAG Tracker Supplier Blend Portal", layout="wide")
st.title("📊 IAG Global Tracker Operations Portal")
st.caption("Tracking Period: June 2026 – Present (October) | Blend Alignment vs Operational Targets")
st.markdown("---")

# ----------------------------------------------------
# 2. Master Blend Target Parser (Internal Change)
# ----------------------------------------------------
@st.cache_data
def load_master_targets():
    """
    Loads target allocations & supplier mappings from internal_master_rules_Used.xlsx
    (or the Internal Change columns in internal_master_rules.xlsx).
    """
    try:
        try:
            df_rules = pd.read_excel("internal_master_rules_Used.xlsx", sheet_name="Blend")
        except FileNotFoundError:
            raw = pd.read_excel("internal_master_rules.xlsx", sheet_name="Blend")
            df_rules = raw.iloc[:, [5, 6, 7, 8]].copy()
            df_rules.columns = ['Unnamed: 0', 'Internal Change', 'Unnamed: 2', 'Unnamed: 3']

        # Forward fill Country names
        df_rules.iloc[:, 0] = df_rules.iloc[:, 0].ffill()

        target_allocations = []
        supplier_mapping = {}

        current_group = None
        for _, row in df_rules.iterrows():
            country = str(row.iloc[0]).strip()
            grp = str(row.iloc[1]).strip()
            supp = str(row.iloc[2]).strip()
            alloc = row.iloc[3]

            if grp.lower() == "group assignments" or country.lower() == "nan":
                continue

            if grp != "nan":
                current_group = grp
                try:
                    alloc_val = float(alloc)
                    target_allocations.append({
                        "Country": country,
                        "Supplier Group": current_group,
                        "Target Allocation": alloc_val
                    })
                except (ValueError, TypeError):
                    pass

            if supp != "nan" and current_group:
                supplier_mapping[(country.lower(), supp.lower())] = current_group

        target_df = pd.DataFrame(target_allocations)
        return target_df, supplier_mapping
    except Exception as e:
        st.error(f"Error loading master blend target rules: {e}")
        return pd.DataFrame(), {}

target_df, supplier_mapping = load_master_targets()

# ----------------------------------------------------
# 3. Data Ingestion & Date Pipeline (From June Onwards)
# ----------------------------------------------------
st.sidebar.markdown("### 📥 Data Refresh Center")
uploaded_file = st.sidebar.file_uploader("Upload Tracker Raw CSV Data", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file, low_memory=False)

    # Locate datetime column
    date_cols = [c for c in ['PS Entry DateTime', 'PS Entry DateTime (Pacific Time Zone)'] if c in df.columns]
    if not date_cols:
        st.error("Missing date column: Could not locate 'PS Entry DateTime' in uploaded file.")
        st.stop()
    
    date_col = date_cols[0]
    # Parse with dayfirst=True to handle DD-MM-YYYY format (e.g., 05-06-2026 = 5th June)
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')

    # Filter records from June 1, 2026 onwards
    start_date = pd.to_datetime("2026-06-01")
    df = df[df[date_col] >= start_date].copy()

    if df.empty:
        st.warning("No records found from June 2026 onwards. Please verify the date column in the uploaded file.")
        st.stop()

    # Create Dynamic Month & ISO Week Labels
    df['Tracking Month'] = df[date_col].dt.strftime('%Y-%m (%B)')

    def assign_dynamic_week(dt):
        if pd.isnull(dt):
            return "Unknown"
        # Standard Monday to Sunday cycle
        start = dt - pd.Timedelta(days=dt.weekday())
        end = start + pd.Timedelta(days=6)
        iso_year, iso_week, _ = dt.isocalendar()
        return f"W{iso_week:02d} ({start.strftime('%b %d')} - {end.strftime('%b %d')})"

    df['Tracking Week'] = df[date_col].apply(assign_dynamic_week)

    # ----------------------------------------------------
    # 4. Supplier Group Assignment (Internal Change Mapping)
    # ----------------------------------------------------
    def clean_supplier_group(row):
        country = str(row.get('Survey Country', '')).strip()
        supplier = str(row.get('Supplier Name', '')).strip()
        existing_group = str(row.get('Supplier Group', '')).strip()

        # 1. Exact match from master excel
        matched = supplier_mapping.get((country.lower(), supplier.lower()))
        if matched:
            return matched

        # 2. Known vendor logic
        if 'Prime Insights' in supplier:
            return 'Group 1'

        if country == 'France':
            if any(s in supplier for s in ['CPX Research', 'Prodege']):
                return 'Group 2'
            return 'Group MP'

        elif country in ['Spain', 'Ireland']:
            if supplier in ['AttaPoll', 'Fusion']:
                return 'Group 2'
            return 'Group MP'

        elif country == 'United States':
            # US Internal Change: Group 2 has DISQO and Fusion
            if supplier in ['DISQO', 'Fusion']:
                return 'Group 2'
            return 'Group MP'

        elif country == 'United Kingdom':
            # UK Internal Change: Group 2 has Fusion, CPX, Branded Research
            if any(s in supplier for s in ['Fusion', 'CPX', 'Branded Research']):
                return 'Group 2'
            return 'Group MP'

        elif country == 'India':
            if supplier in ['AttaPoll', 'CPX Research']:
                return 'Group 2'
            return 'Group MP'

        # Fallback to column text if present
        if 'group 2' in existing_group.lower():
            return 'Group 2'
        return 'Group MP'

    df['Cleaned Supplier Group'] = df.apply(clean_supplier_group, axis=1)

    # ----------------------------------------------------
    # 5. Sidebar View Controls
    # ----------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ View Controls")

    blend_view = st.sidebar.radio(
        "📅 Blend Frequency:",
        options=["Week on Week (WoW)", "Month on Month (MoM)"],
        index=0
    )
    period_col = 'Tracking Week' if "Week" in blend_view else 'Tracking Month'

    # Chronologically sort the periods (from June up to October)
    sorted_dates_df = df.dropna(subset=[date_col]).sort_values(by=date_col)
    periods_order = [p for p in sorted_dates_df[period_col].unique() if p != "Unknown"]

    # Market selection
    countries_list = ['Overall / All Markets'] + sorted([c for c in df['Survey Country'].dropna().unique() if str(c).strip() != ''])
    selected_country = st.sidebar.selectbox("🌐 Market Country Filter:", countries_list)

    # Status filter
    statuses = sorted(df['Respondent Status Description'].dropna().unique())
    default_status = 'Complete' if 'Complete' in statuses else (statuses[0] if statuses else None)
    selected_status = st.sidebar.selectbox("🎯 Respondent Status:", statuses, index=statuses.index(default_status) if default_status else 0)

    filtered_df = df[df['Respondent Status Description'] == selected_status].copy()

    # ----------------------------------------------------
    # 6. KPI Overview Cards
    # ----------------------------------------------------
    total_records = len(filtered_df)
    active_markets = filtered_df['Survey Country'].nunique()
    latest_period = periods_order[-1] if periods_order else "N/A"
    latest_cnt = len(filtered_df[filtered_df[period_col] == latest_period]) if latest_period != "N/A" else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total Cases (June – Present)", f"{total_records:,} Cases", help=f"Status: {selected_status}")
    with c2:
        st.metric("Active Countries", f"{active_markets} Markets")
    with c3:
        st.metric(f"Latest Period ({latest_period})", f"{latest_cnt:,} Cases")

    st.markdown("---")

    # ----------------------------------------------------
    # Helper to Build Crosstabs
    # ----------------------------------------------------
    def build_frequency_table(data, index_col, periods):
        pivot = pd.crosstab(data[index_col], data[period_col])
        for p in periods:
            if p not in pivot.columns:
                pivot[p] = 0
        pivot = pivot[periods].copy()
        
        pivot.loc['Grand Total'] = pivot.sum()
        pivot['Total Volume'] = pivot.sum(axis=1)

        pct_df = pd.DataFrame(index=pivot.index)
        for p in periods:
            tot = pivot.loc['Grand Total', p]
            pct_df[f"{p} %"] = (pivot[p] / tot * 100).round(2).astype(str) + "%" if tot > 0 else "0.00%"
            pct_df[f"{p} (N)"] = pivot[p]

        grand_tot = pivot.loc['Grand Total', 'Total Volume']
        pct_df['Overall Share %'] = (pivot['Total Volume'] / grand_tot * 100).round(2).astype(str) + "%" if grand_tot > 0 else "0.00%"
        pct_df['Total (N)'] = pivot['Total Volume']

        return pivot, pct_df

    # ----------------------------------------------------
    # 7. Render Tables
    # ----------------------------------------------------
    if selected_country == 'Overall / All Markets':
        active_df = filtered_df
        st.subheader(f"🌐 Global View - Supplier Composite Blend ({blend_view})")
    else:
        active_df = filtered_df[filtered_df['Survey Country'] == selected_country]
        st.subheader(f"📍 {selected_country} - Supplier Composite Blend ({blend_view})")

    if not active_df.empty and periods_order:
        # Composite Group Table
        _, group_display = build_frequency_table(active_df, 'Cleaned Supplier Group', periods_order)
        st.dataframe(group_display, use_container_width=True)

        # Target vs Actual Alignment Table
        if selected_country != 'Overall / All Markets' and not target_df.empty:
            st.markdown("### 🎯 Target Blend Alignment & Variance (Internal Change)")
            country_targets = target_df[target_df['Country'].str.lower() == selected_country.lower()].copy()

            if not country_targets.empty:
                actual_counts = active_df.groupby('Cleaned Supplier Group').size()
                total_c = len(active_df)

                alignment_rows = []
                for _, r in country_targets.iterrows():
                    grp = r['Supplier Group']
                    tgt = r['Target Allocation'] * 100
                    actual_n = actual_counts.get(grp, 0)
                    actual_pct = (actual_n / total_c * 100) if total_c > 0 else 0.0
                    delta = actual_pct - tgt

                    status_flag = "🟢 Aligned" if abs(delta) <= 5.0 else ("🔴 Under Quota" if delta < -5.0 else "🟡 Over Quota")

                    alignment_rows.append({
                        "Supplier Group": grp,
                        "Target %": f"{tgt:.1f}%",
                        "Actual %": f"{actual_pct:.2f}%",
                        "Delta (Variance)": f"{delta:+.2f}%",
                        "Actual Completes (N)": actual_n,
                        "Status": status_flag
                    })

                st.dataframe(pd.DataFrame(alignment_rows), use_container_width=True, hide_index=True)
            else:
                st.info(f"No specific target rules found for {selected_country} in the master sheet.")

        # Granular Supplier Breakdown Expander
        with st.expander("🔎 View Granular Supplier Name Breakdown"):
            _, supplier_display = build_frequency_table(active_df, 'Supplier Name', periods_order)
            st.dataframe(supplier_display, use_container_width=True)

        # ----------------------------------------------------
        # 8. Export Center
        # ----------------------------------------------------
        st.markdown("---")
        st.markdown("### 📤 Export Dashboard Data")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            group_display.to_excel(writer, sheet_name='Composite Group Blend')
            if selected_country != 'Overall / All Markets' and not target_df.empty:
                country_targets.to_excel(writer, sheet_name='Target Rules', index=False)
            active_df.to_excel(writer, sheet_name='Filtered Raw Records', index=False)

        st.download_button(
            label=f"📥 Download {selected_country} {blend_view} Report (.xlsx)",
            data=output.getvalue(),
            file_name=f"IAG_Blend_{selected_country.replace(' ', '_')}_{blend_view[:4]}_from_June.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("No records matching the filter criteria found from June 2026 onwards.")

else:
    st.sidebar.info("Upload your latest raw CSV tracking file to view live blends.")
    st.info("👋 Upload your latest tracker CSV export in the left sidebar to generate Week-on-Week and Month-on-Month blend allocations from June 2026 through October 2026.")
	