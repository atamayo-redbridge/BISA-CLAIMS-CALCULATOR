import streamlit as st
import pandas as pd
import numpy as np
import re
from io import BytesIO

# ---------------------- Helper Functions ----------------------

month_mapping = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# Cap values at a limit
def cap_value(value, cap_limit):
    return min(value, cap_limit)

# Extract month and year from filename
def extract_month_year(filename):
    filename = filename.lower()
    month_match = re.search(r'\b(' + '|'.join(month_mapping.keys()) + r')\b', filename)
    month = month_match.group() if month_match else None
    year_match = re.search(r'\b(20\d{2})\b', filename)
    year = int(year_match.group()) if year_match else None
    return month, year

# Sort files by year and month
def sort_uploaded_files(uploaded_files):
    files_with_dates = []
    for file in uploaded_files:
        month_name, year = extract_month_year(file.name)
        if month_name and year:
            month_number = month_mapping[month_name]
            files_with_dates.append((year, month_number, file))
    return sorted(files_with_dates, key=lambda x: (x[0], x[1]))

# Detect dynamic column names
def detect_column(df, possible_names):
    for col in df.columns:
        if any(name in col.upper() for name in possible_names):
            return col
    return None

# ---------------------- Processing Claims ----------------------

def process_claims(sorted_files, total_cap_year1, total_cap_year2, status_text, progress_bar):
    cumulative_data = pd.DataFrame()
    quarterly_results = {}
    skipped_files = []
    total_files = len(sorted_files)
    quarter_number = 1
    month_counter = 0

    for i, (year, month_number, file) in enumerate(sorted_files):
        if month_counter % 3 == 0:
            quarter_key = f"Q{quarter_number}"
            if quarter_key not in quarterly_results:
                quarterly_results[quarter_key] = pd.DataFrame()
            quarter_number += 1

        df = pd.read_excel(file)
        status_text.text(f"🔄 Processing {file.name} ({i+1}/{total_files})...")

        required_columns = ["COD_ASEGURADO", "FECHA_RECLAMO"]
        if not all(col in df.columns for col in required_columns):
            skipped_files.append(file.name)
            continue

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

        # Define Year 1 and Year 2 date ranges (KEEP FECHA_RECLAMO AS STRING)
        year1_start = "2023-10-01"
        year1_end = "2024-09-30"
        year2_start = "2024-10-01"

        # Ensure diagnostic column exists
        if diagnostic_col:
            covid_condition = df[diagnostic_col].astype(str).str.contains("COVID", case=False, na=False)
        else:
            covid_condition = False

        # Year classification based on date range **WITHOUT converting to datetime**
        df["YEAR_TYPE"] = np.where(
            (df["FECHA_RECLAMO"] >= year1_start) & (df["FECHA_RECLAMO"] <= year1_end), "Year1", "Year2"
        )

        # Apply Year 1 logic
        df["TOTAL_AMOUNT"] = df[monto_col]
        df["FINAL"] = np.where(
            df["YEAR_TYPE"] == "Year1",
            df["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year1)),
            df["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, total_cap_year2))
        )

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        grouped = df.groupby(["COD_ASEGURADO", "NOMBRE_ASEGURADO"], as_index=False)[numeric_cols].sum()
        grouped.fillna(0, inplace=True)

        if quarter_key in quarterly_results:
            quarterly_results[quarter_key] = pd.concat([quarterly_results[quarter_key], grouped], ignore_index=True).fillna(0)
        else:
            quarterly_results[quarter_key] = grouped.copy().fillna(0)

        month_counter += 1
        progress_bar.progress((i + 1) / total_files)

    return quarterly_results, skipped_files

# ---------------------- Streamlit UI ----------------------

st.title("📊 Insurance Claims Processor")

st.header("1️⃣ Upload Monthly Claim Files")
uploaded_files = st.file_uploader("Upload Monthly Claim Files:", type=["xlsx"], accept_multiple_files=True)

if st.button("🚀 Process Files"):
    if uploaded_files:
        progress_bar = st.progress(0)
        status_text = st.empty()

        sorted_files = sort_uploaded_files(uploaded_files)
        final_results, skipped_files = process_claims(sorted_files, 20000, 2000000, status_text, progress_bar)

        output_buffer = BytesIO()
        with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
            for quarter, df in final_results.items():
                df.to_excel(writer, sheet_name=quarter, index=False)

        output_buffer.seek(0)
        st.download_button("📥 Download Processed Report", data=output_buffer, file_name="Processed_Claims_Report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.success("✅ Processing complete!")
    else:
        st.error("❌ Please upload valid Excel files.")

