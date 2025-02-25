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

# Assign quarters based on the fiscal year starting in October
def assign_quarter(month):
    if month in [10, 11, 12]:  # October to December
        return "Q1"
    elif month in [1, 2, 3]:   # January to March
        return "Q2"
    elif month in [4, 5, 6]:   # April to June
        return "Q3"
    elif month in [7, 8, 9]:   # July to September
        return "Q4"

# Extract month and year from filename using regex
def extract_month_year(filename):
    filename = filename.lower()
    month_match = re.search(r'\b(' + '|'.join(month_mapping.keys()) + r')\b', filename)
    month = month_match.group() if month_match else None
    year_match = re.search(r'\b(20\d{2})\b', filename)
    year = int(year_match.group()) if year_match else None
    return month, year

# Filter claims based on valid date range
def filter_valid_dates(df, date_col, year_range):
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    valid_mask = (df[date_col] >= year_range[0]) & (df[date_col] <= year_range[1])
    return df[valid_mask]

# Process data into quarters and apply capping logic
def process_claims(files, year1_range, year2_range):
    all_claims = pd.DataFrame()
    quarter_data = {}
    year2_cumulative_payout = {}

    for file in files:
        filename = file.name.lower()
        month_name, year = extract_month_year(filename)

        if not month_name or not year:
            continue  # Skip files without proper month/year detection

        month_number = month_mapping[month_name]
        quarter = assign_quarter(month_number)
        quarter_key = f"{quarter}-{year}"

        # Load file and process each sheet
        xls = pd.ExcelFile(file)
        for sheet in xls.sheet_names:
            df = pd.read_excel(file, sheet_name=sheet)
            detected_columns = detect_columns(df)

            if all(col in detected_columns for col in ["COD_ASEGURADO", "NOMBRE_ASEGURADO", "FECHA_RECLAMO", "MONTO"]):
                date_range = year1_range if year == year1_range[0].year else year2_range
                valid_claims = filter_valid_dates(df, detected_columns["FECHA_RECLAMO"], date_range)

                # Add quarter assignment
                valid_claims["QUARTER"] = quarter_key

                # Year 1: Apply a cap of 20,000
                if year == year1_range[0].year:
                    valid_claims["COVID_AMOUNT"] = np.where(
                        valid_claims.get(detected_columns["DIAGNOSTICO"], "").astype(str).str.contains("COVID", case=False, na=False),
                        valid_claims[detected_columns["MONTO"]],
                        0
                    )
                    valid_claims["GENERAL_AMOUNT"] = valid_claims[detected_columns["MONTO"]] - valid_claims["COVID_AMOUNT"]
                    valid_claims["TOTAL_AMOUNT"] = valid_claims["COVID_AMOUNT"] + valid_claims["GENERAL_AMOUNT"]
                    valid_claims["FINAL"] = valid_claims["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, 20000))

                # Year 2: Apply payout trigger and cap
                else:
                    grouped = valid_claims.groupby(detected_columns["COD_ASEGURADO"])[detected_columns["MONTO"]].sum()
                    payouts = []

                    for cod, total_claim in grouped.items():
                        cumulative = year2_cumulative_payout.get(cod, 0) + total_claim

                        if abs(cumulative) > 40000:
                            payout = min(cumulative, 2000000)  # Cap payout at 2,000,000
                            year2_cumulative_payout[cod] = payout
                        else:
                            payout = 0  # No payment yet if below threshold
                        
                        payouts.append(payout)

                    valid_claims["COVID_AMOUNT"] = 0
                    valid_claims["GENERAL_AMOUNT"] = valid_claims[detected_columns["MONTO"]]
                    valid_claims["TOTAL_AMOUNT"] = valid_claims["GENERAL_AMOUNT"]
                    valid_claims["FINAL"] = payouts

                # Store claims in corresponding quarter
                if quarter_key not in quarter_data:
                    quarter_data[quarter_key] = valid_claims
                else:
                    quarter_data[quarter_key] = pd.concat([quarter_data[quarter_key], valid_claims])

    return quarter_data

# ------------------- Streamlit UI -------------------

st.title("📊 Insurance Claims Processing Tool (Updated for Year 1 & Year 2 Logic)")

# Upload new monthly files
st.header("📁 Upload Monthly Files")
uploaded_files = st.file_uploader("Upload monthly files:", type=["xlsx"], accept_multiple_files=True)

# Process and Generate Report
if st.button("🔄 Process Files"):
    if uploaded_files:
        year1_range = (pd.Timestamp("2023-10-01"), pd.Timestamp("2024-09-30"))
        year2_range = (pd.Timestamp("2024-10-01"), pd.Timestamp("2025-09-30"))

        quarter_data = process_claims(uploaded_files, year1_range, year2_range)

       # Save final report only if there is valid data
if quarter_data:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"Processed_Claims_Report_{timestamp}.xlsx"

    with pd.ExcelWriter(output_file) as writer:
        for quarter, df in quarter_data.items():
            output_df = df[["COD_ASEGURADO", "NOMBRE_ASEGURADO", "COVID_AMOUNT", "GENERAL_AMOUNT", "TOTAL_AMOUNT", "FINAL"]]
            output_df.to_excel(writer, sheet_name=quarter, index=False)

    st.success("✅ Report processed successfully!")
    st.download_button(label="📥 Download Processed Report", data=open(output_file, "rb"), file_name=output_file)

else:
    st.error("❌ No valid claims were found in the uploaded files. Please check your input data or date filters.")
