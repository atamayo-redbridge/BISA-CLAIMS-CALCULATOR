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
    try:
        existing_data = {}
        xls = pd.ExcelFile(uploaded_report)
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            existing_data[sheet_name] = df
        return existing_data
    except Exception as e:
        st.error(f"Error loading existing report: {e}")
        return {}

# ✅ **Fixed: Sort function now returns (year, month_number, file)**
def sort_uploaded_files(uploaded_files):
    files_with_dates = []
    for file in uploaded_files:
        month_name, year = extract_month_year(file.name)
        if month_name and year:
            month_number = month_mapping[month_name]
            files_with_dates.append((year, month_number, file))
    
    # ✅ **Sort correctly and return (year, month_number, file) tuples**
    return sorted(files_with_dates, key=lambda x: (x[0], x[1]))

# Dynamically detect the MONTO column
def detect_monto_column(df):
    for col in df.columns:
        if "MONTO" in col.upper():
            return col
    return None

# Dynamically detect the NOMBRE_ASEGURADO column
def detect_nombre_column(df):
    for col in df.columns:
        if "NOMBREASEGURADO" in col.upper() or "NOMBRESASEGURADO" in col.upper() or "NOMBRE_ASEGURADO" in col.upper():
            return col
    return None

# ✅ **Fix: Ensure sorted_files structure is handled correctly**
def process_cumulative_quarters(existing_data, sorted_files, covid_cap, total_cap_year1, trigger_cap_year2, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
    skipped_files = []
    cumulative_final_sum = 0  

    # Define date ranges
    year1_start, year1_end = pd.Timestamp("2023-10-01"), pd.Timestamp("2024-09-30")
    year2_start, year2_end = pd.Timestamp("2024-10-01"), pd.Timestamp("2025-09-30")

    if existing_data and len(existing_data) > 0:
        cumulative_data = pd.concat(existing_data.values(), ignore_index=True)

    total_files = len(sorted_files)
    quarter_number = 1
    month_counter = 0

    # ✅ **Ensure sorted_files contains tuples before iterating**
    if not sorted_files or not isinstance(sorted_files[0], tuple):
        st.error("❌ ERROR: File sorting failed. Please check uploaded file names.")
        return {}, []

    for i, (year, month_number, file) in enumerate(sorted_files):  # ✅ Fixed unpacking issue
        if month_counter % 3 == 0:
            quarter_key = f"Q{quarter_number}"
            quarterly_results[quarter_key] = None  # Placeholder
            quarter_number += 1

        df = pd.read_excel(file)
        status_text.text(f"🔄 Processing {file.name} ({i+1}/{total_files})...")

        # Check for required columns
        required_columns = ["COD_ASEGURADO", "FECHA_RECLAMO"]
        if not all(col in df.columns for col in required_columns):
            skipped_files.append(file.name)
            continue

        # Detect MONTO and NOMBRE_ASEGURADO columns
        monto_col = detect_monto_column(df)
        nombre_col = detect_nombre_column(df)
        if not monto_col:
            skipped_files.append(file.name)
            continue

        if nombre_col:
            df.rename(columns={nombre_col: "NOMBRE_ASEGURADO"}, inplace=True)
        else:
            df["NOMBRE_ASEGURADO"] = "No Name Provided"

        df["FECHA_RECLAMO"] = pd.to_datetime(df["FECHA_RECLAMO"], errors="coerce")

        # Filter claims within valid date range
        df = df[(df["FECHA_RECLAMO"] >= year1_start) & (df["FECHA_RECLAMO"] <= year2_end)]

        # Apply Year 1 or Year 2 logic
        df["YEAR_TYPE"] = np.where(df["FECHA_RECLAMO"] < year2_start, "Year1", "Year2")

        df["TOTAL_AMOUNT"] = df[monto_col]
        
        # Apply caps and correct FINAL calculation
        df["FINAL"] = np.where(
            df["YEAR_TYPE"] == "Year1",
            cap_value(df["TOTAL_AMOUNT"] / 2, total_cap_year1),  # Year 1: Divide by 2
            cap_value(df["TOTAL_AMOUNT"], total_cap_year2)  # Year 2: No division
        )

        # Group by COD_ASEGURADO and sum
        grouped = df.groupby(["COD_ASEGURADO", "NOMBRE_ASEGURADO"]).agg({
            "TOTAL_AMOUNT": "sum",
            "FINAL": "sum"
        }).reset_index()

        quarterly_results[quarter_key] = grouped.copy()

        month_counter += 1
        progress_bar.progress((i + 1) / total_files)

    progress_bar.progress(1.0)  # Ensure it reaches 100%
    return quarterly_results, skipped_files

# ---------------------- Streamlit UI ----------------------

st.title("📊 Insurance Claims Processor")

# 📥 Upload Previous Report
st.header("📥 Upload Previous Report (Optional)")
uploaded_existing_report = st.file_uploader("Upload an existing cumulative report:", type=["xlsx"])

# 📂 Upload New Monthly Files
st.header("📂 Upload New Monthly Claim Files")
uploaded_files = st.file_uploader("Upload new claim files:", type=["xlsx"], accept_multiple_files=True)

if st.button("🚀 Process Files"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    if not uploaded_files:
        st.error("❌ Please upload at least one file!")
    else:
        sorted_files = sort_uploaded_files(uploaded_files)

        existing_data = {}
        if uploaded_existing_report:
            existing_data = load_existing_report(uploaded_existing_report)

        final_results, skipped_files = process_cumulative_quarters(
            existing_data, sorted_files, 2000, 20000, 40000, 2000000, status_text, progress_bar
        )

        st.success("✅ Processing complete! Download your updated report below.")

        if skipped_files:
            st.warning("⚠️ Some files were skipped due to missing columns:")
            for file in skipped_files:
                st.write(f"- {file}")
