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
# 3. Sidebar Ingestion & Data Preparation
# ----------------------------------------------------
st.sidebar.markdown("### 📥 1. Upload Data")
uploaded_file = st.sidebar.file_uploader("Upload Tracker Raw CSV", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file, low_memory=False)

    # Strictly filter for Completes only
    status_col = 'Respondent Status Description'
    if status_col in df.columns:
        df = df[df[status_col].astype(str).str.strip().str.lower() == 'complete'].copy()
    else:
        st.error(f"Missing column '{status_col}' in uploaded file.")
        st.stop()

    if df.empty:
        st.warning("No records found with status 'Complete'.")
        st.stop()

    # Parse timestamps with dayfirst=True
    date_cols = [c for c in ['PS Entry DateTime', 'PS Entry DateTime (Pacific Time Zone)'] if c in df.columns]
    if not date_cols:
        st.error("Missing date column: Could not find 'PS Entry DateTime'.")
        st.stop()

    date_col = date_cols[0]
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')

    # Filter from June 1st onwards
    df = df[df[date_col] >= pd.to_datetime("2026-06-01")].copy()

    if df.empty:
        st.warning("No complete records found from June 2026 onwards.")
        st.stop()

    # Generate Month & ISO Week Labels
    df['Month'] = df[date_col].dt.strftime('%B %Y')
    
    def assign_dynamic_week(dt):
        if pd.isnull(dt):
            return "Unknown"
        start = dt - pd.Timedelta(days=dt.weekday())
        end = start + pd.Timedelta(days=6)
        iso_year, iso_week, _ = dt.isocalendar()
        return f"W{iso_week:02d} ({start.strftime('%b %d')} - {end.strftime('%b %d')})"

    df['Week'] = df[date_col].apply(assign_dynamic_week)

    # Supplier Group Mapping
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
    # 4. Sidebar View & Period Controls
    # ----------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ 2. View & Period Controls")

    blend_view = st.sidebar.radio(
        "📅 Blend Frequency:",
        options=["Week on Week (WoW)", "Month on Month (MoM)"],
        index=0
    )
    period_col = 'Week' if "Week" in blend_view else 'Month'
    period_label = "Week" if "Week" in blend_view else "Month"

    sorted_df = df.dropna(subset=[date_col]).sort_values(by=date_col)
    available_periods = [p for p in sorted_df[period_col].unique() if p != "Unknown"]

    # Market Selection
    countries_list = ['All Markets'] + sorted([c for c in df['Survey Country'].dropna().unique() if str(c).strip() != ''])
    selected_country = st.sidebar.selectbox("🌐 Country / Market:", countries_list)

    active_df = df if selected_country == 'All Markets' else df[df['Survey Country'] == selected_country].copy()

    # Dynamic Filter / Comparison Mode
    filter_mode = st.sidebar.radio(
        f"🔍 {period_label} Display Mode:",
        options=[f"⚡ Compare with Previous {period_label}", "🎯 Custom Selection", "📜 View All Periods"],
        index=0
    )

    if filter_mode == f"⚡ Compare with Previous {period_label}":
        selected_target_period = st.sidebar.selectbox(
            f"Select Target {period_label}:",
            options=list(reversed(available_periods)),
            index=0
        )
        target_idx = available_periods.index(selected_target_period)
        if target_idx > 0:
            prev_period = available_periods[target_idx - 1]
            selected_periods = [prev_period, selected_target_period]
            st.sidebar.caption(f"Comparing: **{prev_period}** ➔ **{selected_target_period}**")
        else:
            selected_periods = [selected_target_period]
            st.sidebar.caption("First period in dataset (no prior period to compare).")

    elif filter_mode == "🎯 Custom Selection":
        default_selection = available_periods[-2:] if len(available_periods) >= 2 else available_periods
        selected_periods = st.sidebar.multiselect(
            f"Select Specific {period_label}(s):",
            options=available_periods,
            default=default_selection
        )
    else:
        selected_periods = available_periods

    if not selected_periods:
        st.warning(f"Please select at least one {period_label} to display.")
        st.stop()

    filtered_period_df = active_df[active_df[period_col].isin(selected_periods)].copy()

    # ----------------------------------------------------
    # 5. Top KPI Summary Cards
    # ----------------------------------------------------
    total_completes_period = len(filtered_period_df)
    primary_period = selected_periods[-1]
    primary_count = len(filtered_period_df[filtered_period_df[period_col] == primary_period])
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Completes (View)", f"{total_completes_period:,}")
    with c2:
        st.metric("Market Filter", selected_country)
    with c3:
        st.metric(f"Current {period_label} ({primary_period})", f"{primary_count:,} Completes")
    with c4:
        st.metric("Periods in View", f"{len(selected_periods)} {period_label}(s)")

    st.markdown("---")

    # ----------------------------------------------------
    # 6. Period Comparison Summary (When 2 Periods Selected)
    # ----------------------------------------------------
    all_groups = ['Group 1', 'Group 2', 'Group MP']
    actual_groups_found = [g for g in all_groups if g in active_df['Cleaned Supplier Group'].unique()]
    other_groups = [g for g in active_df['Cleaned Supplier Group'].unique() if g not in all_groups]
    groups_order = actual_groups_found + other_groups

    comp_deltas = {}
    if len(selected_periods) == 2:
        p_prev, p_curr = selected_periods[0], selected_periods[1]
        st.subheader(f"🔄 Direct Comparison: {p_curr} vs Previous ({p_prev})")
        
        curr_subset = filtered_period_df[filtered_period_df[period_col] == p_curr]
        prev_subset = filtered_period_df[filtered_period_df[period_col] == p_prev]

        curr_tot = len(curr_subset)
        prev_tot = len(prev_subset)

        comp_rows = []
        for g in groups_order:
            curr_n = len(curr_subset[curr_subset['Cleaned Supplier Group'] == g])
            prev_n = len(prev_subset[prev_subset['Cleaned Supplier Group'] == g])

            curr_pct = (curr_n / curr_tot * 100) if curr_tot > 0 else 0.0
            prev_pct = (prev_n / prev_tot * 100) if prev_tot > 0 else 0.0
            delta_pct = curr_pct - prev_pct
            comp_deltas[g] = delta_pct

            shift_symbol = "🔺" if delta_pct > 0 else ("🔻" if delta_pct < 0 else "➖")

            comp_rows.append({
                "Supplier Group": g,
                f"Previous ({p_prev}) %": f"{prev_pct:.1f}%",
                f"Previous ({p_prev}) (N)": prev_n,
                f"Current ({p_curr}) %": f"{curr_pct:.1f}%",
                f"Current ({p_curr}) (N)": curr_n,
                f"{period_label}-over-{period_label} Shift": f"{shift_symbol} {delta_pct:+.1f}%"
            })

        st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
        st.markdown("---")

    # ----------------------------------------------------
    # 7. Flipped Table View (Periods = Rows, Groups = Columns)
    # ----------------------------------------------------
    st.subheader(f"📋 {selected_country} — {blend_view} Performance Table")
    st.caption("Rows represent periods in chronological sequence; columns represent Supplier Group shares.")

    if not filtered_period_df.empty:
        ct = pd.crosstab(filtered_period_df[period_col], filtered_period_df['Cleaned Supplier Group'])
        ct = ct.reindex(index=selected_periods, columns=groups_order, fill_value=0)

        row_totals = ct.sum(axis=1)

        flipped_df = pd.DataFrame(index=ct.index)
        for g in groups_order:
            flipped_df[f"{g} %"] = (ct[g] / row_totals * 100).round(1).astype(str) + "%"
            flipped_df[f"{g} (N)"] = ct[g]

        flipped_df['Total Completes (N)'] = row_totals

        grand_total_row = {}
        grand_sum = ct.sum()
        grand_n_all = grand_sum.sum()
        for g in groups_order:
            g_tot = grand_sum[g]
            grand_total_row[f"{g} %"] = f"{(g_tot / grand_n_all * 100):.1f}%" if grand_n_all > 0 else "0.0%"
            grand_total_row[f"{g} (N)"] = g_tot
        grand_total_row['Total Completes (N)'] = grand_n_all

        flipped_df.loc['Total (Selected)'] = pd.Series(grand_total_row)
        st.dataframe(flipped_df, use_container_width=True)

        # ----------------------------------------------------
        # 8. Alignment vs Target Quota (Internal Change)
        # ----------------------------------------------------
        alignment_summary = {}
        if selected_country != 'All Markets' and not target_df.empty:
            st.markdown("### 🎯 Alignment vs Master Blend Targets")
            country_targets = target_df[target_df['Country'].str.lower() == selected_country.lower()]

            if not country_targets.empty:
                group_counts = filtered_period_df['Cleaned Supplier Group'].value_counts()
                total_c = len(filtered_period_df)

                align_cols = st.columns(len(country_targets))
                align_rows = []

                for idx, (_, r) in enumerate(country_targets.iterrows()):
                    grp = r['Supplier Group']
                    target_pct = r['Target Allocation'] * 100
                    actual_n = group_counts.get(grp, 0)
                    actual_pct = (actual_n / total_c * 100) if total_c > 0 else 0.0
                    delta = actual_pct - target_pct

                    status = "🟢 Aligned" if abs(delta) <= 3.0 else ("🟡 Over Quota" if delta > 3.0 else "🔴 Under Quota")
                    alignment_summary[grp] = {
                        "target": target_pct,
                        "actual": actual_pct,
                        "delta": delta,
                        "status": status,
                        "count": actual_n
                    }

                    align_rows.append({
                        "Supplier Group": grp,
                        "Target Allocation": f"{target_pct:.1f}%",
                        "Actual Achieved": f"{actual_pct:.2f}%",
                        "Variance (Delta)": f"{delta:+.2f}%",
                        "Completes (N)": f"{actual_n:,}",
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
        # 9. Supplier Drilldown Expander
        # ----------------------------------------------------
        with st.expander("🔎 Granular Supplier Breakdown (Selected Periods)"):
            supp_ct = pd.crosstab(filtered_period_df['Supplier Name'], filtered_period_df[period_col])
            supp_ct = supp_ct.reindex(columns=selected_periods, fill_value=0)
            supp_ct['Total Completes'] = supp_ct.sum(axis=1)
            supp_ct = supp_ct.sort_values(by='Total Completes', ascending=False)
            st.dataframe(supp_ct, use_container_width=True)

        # ----------------------------------------------------
        # 10. Automated Country Summary Notes Box
        # ----------------------------------------------------
        st.markdown("---")
        st.subheader(f"📝 Executive Operational Notes: {selected_country}")

        with st.container(border=True):
            if selected_country == 'All Markets':
                st.markdown(f"""
                * **Overall Scope**: Showing **{total_completes_period:,}** total complete completes across all active markets in the selected time scope.
                * **Aggregation**: Currently reviewing data aggregated by **{blend_view}**.
                * **Operational Guideline**: Select an individual country from the sidebar to review specific quota rules, supplier group balances, and action recommendations.
                """)
            else:
                top_suppliers = (
                    filtered_period_df['Supplier Name']
                    .value_counts()
                    .head(3)
                    .to_dict()
                )
                top_supp_str = ", ".join([f"**{k}** ({v:,} completes)" for k, v in top_suppliers.items()])

                # Bullet 1: Top Contributors
                st.markdown(f"**1. Leading Panel Contributors in {selected_country}:**\n* Top sources: {top_supp_str}")

                # Bullet 2: Target Quota Alignment Notes
                if alignment_summary:
                    notes_list = []
                    actions = []
                    for grp, info in alignment_summary.items():
                        delta_sign = f"+{info['delta']:.1f}%" if info['delta'] > 0 else f"{info['delta']:.1f}%"
                        notes_list.append(f"**{grp}**: Actual is **{info['actual']:.1f}%** vs Target **{info['target']:.0f}%** ({info['status']}, {delta_sign})")
                        
                        if info['delta'] > 3.0:
                            actions.append(f"Throttle/cap **{grp}** intake (running {delta_sign} above target).")
                        elif info['delta'] < -3.0:
                            actions.append(f"Boost/prioritize sample for **{grp}** (lagging by {delta_sign}).")

                    st.markdown("**2. Quota Health & Target Deviations:**")
                    for n in notes_list:
                        st.markdown(f"* {n}")

                    # Bullet 3: WoW / MoM Shift Dynamics
                    if comp_deltas:
                        st.markdown(f"**3. {period_label}-on-{period_label} Movement Dynamic:**")
                        for grp, d in comp_deltas.items():
                            direction = "increased" if d > 0 else ("decreased" if d < 0 else "remained flat")
                            st.markdown(f"* **{grp}** {direction} by **{abs(d):.1f}%** compared to {selected_periods[0]}.")

                    # Bullet 4: Action Items
                    st.markdown("**4. Recommended Operational Actions:**")
                    if actions:
                        for act in actions:
                            st.markdown(f"* ⚠️ {act}")
                    else:
                        st.markdown("* ✅ All supplier groups are within the acceptable ±3.0% tolerance band. Maintain current allocation pacing.")
                else:
                    st.info(f"Master blend targets are not configured for {selected_country} in the internal rules workbook.")

    else:
        st.warning("No records found for the selected filter.")

else:
    st.info("👈 Upload your tracker CSV export in the sidebar to populate the dashboard.")
