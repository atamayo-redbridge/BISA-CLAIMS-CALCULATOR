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

# Fallback: Extract year directly from dates if filename detection fails
def extract_year_from_dates(df, date_column):
    years = pd.to_datetime(df[date_column], errors='coerce').dt.year.dropna().unique()
    return int(years[0]) if len(years) > 0 else None

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
                df.columns = df.columns.str.upper()
                df["FECHA_RECLAMO"] = pd.to_datetime(df[detected_columns["FECHA_RECLAMO"]], errors="coerce")

                # Include claims from October 1, 2023 to September 30, 2024 (Year 1)
                valid_mask = (
                    (df["FECHA_RECLAMO"] >= year_range[0]) &
                    (df["FECHA_RECLAMO"] <= year_range[1])
                )
                valid_claims = df[valid_mask]

                # Debugging output for valid claims count
                st.write(f"📅 **Sheet:** {sheet} → **Valid Claims:** {len(valid_claims)}")

                # Use the sheet with the most valid claims
                if len(valid_claims) > max_valid_claims:
                    validated_claims = valid_claims
                    max_valid_claims = len(valid_claims)

        return validated_claims
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return pd.DataFrame()

# Process data into quarters with cumulative calculations
def process_quarters(files, year1_range, year2_range):
    all_claims = pd.DataFrame()
    quarter_data = {}

    detected_months = []

    for file in files:
        filename = file.name.lower()
        month, year = extract_month_year(filename)

        claims = load_and_validate_claims(file, year1_range if year == year1_range[0].year else year2_range)

        # Fallback year detection from date values
        if not year:
            detected_columns = detect_columns(claims)
            year = extract_year_from_dates(claims, detected_columns["FECHA_RECLAMO"])
            st.write(f"🔍 **Fallback Year Detection:** Detected year from date values → {year}")

        if month and year:
            claims["MONTH"] = month
            claims["YEAR"] = year
            detected_months.append((file.name, month, year, len(claims)))
            all_claims = pd.concat([all_claims, claims], ignore_index=True)

    # Display detected months, years, and claim counts for verification
    st.subheader("📅 Detected Months, Years, and Valid Claims:")
    for name, month, year, count in detected_months:
        st.write(f"**File:** {name} → **Month:** {month.capitalize()}, **Year:** {year}, **Valid Claims:** {count}")

    # Group files into quarters
    grouped_files = {}
    for _, row in all_claims.iterrows():
        month = month_mapping[row["MONTH"]]
        quarter = (month - 1) // 3 + 1
        year = row["YEAR"]
        quarter_key = f"Q{quarter}-{year}"

        if quarter_key not in grouped_files:
            grouped_files[quarter_key] = []
        grouped_files[quarter_key].append(row)

    # Display detected quarters and their claim counts
    st.subheader("📆 Detected Quarters and Claims:")
    for quarter, claims in grouped_files.items():
        st.write(f"**{quarter}:** {len(claims)} claims")

    # Cumulative processing logic
    cumulative_data = pd.DataFrame()
    progressive_results = {}
    previous_sum = 0

    for quarter, data in grouped_files.items():
        df = pd.DataFrame(data)
        detected_columns = detect_columns(df)

        grouped = df.groupby([detected_columns["COD_ASEGURADO"], detected_columns["NOMBRE_ASEGURADO"]]).agg({
            detected_columns["MONTO"]: "sum"
        }).reset_index().rename(columns={
            detected_columns["COD_ASEGURADO"]: "COD_ASEGURADO",
            detected_columns["NOMBRE_ASEGURADO"]: "NOMBRE_ASEGURADO",
            detected_columns["MONTO"]: "TOTAL_AMOUNT"
        })

        # Apply logic based on year
        year = int(quarter.split("-")[1])
        if year == year1_range[0].year:
            # Year 1: Separate COVID and non-COVID claims
            if "DIAGNOSTICO" in detected_columns:
                df["COVID_AMOUNT"] = np.where(
                    df[detected_columns["DIAGNOSTICO"]].astype(str).str.contains("COVID", case=False, na=False),
                    df[detected_columns["MONTO"]],
                    0
                )
            else:
                df["COVID_AMOUNT"] = 0
            df["GENERAL_AMOUNT"] = df[detected_columns["MONTO"]] - df["COVID_AMOUNT"]

            # Merge sums correctly
            covid_sums = df.groupby("COD_ASEGURADO")["COVID_AMOUNT"].sum()
            grouped = grouped.merge(covid_sums, on="COD_ASEGURADO", how="left").fillna(0)

            general_sums = df.groupby("COD_ASEGURADO")["GENERAL_AMOUNT"].sum()
            grouped = grouped.merge(general_sums, on="COD_ASEGURADO", how="left").fillna(0)

            grouped["TOTAL_AMOUNT"] = grouped["COVID_AMOUNT"] + grouped["GENERAL_AMOUNT"]
            grouped["FINAL"] = grouped["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, 20000))
        else:
            # Year 2: No COVID separation
            grouped["COVID_AMOUNT"] = 0
            grouped["GENERAL_AMOUNT"] = grouped["TOTAL_AMOUNT"]
            grouped["TOTAL_AMOUNT"] = grouped["TOTAL_AMOUNT"].apply(lambda x: cap_value(x, 40000))
            grouped["FINAL"] = grouped["TOTAL_AMOUNT"]

        # Cumulative sum across quarters
        if cumulative_data.empty:
            cumulative_data = grouped
        else:
            cumulative_data = cumulative_data.merge(
                grouped, on=["COD_ASEGURADO", "NOMBRE_ASEGURADO"], how="outer", suffixes=('_prev', '_new')
            ).fillna(0)
            cumulative_data["FINAL"] = cumulative_data["FINAL_prev"] + cumulative_data["FINAL_new"]
            cumulative_data = cumulative_data[["COD_ASEGURADO", "NOMBRE_ASEGURADO", "FINAL"]]

        # Progressive division logic
        total_sum = grouped["FINAL"].sum() / 2
        result = total_sum - previous_sum
        progressive_results[quarter] = result
        previous_sum += result

        quarter_data[quarter] = grouped.copy()

    return quarter_data, progressive_results

# ------------------- Streamlit UI -------------------

st.title("📊 Insurance Claims Processing Tool (Year Detection & Filtering Fix)")

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

        quarter_data, progressive_results = process_quarters(uploaded_files, year1_range, year2_range)

        # Save final report
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_file = f"Processed_Claims_Report_{timestamp}.xlsx"

        with pd.ExcelWriter(output_file) as writer:
            for quarter, df in quarter_data.items():
                output_df = df[["COD_ASEGURADO", "NOMBRE_ASEGURADO", "COVID_AMOUNT", "GENERAL_AMOUNT", "TOTAL_AMOUNT", "FINAL"]]
                output_df.to_excel(writer, sheet_name=quarter, index=False)

            # Add progressive results summary
            summary_df = pd.DataFrame(list(progressive_results.items()), columns=["Quarter", "Progressive_Result"])
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

        st.success("✅ Report processed successfully!")
        st.download_button(label="📥 Download Processed Report", data=open(output_file, "rb"), file_name=output_file)

        # Display progressive results
        st.header("📋 Progressive Results Summary")
        for quarter, value in progressive_results.items():
            st.write(f"{quarter}: {value:,.2f}")
    else:
        st.error("❌ Please upload at least one monthly file.")
