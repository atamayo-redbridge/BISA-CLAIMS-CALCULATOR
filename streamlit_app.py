import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime

# ---------------------- Helper Functions ----------------------

# Month mapping for filename detection
month_mapping = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# Cap both positive and negative values
def cap_value(value, cap_limit):
    return max(min(value, cap_limit), -cap_limit)

# Extract month and year from the filename
def extract_month_year(filename):
    filename = filename.lower()
    month_match = re.search(r'\b(' + '|'.join(month_mapping.keys()) + r')\b', filename)
    month = month_match.group() if month_match else None
    year_match = re.search(r'\b(20\d{2})\b', filename)
    year = int(year_match.group()) if year_match else None
    return month, year

# Assign fiscal quarter based on filename
def assign_quarter_based_on_filename(month_number):
    if month_number in [10, 11, 12]:
        return "Q1"
    elif month_number in [1, 2, 3]:
        return "Q2"
    elif month_number in [4, 5, 6]:
        return "Q3"
    elif month_number in [7, 8, 9]:
        return "Q4"

# Load previous report if uploaded
def load_existing_report(uploaded_report):
    existing_data = {}
    xls = pd.ExcelFile(uploaded_report)
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        existing_data[sheet_name] = df
    return existing_data

# Process claims and apply caps
def process_cumulative_quarters(existing_data, dataframes, covid_cap, total_cap_year1, trigger_cap_year2, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
    year2_cumulative_payouts = {}

    # Load previous cumulative data if available
    if existing_data:
        cumulative_data = pd.concat(existing_data.values(), ignore_index=True)

    total_quarters = len(dataframes)

    for i, (quarter, frames) in enumerate(dataframes.items()):
        if not frames:
            continue

        combined_df = pd.concat(frames, ignore_index=True)

        # Update status message
        status_text.text(f"🔄 Processing {quarter} ({i+1}/{total_quarters})...")

        # Extract the quarter number using regex
        quarter_number = int(re.search(r'Q(\d+)', quarter).group(1))

        # Detect the correct diagnostic column
        diagnostic_col = None
        for col in ["DIAGNOSTICO", "DIAGNOSTICOS"]:
            if col in combined_df.columns:
                diagnostic_col = col
                break

        # For Q1-Q4 (Year 1)
        if quarter_number <= 4:
            if diagnostic_col:
                combined_df["COVID_AMOUNT"] = np.where(
                    combined_df[diagnostic_col].astype(str).str.contains("COVID", case=False, na=False),
                    combined_df["MONTO"],
                    0
                )
            else:
                combined_df["COVID_AMOUNT"] = 0  # No COVID claims detected if column is missing

            combined_df["GENERAL_AMOUNT"] = np.where(
                combined_df["COVID_AMOUNT"] == 0, combined_df["MONTO"], 0
            )

            grouped = combined_df.groupby("COD_ASEGURADO").agg({
                "COVID_AMOUNT": "sum",
                "GENERAL_AMOUNT": "sum"
            }).reset_index()

            if cumulative_data.empty:
                cumulative_data = grouped
            else:
                cumulative_data = cumulative_data.merge(
                    grouped, on="COD_ASEGURADO", how="outer", suffixes=('_prev', '_new')
                ).fillna(0)
                cumulative_data["COVID_AMOUNT"] = cumulative_data["COVID_AMOUNT_prev"] + cumulative_data["COVID_AMOUNT_new"]
                cumulative_data["GENERAL_AMOUNT"] = cumulative_data["GENERAL_AMOUNT_prev"] + cumulative_data["GENERAL_AMOUNT_new"]
                cumulative_data = cumulative_data[["COD_ASEGURADO", "COVID_AMOUNT", "GENERAL_AMOUNT"]]

            cumulative_data["COVID_AMOUNT"] = cumulative_data["COVID_AMOUNT"].apply(lambda x: cap_value(x, covid_cap))
            cumulative_data["TOTAL_AMOUNT"] = cumulative_data["COVID_AMOUNT"] + cumulative_data["GENERAL_AMOUNT"]
            cumulative_data["TOTAL_AMOUNT"] = cumulative_data["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year1))
            cumulative_data["FINAL"] = cumulative_data["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year1))

        # For Q5 and onward (Year 2)
        else:
            if quarter == "Q5":
                cumulative_data = pd.DataFrame()

            grouped = combined_df.groupby("COD_ASEGURADO").agg({
                "MONTO": "sum"
            }).reset_index().rename(columns={"MONTO": "TOTAL_AMOUNT"})

            if cumulative_data.empty:
                cumulative_data = grouped
            else:
                cumulative_data = cumulative_data.merge(
                    grouped, on="COD_ASEGURADO", how="outer", suffixes=('_prev', '_new')
                ).fillna(0)
                cumulative_data["TOTAL_AMOUNT"] = cumulative_data["TOTAL_AMOUNT_prev"] + cumulative_data["TOTAL_AMOUNT_new"]
                cumulative_data = cumulative_data[["COD_ASEGURADO", "TOTAL_AMOUNT"]]

            payout_list = []
            for idx, row in cumulative_data.iterrows():
                cod = row["COD_ASEGURADO"]
                total_claim = row["TOTAL_AMOUNT"]
                cumulative_payout = year2_cumulative_payouts.get(cod, 0)

                if abs(total_claim) > trigger_cap_year2:
                    payout = cap_value(cumulative_payout + total_claim, total_cap_year2)
                    year2_cumulative_payouts[cod] = payout
                else:
                    payout = 0  # No payout if below threshold

                payout_list.append(payout)

            cumulative_data["FINAL"] = payout_list

        quarterly_results[quarter] = cumulative_data.copy()

        # Update progress bar
        progress_bar.progress((i + 1) / total_quarters)

    return quarterly_results

# ---------------------- Streamlit UI ----------------------

st.title("📊 Insurance Claims Processing App with Cumulative Report Support")

# Upload existing report (optional)
st.header("1️⃣ Upload Existing Cumulative Report (Optional)")
uploaded_existing_report = st.file_uploader("Upload Existing Cumulative Report (Excel):", type=["xlsx"])

# Upload new monthly files
st.header("2️⃣ Upload New Monthly Claim Files")
uploaded_files = st.file_uploader("Upload New Monthly Claim Files:", type=["xlsx"], accept_multiple_files=True)

if st.button("🚀 Process Files"):
    if uploaded_files:
        progress_bar = st.progress(0)
        status_text = st.empty()
        quarterly_data = {}

        # Load existing report if available
        existing_data = {}
        if uploaded_existing_report:
            existing_data = load_existing_report(uploaded_existing_report)
            st.success("✅ Existing cumulative report loaded successfully.")

        # Process uploaded files
        total_files = len(uploaded_files)
        for i, file in enumerate(uploaded_files):
            file_name = file.name
            month_name, year = extract_month_year(file_name)
            if not month_name or not year:
                continue

            month_number = month_mapping[month_name]
            quarter = assign_quarter_based_on_filename(month_number)
            quarter_key = f"{quarter}-{year}"

            if quarter_key not in quarterly_data:
                quarterly_data[quarter_key] = []

            xls = pd.ExcelFile(file)
            for sheet in xls.sheet_names:
                df = pd.read_excel(file, sheet_name=sheet)
                if all(col in df.columns for col in ["COD_ASEGURADO", "FECHA_RECLAMO", "MONTO"]) and any(col in df.columns for col in ["DIAGNOSTICO", "DIAGNOSTICOS"]):
                    df.columns = df.columns.str.upper()
                    df["FECHA_RECLAMO"] = pd.to_datetime(df["FECHA_RECLAMO"], errors="coerce")
                    df = df[df["FECHA_RECLAMO"] >= pd.Timestamp("2023-10-01")]
                    df["QUARTER"] = quarter_key
                    quarterly_data[quarter_key].append(df)
                    break

            # Update progress
            status_text.text(f"📂 Processing file {i + 1} of {total_files}: {file_name}")
            progress_bar.progress((i + 1) / total_files)

        # Process quarters with cumulative data
        final_results = process_cumulative_quarters(
            existing_data,
            quarterly_data,
            covid_cap=2000,
            total_cap_year1=20000,
            trigger_cap_year2=40000,
            total_cap_year2=2000000,
            status_text=status_text,
            progress_bar=progress_bar
        )

        # Saving results
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"Updated_Processed_Claims_Report_{timestamp}.xlsx"
        with pd.ExcelWriter(output_file) as writer:
            for quarter, df in final_results.items():
                if not df.empty:
                    df.to_excel(writer, sheet_name=quarter, index=False)

        status_text.text("✅ All files and quarters processed successfully!")
        st.success("🎉 Report processed successfully with cumulative data!")
        st.download_button("📥 Download Updated Report", data=open(output_file, "rb"), file_name=output_file)

    else:
        st.error("❌ Please upload valid Excel files to process.")
