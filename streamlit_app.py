import streamlit as st
import pandas as pd
import numpy as np
import re
import os
from datetime import datetime
from io import BytesIO

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
    return sorted(files_with_dates, key=lambda x: (x[0], x[1]))

# Dynamically detect required columns
def detect_column(df, possible_names):
    for col in df.columns:
        if any(name in col.upper() for name in possible_names):
            return col
    return None

# ---------------------- Processing Claims ----------------------

def process_cumulative_quarters(existing_data, sorted_files, covid_cap, total_cap_year1, trigger_cap_year2, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
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

        # Detect necessary columns
        monto_col = detect_column(df, ["MONTO"])
        name_col = detect_column(df, ["NOMBREASEGURADO", "NOMBRE_ASEGURADO", "NOMBRESASEGURADO"])
        diagnostic_col = detect_column(df, ["DIAGNOSTICO", "DIAGNOSTICOS"])

        if not monto_col:
            skipped_files.append(file.name)
            continue

        if not name_col:
            df["NOMBRE_ASEGURADO"] = "No Name Provided"
        else:
            df.rename(columns={name_col: "NOMBRE_ASEGURADO"}, inplace=True)

        # Convert claim date to datetime
        df["FECHA_RECLAMO"] = pd.to_datetime(df["FECHA_RECLAMO"], errors="coerce")

        # Define Year 1 and Year 2 date ranges
        year1_start = pd.Timestamp("2023-10-01")
        year1_end = pd.Timestamp("2024-09-30")
        year2_start = pd.Timestamp("2024-10-01")

        # Identify COVID-related claims
        if diagnostic_col:
            diagnostic_series = df[diagnostic_col].astype(str).str.contains("COVID", case=False, na=False)
        else:
            diagnostic_series = pd.Series(False, index=df.index)

        # Apply logic based on claim date
        df["YEAR_TYPE"] = np.where(df["FECHA_RECLAMO"] < year2_start, "Year1", "Year2")

        # Apply Year 1 logic for all claims from Oct 1, 2023 – Sept 30, 2024
        df["COVID_AMOUNT"] = np.where((df["YEAR_TYPE"] == "Year1") & diagnostic_series, df[monto_col], 0)
        df["GENERAL_AMOUNT"] = np.where((df["YEAR_TYPE"] == "Year1") & (df["COVID_AMOUNT"] == 0), df[monto_col], 0)

        # Apply Year 2 logic for claims from Oct 1, 2024, onwards
        df.loc[df["YEAR_TYPE"] == "Year2", "COVID_AMOUNT"] = 0
        df.loc[df["YEAR_TYPE"] == "Year2", "GENERAL_AMOUNT"] = df[monto_col]

        # Set TOTAL_AMOUNT
        df["TOTAL_AMOUNT"] = df[monto_col]

        # Apply caps
        df["FINAL"] = np.where(
            df["YEAR_TYPE"] == "Year1",
            df["TOTAL_AMOUNT"].div(2).apply(lambda x: cap_value(x, total_cap_year1)),
            df["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year2))
        )

        # Aggregate data
        grouped = df.groupby(["COD_ASEGURADO", "NOMBRE_ASEGURADO"]).agg({
            "COVID_AMOUNT": "sum",
            "GENERAL_AMOUNT": "sum",
            "TOTAL_AMOUNT": "sum",
            "FINAL": "sum"
        }).reset_index()

        quarterly_results[quarter_key] = grouped.copy()
        month_counter += 1
        progress_bar.progress((i + 1) / total_files)

    return quarterly_results, skipped_files

# ---------------------- Streamlit UI ----------------------

st.title("📊 Insurance Claims Processor (With Download Option)")

st.header("1️⃣ Upload Existing Cumulative Report (Optional)")
uploaded_existing_report = st.file_uploader("Upload Existing Report (Excel):", type=["xlsx"])

st.header("2️⃣ Upload New Monthly Claim Files")
uploaded_files = st.file_uploader("Upload Monthly Claim Files:", type=["xlsx"], accept_multiple_files=True)

if st.button("🚀 Process Files"):
    if uploaded_files:
        progress_bar = st.progress(0)
        status_text = st.empty()

        existing_data = {}
        if uploaded_existing_report:
            existing_data = load_existing_report(uploaded_existing_report)

        sorted_files = sort_uploaded_files(uploaded_files)

        final_results, skipped_files = process_cumulative_quarters(existing_data, sorted_files, 2000, 20000, 40000, 2000000, status_text, progress_bar)

        # Save results to an Excel file
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"Processed_Claims_Report_{timestamp}.xlsx"
        output_buffer = BytesIO()

        with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
            for quarter, df in final_results.items():
                if not df.empty:
                    df.to_excel(writer, sheet_name=quarter, index=False)

        output_buffer.seek(0)

        st.success("✅ Processing complete! Download your report below.")
        st.download_button(
            label="📥 Download Processed Report",
            data=output_buffer,
            file_name=output_file,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.error("❌ Please upload valid Excel files to process.")
