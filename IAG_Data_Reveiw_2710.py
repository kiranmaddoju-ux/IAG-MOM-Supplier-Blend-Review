import streamlit as st
import pandas as pd
import numpy as np

# ----------------------------------------------------
# 1. Page Configuration & Layout
# ----------------------------------------------------
st.set_page_config(
    page_title="IAG Tracker | Completes Blend Portal",
    page_icon="✈️",
    layout="wide"
)

st.title("✈️ IAG Global Tracker — Completes Blend Portal")
st.caption("Tracking Period: **June 2026 – Present (October)** | Status: **Completes Only**")
st.markdown("---")

# ----------------------------------------------------
# 2. Master Blend Target Parser (Internal Change)
# ----------------------------------------------------
@st.cache_data
def load_master_targets():
    try:
        try:
            df_rules = pd.read_excel("internal_master_rules_Used.xlsx", sheet_name="Blend")
        except FileNotFoundError:
            raw = pd.read_excel("internal_master_rules.xlsx", sheet_name="Blend")
            df_rules = raw.iloc[:, [5, 6, 7, 8]].copy()
            df_rules.columns = ['Unnamed: 0', 'Internal Change', 'Unnamed: 2', 'Unnamed: 3']

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

        return pd.DataFrame(target_allocations), supplier_mapping
    except Exception as e:
        st.error(f"Error loading master blend targets: {e}")
        return pd.DataFrame(), {}

target_df, supplier_mapping = load_master_targets()

# ----------------------------------------------------
# 3. Sidebar Ingestion & Navigation
# ----------------------------------------------------
st.sidebar.markdown("### 📥 Upload Data")
uploaded_file = st.sidebar.file_uploader("Upload Tracker Raw CSV", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file, low_memory=False)

    # 1. Strictly filter for 'Complete' status only
    status_col = 'Respondent Status Description'
    if status_col in df.columns:
        df = df[df[status_col].astype(str).str.strip().str.lower() == 'complete'].copy()
    else:
        st.error(f"Missing column '{status_col}' in uploaded file.")
        st.stop()

    if df.empty:
        st.warning("No records found with status 'Complete'.")
        st.stop()

    # 2. Parse timestamps with dayfirst=True (June = 06)
    date_cols = [c for c in ['PS Entry DateTime', 'PS Entry DateTime (Pacific Time Zone)'] if c in df.columns]
    if not date_cols:
        st.error("Missing date column: Could not find 'PS Entry DateTime'.")
        st.stop()

    date_col = date_cols[0]
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')

    # Filter from June 1st, 2026 onwards
    df = df[df[date_col] >= pd.to_datetime("2026-06-01")].copy()

    if df.empty:
        st.warning("No complete records found from June 2026 onwards.")
        st.stop()

    # 3. Derive Monthly & Weekly bucketing
    df['Month'] = df[date_col].dt.strftime('%B %Y')
    df['Month_Sort'] = df[date_col].dt.strftime('%Y-%m')

    def assign_dynamic_week(dt):
        if pd.isnull(dt):
            return "Unknown"
        start = dt - pd.Timedelta(days=dt.weekday())
        end = start + pd.Timedelta(days=6)
        iso_year, iso_week, _ = dt.isocalendar()
        return f"W{iso_week:02d} ({start.strftime('%b %d')} - {end.strftime('%b %d')})"

    df['Week'] = df[date_col].apply(assign_dynamic_week)

    # 4. Supplier Group Assignment
    def clean_group(row):
        country = str(row.get('Survey Country', '')).strip()
        supplier = str(row.get('Supplier Name', '')).strip()
        existing_group = str(row.get('Supplier Group', '')).strip()

        matched = supplier_mapping.get((country.lower(), supplier.lower()))
        if matched:
            return matched

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
            if supplier in ['DISQO', 'Fusion']:
                return 'Group 2'
            return 'Group MP'
        elif country == 'United Kingdom':
            if any(s in supplier for s in ['Fusion', 'CPX', 'Branded Research']):
                return 'Group 2'
            return 'Group MP'
        elif country == 'India':
            if supplier in ['AttaPoll', 'CPX Research']:
                return 'Group 2'
            return 'Group MP'

        if 'group 2' in existing_group.lower():
            return 'Group 2'
        return 'Group MP'

    df['Cleaned Supplier Group'] = df.apply(clean_group, axis=1)

    # ----------------------------------------------------
    # 4. Sidebar Controls
    # ----------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ View Controls")

    blend_view = st.sidebar.radio(
        "📅 Blend Frequency:",
        options=["Week on Week (WoW)", "Month on Month (MoM)"],
        index=0
    )
    period_col = 'Week' if "Week" in blend_view else 'Month'

    # Chronologically sorted periods
    sorted_df = df.dropna(subset=[date_col]).sort_values(by=date_col)
    periods_order = [p for p in sorted_df[period_col].unique() if p != "Unknown"]

    # Market Selection
    countries_list = ['All Markets'] + sorted([c for c in df['Survey Country'].dropna().unique() if str(c).strip() != ''])
    selected_country = st.sidebar.selectbox("🌐 Country / Market:", countries_list)

    # Filter by Country
    active_df = df if selected_country == 'All Markets' else df[df['Survey Country'] == selected_country].copy()

    # ----------------------------------------------------
    # 5. Top KPI Summary Cards
    # ----------------------------------------------------
    total_completes = len(active_df)
    active_periods_count = len(periods_order)
    latest_period = periods_order[-1] if periods_order else "N/A"
    latest_completes = len(active_df[active_df[period_col] == latest_period]) if periods_order else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Completes", f"{total_completes:,}")
    with c2:
        st.metric("Market Filter", selected_country)
    with c3:
        st.metric(f"Latest Period ({latest_period})", f"{latest_completes:,} Completes")
    with c4:
        st.metric("Total Tracking Periods", f"{active_periods_count} Periods")

    st.markdown("---")

    # ----------------------------------------------------
    # 6. Flipped Crosstab Table (Periods = Rows, Groups = Columns)
    # ----------------------------------------------------
    st.subheader(f"📊 {selected_country} — {blend_view} Completes Blend")
    st.caption("Rows represent chronological periods; columns represent Supplier Groups.")

    if not active_df.empty:
        # Standard group order
        all_groups = ['Group 1', 'Group 2', 'Group MP']
        actual_groups_found = [g for g in all_groups if g in active_df['Cleaned Supplier Group'].unique()]
        other_groups = [g for g in active_df['Cleaned Supplier Group'].unique() if g not in all_groups]
        groups_order = actual_groups_found + other_groups

        # Crosstab with periods as index and groups as columns
        ct = pd.crosstab(active_df[period_col], active_df['Cleaned Supplier Group'])
        ct = ct.reindex(index=periods_order, columns=groups_order, fill_value=0)

        # Row totals (completes per period)
        row_totals = ct.sum(axis=1)

        # Build clean flipped table
        flipped_df = pd.DataFrame(index=ct.index)
        for g in groups_order:
            flipped_df[f"{g} %"] = (ct[g] / row_totals * 100).round(1).astype(str) + "%"
            flipped_df[f"{g} (N)"] = ct[g]

        flipped_df['Total Completes (N)'] = row_totals

        # Add Overall / Total Row
        grand_total_row = {}
        grand_sum = ct.sum()
        grand_n_all = grand_sum.sum()
        for g in groups_order:
            g_tot = grand_sum[g]
            grand_total_row[f"{g} %"] = f"{(g_tot / grand_n_all * 100):.1f}%" if grand_n_all > 0 else "0.0%"
            grand_total_row[f"{g} (N)"] = g_tot
        grand_total_row['Total Completes (N)'] = grand_n_all

        flipped_df.loc['Grand Total'] = pd.Series(grand_total_row)

        st.dataframe(flipped_df, use_container_width=True)

        # ----------------------------------------------------
        # 7. Alignment vs Target Quota (Internal Change)
        # ----------------------------------------------------
        if selected_country != 'All Markets' and not target_df.empty:
            st.markdown("### 🎯 Alignment vs Master Targets")
            country_targets = target_df[target_df['Country'].str.lower() == selected_country.lower()]

            if not country_targets.empty:
                group_counts = active_df['Cleaned Supplier Group'].value_counts()
                total_c = len(active_df)

                align_cols = st.columns(len(country_targets))
                align_rows = []

                for idx, (_, r) in enumerate(country_targets.iterrows()):
                    grp = r['Supplier Group']
                    target_pct = r['Target Allocation'] * 100
                    actual_n = group_counts.get(grp, 0)
                    actual_pct = (actual_n / total_c * 100) if total_c > 0 else 0.0
                    delta = actual_pct - target_pct

                    status = "🟢 Aligned" if abs(delta) <= 3.0 else ("🟡 Over Quota" if delta > 3.0 else "🔴 Under Quota")

                    align_rows.append({
                        "Supplier Group": grp,
                        "Target Allocation": f"{target_pct:.1f}%",
                        "Cumulative Actual": f"{actual_pct:.2f}%",
                        "Delta (Variance)": f"{delta:+.2f}%",
                        "Achieved Completes": f"{actual_n:,}",
                        "Status": status
                    })

                    with align_cols[idx % len(align_cols)]:
                        st.metric(
                            label=f"{grp} (Target {target_pct:.0f}%)",
                            value=f"{actual_pct:.1f}%",
                            delta=f"{delta:+.1f}% vs Target"
                        )

                st.dataframe(pd.DataFrame(align_rows), use_container_width=True, hide_index=True)

        # ----------------------------------------------------
        # 8. Visual Trend Chart
        # ----------------------------------------------------
        with st.expander("📈 View Blend Trend Chart", expanded=True):
            chart_data = ct.copy()
            st.bar_chart(chart_data)

        # ----------------------------------------------------
        # 9. Supplier Drilldown Expander
        # ----------------------------------------------------
        with st.expander("🔎 Granular Supplier Name Breakdown"):
            supp_ct = pd.crosstab(active_df['Supplier Name'], active_df[period_col])
            supp_ct = supp_ct.reindex(columns=periods_order, fill_value=0)
            supp_ct['Total Completes'] = supp_ct.sum(axis=1)
            supp_ct = supp_ct.sort_values(by='Total Completes', ascending=False)
            st.dataframe(supp_ct, use_container_width=True)

    else:
        st.warning("No records found for the selected market.")

else:
    st.info("👈 Upload your tracker CSV export in the sidebar to populate the dashboard.")
