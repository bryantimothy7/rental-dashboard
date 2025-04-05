import requests
import base64
import json

def save_to_github(file_path="data.xlsx"):
    """Save the Excel file to GitHub repository"""
    try:
        # Read the file
        with open(file_path, "rb") as file:
            content = file.read()
        
        # Encode file content
        encoded_content = base64.b64encode(content).decode()
        
        # GitHub API info - replace these values with your own
        github_token = st.secrets["github"]["token"]
        repo_owner = "bryantimothy7"  # Change this to your GitHub username
        repo_name = "rental-dashboard"         # Change this to your repository name
        
        # API headers
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Get current file sha (needed for update)
        r = requests.get(
            f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}",
            headers=headers
        )
        
        # Check if file exists
        if r.status_code == 200:
            sha = r.json()["sha"]
            # Prepare API request to update existing file
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
            data = {
                "message": "Update data from Streamlit app",
                "content": encoded_content,
                "sha": sha
            }
        else:
            # Prepare API request to create new file
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
            data = {
                "message": "Create data from Streamlit app",
                "content": encoded_content
            }
        
        # Commit the file
        response = requests.put(url, headers=headers, data=json.dumps(data))
        
        if response.status_code in [200, 201]:
            return True
        else:
            st.error(f"GitHub API error: {response.status_code}, {response.json()}")
            return False
            
    except Exception as e:
        st.error(f"Error saving to GitHub: {e}")
        return False
        
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

YEARS_AHEAD = 10
RENEWAL_RATE = 0.07

def format_rupiah(value):
    return f"Rp {value:,.0f}".replace(",", ".")

def calculate_lease_end(start_date, lease_years):
    return start_date.replace(year=start_date.year + lease_years)

def parse_custom_split(split_str, years):
    try:
        percentages = [float(p.strip()) for p in split_str.split("/") if p.strip()]
        if len(percentages) != years or abs(sum(percentages) - 100) > 0.1:
            return None
        return [p / 100 for p in percentages]
    except:
        return None

def project_income_with_breakdown(df, years_before=1, years_after=3):
    # Get current year
    current_year = datetime.now().year
    min_year = current_year - years_before
    max_year = current_year + years_after
    
    # Initialize projections dict with 0 for all years in range
    projections = {year: 0 for year in range(min_year, max_year + 1)}
    
    # Create breakdown dict to track individual tenant contributions
    breakdown = {year: {} for year in range(min_year, max_year + 1)}
    
    for _, row in df.iterrows():
        try:
            tenant = row["Tenant"]
            start_date = pd.to_datetime(row["Start Date"])
            start_year = start_date.year
            lease_duration = int(row["Lease Duration (Years)"])
            rent_per_year = float(row["Projected Income (Rp/year)"])
            scheme = row.get("Payment Scheme", "Split Per Year")
            custom_split = parse_custom_split(str(row.get("Custom Split (%)", "")), lease_duration)
            
            # Calculate end year of current lease
            end_year = start_year + lease_duration
            
            # Project income for years in our display range
            for display_year in range(min_year, max_year + 1):
                # Calculate which lease cycle this display year belongs to
                years_since_start = display_year - start_year
                if years_since_start < 0:
                    continue  # Skip years before the lease starts
                
                current_cycle = years_since_start // lease_duration
                cycle_start_year = start_year + (current_cycle * lease_duration)
                years_into_cycle = display_year - cycle_start_year
                
                # Only include if within lease duration
                if years_into_cycle >= 0 and years_into_cycle < lease_duration:
                    income_for_year = 0
                    
                    if scheme == "Full Lease Upfront" and years_into_cycle == 0:
                        # Full payment happens in first year of each cycle
                        income_for_year = rent_per_year * lease_duration
                    elif scheme == "Custom Split" and custom_split and years_into_cycle < len(custom_split):
                        # Use custom split percentages
                        income_for_year = rent_per_year * lease_duration * custom_split[years_into_cycle]
                    else:  # Default: Split evenly
                        income_for_year = rent_per_year
                    
                    # Add to total projections
                    projections[display_year] += income_for_year
                    
                    # Add to breakdown
                    breakdown[display_year][tenant] = breakdown[display_year].get(tenant, 0) + income_for_year
                
        except Exception as e:
            # Skip entries with errors
            continue

    # Convert to DataFrame and format for summary
    years = sorted(projections.keys())
    proj_df = pd.DataFrame([
        {"Year": year, "Projected Total Income (Rp)": projections[year]} 
        for year in years
    ])
    
    # Highlight current year
    proj_df["Note"] = ""
    if current_year in proj_df["Year"].values:
        proj_df.loc[proj_df["Year"] == current_year, "Note"] = "Current Year"
    
    # Format currency for summary AFTER calculations are done
    proj_df["Projected Total Income (Rp)"] = proj_df["Projected Total Income (Rp)"].apply(lambda x: format_rupiah(x))
    
    # Create breakdown dataframes
    breakdown_dfs = {}
    for year in years:
        if breakdown[year]:
            # Store raw values for percentage calculation
            raw_amounts = {tenant: amount for tenant, amount in breakdown[year].items()}
            total = sum(raw_amounts.values())
            
            # Create DataFrame from this year's breakdown
            year_df = pd.DataFrame([
                {"Tenant": tenant, "Income (Rp)": amount, "Raw": amount}
                for tenant, amount in raw_amounts.items()
            ])
            
            # Sort by income amount (descending)
            year_df = year_df.sort_values("Raw", ascending=False)
            
            # Calculate percentages using raw values
            year_df["% of Total"] = year_df["Raw"].apply(
                lambda x: f"{(x / total * 100):.1f}%" if total > 0 else "0.0%"
            )
            
            # Format currency after calculations
            year_df["Income (Rp)"] = year_df["Raw"].apply(lambda x: format_rupiah(x))
            
            # Remove the Raw column as it's no longer needed
            year_df = year_df.drop("Raw", axis=1)
            
            breakdown_dfs[year] = year_df
    
    return proj_df, breakdown_dfs

def main():
    st.title("Rental Asset Dashboard")

    # Load data if not already in session state
    if "df" not in st.session_state:
        try:
            df = pd.read_excel("data.xlsx")
            df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce")
            df["Lease End Date"] = pd.to_datetime(df["Lease End Date"], errors="coerce")
            if "Payment Scheme" not in df.columns:
                df["Payment Scheme"] = "Split Per Year"
            if "Custom Split (%)" not in df.columns:
                df["Custom Split (%)"] = ""
            if "Payment Status" not in df.columns:
                df["Payment Status"] = ""
            st.session_state["df"] = df
        except Exception as e:
            st.error(f"Error loading data: {e}")
            st.session_state["df"] = pd.DataFrame(columns=[
                "Tenant", "Start Date", "Lease End Date", "3-Month Reminder", 
                "Lease Duration (Years)", "Projected Income (Rp/year)",
                "Actual Income (Rp/year)", "Payment Scheme", "Custom Split (%)"
            ])

    st.header("📋 Existing Rentals")
    display_df = st.session_state["df"].copy()
    display_df["Projected Income (Rp/year)"] = display_df["Projected Income (Rp/year)"].apply(lambda x: format_rupiah(float(x)))
    display_df["Actual Income (Rp/year)"] = display_df["Actual Income (Rp/year)"].apply(lambda x: format_rupiah(float(x)))
    st.dataframe(display_df)

    st.header("➕ Add New Rental")
    with st.form("add_rental"):
        tenant = st.text_input("Tenant Name")
        start_date = st.date_input("Lease Start Date")
        lease_years = st.number_input("Lease Duration (Years)", min_value=1, step=1)
        rent = st.number_input("Projected Income (Rp/year)", min_value=0.0, step=1.0)
        actual_income = st.number_input("Actual Income (Rp/year)", min_value=0.0, step=1.0)
        payment_scheme = st.selectbox("Payment Scheme", ["Split Per Year", "Full Lease Upfront", "Custom Split"])
        custom_split = ""
        if payment_scheme == "Custom Split":
            custom_split = st.text_input("Custom Split (%) (e.g., 50/50 or 25/25/50)")
        submitted = st.form_submit_button("Add Rental")

        if submitted:
            end_date = calculate_lease_end(start_date, lease_years)
            reminder = "Reminder: Lease Ending Soon" if (end_date - datetime.now().date()) <= timedelta(days=90) else ""
            new_row = pd.DataFrame([{
                "Tenant": tenant,
                "Start Date": pd.to_datetime(start_date),
                "Lease End Date": pd.to_datetime(end_date),
                "3-Month Reminder": reminder,
                "Lease Duration (Years)": lease_years,
                "Projected Income (Rp/year)": rent,
                "Actual Income (Rp/year)": actual_income,
                "Payment Scheme": payment_scheme,
                "Custom Split (%)": custom_split
            }])
            st.session_state["df"] = pd.concat([st.session_state["df"], new_row], ignore_index=True)
            st.success("Tenant added.")

    st.header("✏️ Edit or Remove Tenant")
    tenants = st.session_state["df"]["Tenant"].unique().tolist()
    if tenants:
        selected_tenant = st.selectbox("Select Tenant", tenants)
        df = st.session_state["df"]
        tenant_rows = df[df["Tenant"] == selected_tenant]
        if not tenant_rows.empty:
            index = tenant_rows.index[0]
            row = tenant_rows.iloc[0]

            with st.form("edit_rental"):
                new_lease_years = st.number_input("Edit Lease Duration", value=int(row["Lease Duration (Years)"]), step=1)
                new_start_date = st.date_input("Edit Start Date", value=pd.to_datetime(row["Start Date"]))
                new_rent = st.number_input("Edit Projected Income", value=float(row["Projected Income (Rp/year)"]), step=1.0)
                new_actual = st.number_input("Edit Actual Income", value=float(row["Actual Income (Rp/year)"]), step=1.0)
                new_scheme = st.selectbox("Edit Payment Scheme", ["Split Per Year", "Full Lease Upfront", "Custom Split"], index=["Split Per Year", "Full Lease Upfront", "Custom Split"].index(row.get("Payment Scheme", "Split Per Year")))
                new_custom = ""
                if new_scheme == "Custom Split":
                    new_custom = st.text_input("Edit Custom Split (%)", value=str(row.get("Custom Split (%)", "")))
                submitted_edit = st.form_submit_button("Save Changes")

                if submitted_edit:
                    lease_end = calculate_lease_end(new_start_date, new_lease_years)
                    reminder = "Reminder: Lease Ending Soon" if (lease_end - datetime.now().date()) <= timedelta(days=90) else ""
                    df.at[index, "Start Date"] = pd.to_datetime(new_start_date)
                    df.at[index, "Lease End Date"] = pd.to_datetime(lease_end)
                    df.at[index, "Lease Duration (Years)"] = new_lease_years
                    df.at[index, "Projected Income (Rp/year)"] = new_rent
                    df.at[index, "Actual Income (Rp/year)"] = new_actual
                    df.at[index, "Payment Scheme"] = new_scheme
                    df.at[index, "Custom Split (%)"] = new_custom
                    df.at[index, "3-Month Reminder"] = reminder
                    st.success("Tenant updated.")

            if st.button("❌ Remove Tenant"):
                df.drop(index=index, inplace=True)
                df.reset_index(drop=True, inplace=True)
                st.success("Tenant removed.")
    else:
        st.info("No tenants to edit. Add a tenant first.")

    # Removed the "Projected vs Actual Income" section with line chart

    st.header("📊 Future Income Projection (5-Year Window)")
    
    years_before = 1  # Show 1 year before current year
    years_after = 3   # Show 3 years after current year
    
    # Use the new function that returns both summary and breakdown
    future_df, breakdown_dfs = project_income_with_breakdown(st.session_state["df"], years_before=years_before, years_after=years_after)
    
    # Apply styling to highlight current year
    current_year = datetime.now().year
    
    # Create a styled dataframe
    st.write(f"Displaying projections from {current_year-years_before} to {current_year+years_after}")
    
    # Display the dataframe with conditional formatting
    st.dataframe(
        future_df,
        column_config={
            "Year": st.column_config.NumberColumn(format="%d"),
            "Projected Total Income (Rp)": "Projected Income",
            "Note": "Status"
        },
        hide_index=True
    )
    
    # Calculate total for the displayed period
    try:
        total_sum = sum([
            float(x.replace("Rp ", "").replace(".", "")) 
            for x in future_df["Projected Total Income (Rp)"]
        ])
        st.metric("Total Projected Income (5-Year Window)", format_rupiah(total_sum))
    except:
        st.warning("Could not calculate total due to formatting issues.")
    
    # Display the breakdown for each year
    st.subheader("📊 Income Breakdown by Tenant (Per Year)")
    
    # Create tabs for each year
    years = sorted(breakdown_dfs.keys())
    tabs = st.tabs([str(year) for year in years])
    
    # Display breakdowns in tabs
    for i, year in enumerate(years):
        with tabs[i]:
            if not breakdown_dfs[year].empty:
                st.write(f"### Income Sources for {year}")
                st.dataframe(
                    breakdown_dfs[year],
                    column_config={
                        "Tenant": "Tenant Name",
                        "Income (Rp)": "Income",
                        "% of Total": "Percentage"
                    },
                    hide_index=True
                )
            else:
                st.info(f"No projected income for {year}")

    st.header("📈 Growth Projection: 7% Increase at Each Renewal")
    growth_records = []
    for _, row in st.session_state["df"].iterrows():
        try:
            tenant = row["Tenant"]
            start_year = pd.to_datetime(row["Start Date"]).year
            lease_years = int(row["Lease Duration (Years)"])
            base_rent = float(row["Projected Income (Rp/year)"])
            for i in range(5):  # project 5 cycles
                year = start_year + i * lease_years
                adjusted_rent = base_rent * ((1 + RENEWAL_RATE) ** i)
                growth_records.append({"Tenant": tenant, "Year": year, "Required Charge (Rp)": adjusted_rent})
        except:
            continue

    growth_df = pd.DataFrame(growth_records)
    if not growth_df.empty:
        tenant_names = growth_df["Tenant"].unique().tolist()
        selected_tenant = st.selectbox("Select Tenant to View Growth Chart", tenant_names, key="growth_tenant")
        tenant_growth = growth_df[growth_df["Tenant"] == selected_tenant]
        chart_data = tenant_growth[["Year", "Required Charge (Rp)"]].copy()
        chart_data["Required Charge (Rp)"] = chart_data["Required Charge (Rp)"].astype(float)
        st.line_chart(chart_data.set_index("Year"))

        st.subheader("📋 Yearly Charges Required to Meet 7% Growth")
        tenant_growth["Required Charge (Rp)"] = tenant_growth["Required Charge (Rp)"].apply(lambda x: format_rupiah(x))
        st.dataframe(tenant_growth)
    
    if st.button("💾 Save Data"):
        st.session_state["df"].to_excel("data.xlsx", index=False)
        if save_to_github():
            st.success("Data saved successfully to GitHub!")
        else:
            st.warning("Local file saved, but GitHub update failed.")

    st.header("🛠️ Troubleshoot & Fix Issues")

    if "troubleshoot_preview" not in st.session_state:
        st.session_state["troubleshoot_preview"] = None
        st.session_state["troubleshoot_report"] = []

    if st.button("Run Troubleshoot Check"):
        df = st.session_state["df"].copy()
        report = []
        actions = []

        required_cols = [
            "Tenant", "Start Date", "Lease End Date", "Lease Duration (Years)",
            "Projected Income (Rp/year)", "Actual Income (Rp/year)", "Payment Scheme", "Custom Split (%)"
        ]
        for col in required_cols:
            if col not in df.columns:
                actions.append(f"Add missing column: '{col}'")
                df[col] = "" if col in ["Tenant", "Payment Scheme", "Custom Split (%)"] else 0
                report.append(f"🛠️ Will add missing column: '{col}'")

        try:
            df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce")
            df["Lease End Date"] = pd.to_datetime(df["Lease End Date"], errors="coerce")
            report.append("✅ Will fix date format issues")
        except Exception as e:
            report.append(f"❌ Could not fix date formats: {e}")

        duplicates = df[df.duplicated(subset=["Tenant", "Start Date"], keep=False)]
        if not duplicates.empty:
            report.append(f"⚠️ {len(duplicates)} duplicate entries found")
        else:
            report.append("✅ No duplicate entries found")

        for col in required_cols:
            missing = df[col].isnull().sum()
            if missing > 0:
                df[col] = df[col].fillna("" if df[col].dtype == "object" else 0)
                report.append(f"🔄 Will fill {missing} missing values in '{col}'")

        empty_rows = df[df.isnull().all(axis=1)]
        if not empty_rows.empty:
            df.dropna(how="all", inplace=True)
            report.append(f"🧹 Will remove {len(empty_rows)} fully empty rows")

        st.session_state["troubleshoot_preview"] = df
        st.session_state["troubleshoot_report"] = report
        st.info("Preview generated. Review below and click 'Apply Fixes' to confirm.")

    if st.session_state["troubleshoot_preview"] is not None:
        for item in st.session_state["troubleshoot_report"]:
            st.write(item)

        if st.button("✅ Apply Fixes"):
            st.session_state["df"] = st.session_state["troubleshoot_preview"]
            st.session_state["df"].to_excel("data.xlsx", index=False)
            st.success("All fixes applied and saved.")
            st.session_state["troubleshoot_preview"] = None
            st.session_state["troubleshoot_report"] = []


if __name__ == "__main__":
    main()
