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

# Sort files by year and month
def sort_uploaded_files(uploaded_files):
    files_with_dates = []
    for file in uploaded_files:
        month_name, year = extract_month_year(file.name)
        if month_name and year:
            month_number = month_mapping[month_name]
            files_with_dates.append((year, month_number, file))
    return sorted(files_with_dates, key=lambda x: (x[0], x[1]))

# Process claims and apply caps
def process_cumulative_quarters(existing_data, sorted_files, covid_cap, total_cap_year1, trigger_cap_year2, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
    skipped_files = []

    total_files = len(sorted_files)
    quarter_number = 1
    month_counter = 0

    for i, (year, month_number, file) in enumerate(sorted_files):
        if month_counter % 3 == 0:
            quarter_key = f"Q{quarter_number}"
            quarterly_results[quarter_key] = None
            quarter_number += 1

        df = pd.read_excel(file)
        status_text.text(f"🔄 Processing {file.name} ({i+1}/{total_files})...")

        # Ensure required columns exist
        required_columns = ["COD_ASEGURADO", "FECHA_RECLAMO"]
        if not all(col in df.columns for col in required_columns):
            skipped_files.append(file.name)
            continue

        # Detect MONTO column
        monto_col = [col for col in df.columns if "MONTO" in col.upper()]
        if not monto_col:
            skipped_files.append(file.name)
            continue
        monto_col = monto_col[0]  

        df["FECHA_RECLAMO"] = pd.to_datetime(df["FECHA_RECLAMO"], errors="coerce")

        df["TOTAL_AMOUNT"] = df[monto_col]
        
        df["FINAL"] = np.where(
            df["FECHA_RECLAMO"] < pd.Timestamp("2024-10-01"),
            df["TOTAL_AMOUNT"].div(2).apply(lambda x: cap_value(x, total_cap_year1)),
            df["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year2))
        )

        # Aggregate data
        grouped = df.groupby(["COD_ASEGURADO"]).agg({"TOTAL_AMOUNT": "sum", "FINAL": "sum"}).reset_index()
        quarterly_results[quarter_key] = grouped.copy()

        month_counter += 1
        progress_bar.progress((i + 1) / total_files)

    progress_bar.progress(1.0)  
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

        # ✅ Save results and provide download button
        output_filename = f"Processed_Claims_Report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        output_path = os.path.join("outputs", output_filename)

        if not os.path.exists("outputs"):
            os.makedirs("outputs")

        with pd.ExcelWriter(output_path) as writer:
            for quarter, df in final_results.items():
                if df is not None and not df.empty:
                    df.to_excel(writer, sheet_name=quarter, index=False)

        with open(output_path, "rb") as f:
            excel_data = f.read()
        
        st.success("✅ Processing complete! Download your report below.")
        
        st.download_button(
            label="📥 Download Processed Report",
            data=excel_data,
            file_name=output_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        if skipped_files:
            st.warning("⚠️ Some files were skipped due to missing columns:")
            for file in skipped_files:
                st.write(f"- {file}")
