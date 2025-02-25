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

# Load previous report if uploaded
def load_existing_report(uploaded_report):
    existing_data = {}
    xls = pd.ExcelFile(uploaded_report)
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        existing_data[sheet_name] = df
    return existing_data

# Sort files by year and month
def sort_uploaded_files(uploaded_files):
    files_with_dates = []
    for file in uploaded_files:
        month_name, year = extract_month_year(file.name)
        if month_name and year:
            month_number = month_mapping[month_name]
            files_with_dates.append((year, month_number, file))
    sorted_files = sorted(files_with_dates, key=lambda x: (x[0], x[1]))
    return [file[2] for file in sorted_files]

# Dynamically detect the MONTO column
def detect_monto_column(df):
    for col in df.columns:
        if "MONTO" in col.upper():
            return col
    return None

# Process claims and apply caps
def process_cumulative_quarters(existing_data, sorted_files, covid_cap, total_cap_year1, trigger_cap_year2, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
    year2_cumulative_payouts = {}
    skipped_files = []

    if existing_data:
        cumulative_data = pd.concat(existing_data.values(), ignore_index=True)

    total_files = len(sorted_files)
    quarter_number = 1
    month_counter = 0

    for i, (year, month_number, file) in enumerate(sorted_files):
        if month_counter % 3 == 0:
            quarter_key = f"Q{quarter_number}"
            quarterly_results[quarter_key] = []
            quarter_number += 1

        df = pd.read_excel(file)
        status_text.text(f"🔄 Processing {file.name} ({i+1}/{total_files})...")

        # Check for required columns
        required_columns = ["COD_ASEGURADO", "FECHA_RECLAMO"]
        if not all(col in df.columns for col in required_columns):
            skipped_files.append(file.name)
            continue

        # Detect MONTO column
        monto_col = detect_monto_column(df)
        if not monto_col:
            skipped_files.append(file.name)
            continue

        # Detect the correct diagnostic column
        diagnostic_col = None
        for col in ["DIAGNOSTICO", "DIAGNOSTICOS"]:
            if col in df.columns:
                diagnostic_col = col
                break

        # Process Year 1 (Q1-Q4)
        if quarter_number <= 5:
            if diagnostic_col:
                df["COVID_AMOUNT"] = np.where(
                    df[diagnostic_col].astype(str).str.contains("COVID", case=False, na=False),
                    df[monto_col],
                    0
                )
            else:
                df["COVID_AMOUNT"] = 0

            df["GENERAL_AMOUNT"] = np.where(
                df["COVID_AMOUNT"] == 0, df[monto_col], 0
            )

            grouped = df.groupby("COD_ASEGURADO").agg({
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

        # Process Year 2 (Q5 onwards)
        else:
            if quarter_number == 5:
                cumulative_data = pd.DataFrame()

            grouped = df.groupby("COD_ASEGURADO").agg({
                monto_col: "sum"
            }).reset_index().rename(columns={monto_col: "TOTAL_AMOUNT"})

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
                    payout = 0

                payout_list.append(payout)

            cumulative_data["FINAL"] = payout_list

        quarterly_results[quarter_key] = cumulative_data.copy()
        month_counter += 1
        progress_bar.progress((i + 1) / total_files)

    return quarterly_results, skipped_files

# ---------------------- Streamlit UI ----------------------

st.title("📊 Insurance Claims Processor with Dynamic Column Detection & Chronological Order")

# Upload existing report (optional)
st.header("1️⃣ Upload Existing Cumulative Report (Optional)")
uploaded_existing_report = st.file_uploader("Upload Existing Cumulative Report (Excel):", type=["xlsx"])

# Upload new monthly files
st.header("2️⃣ Upload New Monthly Claim Files")
uploaded_files = st.file_uploader("Upload Monthly Claim Files:", type=["xlsx"], accept_multiple_files=True)

if st.button("🚀 Process Files"):
    if uploaded_files:
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Load existing report if available
        existing_data = {}
        if uploaded_existing_report:
            existing_data = load_existing_report(uploaded_existing_report)
            st.success("✅ Existing cumulative report loaded successfully.")

        # Sort uploaded files by date
        sorted_files_with_dates = sort_uploaded_files(uploaded_files)
        sorted_files = [(extract_month_year(file.name)[1], month_mapping[extract_month_year(file.name)[0]], file) for file in sorted_files_with_dates]

        # Process quarters with sorted data
        final_results, skipped_files = process_cumulative_quarters(
            existing_data,
            sorted_files,
            covid_cap=2000,
            total_cap_year1=20000,
            trigger_cap_year2=40000,
            total_cap_year2=2000000,
            status_text=status_text,
            progress_bar=progress_bar
        )

        # Saving results
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"Chronologically_Processed_Claims_Report_{timestamp}.xlsx"
        with pd.ExcelWriter(output_file) as writer:
            for quarter, df in final_results.items():
                if not df.empty:
                    df.to_excel(writer, sheet_name=quarter, index=False)

        status_text.text("✅ All files and quarters processed successfully!")
        st.success("🎉 Report processed in chronological order!")

        # Show skipped files
        if skipped_files:
            st.warning("⚠️ Some files were skipped due to missing required columns:")
            for file in skipped_files:
                st.write(f"- {file}")

        st.download_button("📥 Download Updated Report", data=open(output_file, "rb"), file_name=output_file)

    else:
        st.error("❌ Please upload valid Excel files to process.")
