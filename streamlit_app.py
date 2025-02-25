import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import datetime

# ------------------- Helper Functions -------------------

# Dictionary to map month names for detection
month_mapping = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# Detect columns dynamically
def detect_columns(df):
    variations = {
        "COD_ASEGURADO": ["COD_ASEGURADO"],
        "NOMBRE_ASEGURADO": ["NOMBRES ASEGURADO", "NOMBRE ASEGURADO", "NOMBRESASEURADO"],
        "FECHA_RECLAMO": ["FECHA_RECLAMO"],
        "MONTO": ["MONTO"],
        "DIAGNOSTICO": ["DIAGNOSTICOS", "DIAGNOSTICO"]
    }
    detected = {}
    for standard, options in variations.items():
        for option in options:
            if option in df.columns:
                detected[standard] = option
                break
    return detected

# Cap values according to the limit
def cap_value(value, cap_limit):
    return max(min(value, cap_limit), -cap_limit)

# Extract month and year from filename using regex to avoid false matches
def extract_month_year(filename):
    filename = filename.lower()
    month_match = re.search(r'\b(' + '|'.join(month_mapping.keys()) + r')\b', filename)
    month = month_match.group() if month_match else None
    year_match = re.search(r'\b(20\d{2})\b', filename)
    year = int(year_match.group()) if year_match else None
    return month, year

# Detailed validation with debugging information
def validate_and_debug_claims(df, year_range, detected_columns, sheet_name, file_name):
    total_claims = len(df)
    missing_cod_asegurado = df[detected_columns["COD_ASEGURADO"]].isna().sum()
    missing_monto = df[detected_columns["MONTO"]].isna().sum()

    # Convert FECHA_RECLAMO to datetime
    df["FECHA_RECLAMO"] = pd.to_datetime(df[detected_columns["FECHA_RECLAMO"]], errors="coerce")
    invalid_dates = df["FECHA_RECLAMO"].isna().sum()

    # Date range filtering
    valid_mask = (
        (df["FECHA_RECLAMO"] >= year_range[0]) &
        (df["FECHA_RECLAMO"] <= year_range[1])
    )
    valid_claims = df[valid_mask]
    excluded_due_to_date = (~valid_mask).sum()

    # Logging detailed information
    st.write(f"📄 **File:** {file_name} → **Sheet:** {sheet_name}")
    st.write(f"🔍 Total Claims: {total_claims}")
    st.write(f"❌ Missing COD_ASEGURADO: {missing_cod_asegurado}")
    st.write(f"❌ Missing MONTO: {missing_monto}")
    st.write(f"❌ Invalid FECHA_RECLAMO: {invalid_dates}")
    st.write(f"❌ Excluded due to invalid dates: {excluded_due_to_date}")
    st.write(f"✅ Valid Claims After Filtering: {len(valid_claims)}\n")

    return valid_claims

# Load and validate claims (automatically detect correct sheet)
def load_and_validate_claims(file, year_range):
    try:
        xls = pd.ExcelFile(file)
        validated_claims = pd.DataFrame()

        max_valid_claims = 0  # Track the sheet with the highest valid claims

        for sheet in xls.sheet_names:
            df = pd.read_excel(file, sheet_name=sheet)
            detected_columns = detect_columns(df)

            if all(col in detected_columns for col in ["COD_ASEGURADO", "NOMBRE_ASEGURADO", "FECHA_RECLAMO", "MONTO"]):
                valid_claims = validate_and_debug_claims(df, year_range, detected_columns, sheet, file.name)

                # Use the sheet with the most valid claims
                if len(valid_claims) > max_valid_claims:
                    validated_claims = valid_claims
                    max_valid_claims = len(valid_claims)

        return validated_claims
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return pd.DataFrame()

# ------------------- Streamlit UI -------------------

st.title("📊 Insurance Claims Debugging Tool (Detailed Error Logging)")

# Upload existing report
st.header("1️⃣ Upload Existing Report (Optional)")
existing_report = st.file_uploader("Upload an existing report (if available):", type=["xlsx"])

# Upload new monthly files
st.header("2️⃣ Upload New Monthly Files")
uploaded_files = st.file_uploader("Upload new monthly files:", type=["xlsx"], accept_multiple_files=True)

# Process and Generate Report
if st.button("🔄 Process Files"):
    if uploaded_files:
        year1_range = (pd.Timestamp("2023-10-01"), pd.Timestamp("2024-09-30"))
        year2_range = (pd.Timestamp("2024-10-01"), pd.Timestamp("2025-09-30"))

        # Load and validate claims for each file
        for file in uploaded_files:
            month, year = extract_month_year(file.name)
            year_range = year1_range if year == year1_range[0].year else year2_range
            validated_claims = load_and_validate_claims(file, year_range)

            if validated_claims.empty:
                st.error(f"❌ No valid claims found in file: {file.name}")
            else:
                st.success(f"✅ Valid claims successfully processed for file: {file.name}")
    else:
        st.error("❌ Please upload at least one monthly file.")
