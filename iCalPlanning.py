import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pytz import timezone
from ics import Calendar, Event

# --- CONFIGURATIE ---
LOCAL_TIMEZONE = timezone("Europe/Brussels")

APP_LOGIN = st.secrets.get("APP_LOGIN", "PZ5911")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "5420")
legend = dict(st.secrets["legende_data"]) if "legende_data" in st.secrets else {}

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True

    st.title("🔒 PZ Deinze-Zulte-Lievegem")
    st.write("Log in om de rooster-extractor te gebruiken.")

    col1, col2 = st.columns(2)
    with col1:
        u_login = st.text_input("Gebruikersnaam")
    with col2:
        u_pass = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen"):
        if u_login == APP_LOGIN and u_pass == APP_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Onjuiste gegevens")
    return False

if not check_password():
    st.stop()

# --- HULPFUNCTIES ---
def convert_to_local_time(event_time):
    naive_time = LOCAL_TIMEZONE.localize(event_time, is_dst=None)
    return naive_time.astimezone(LOCAL_TIMEZONE)

all_months = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12
}

def determine_transparency(code):
    transparent_codes = {"V", "VW", "R", "r", "VF", "VB", "OV", "SV", "UV", "VGR", "X"}
    return "TRANSPARENT" if code in transparent_codes else "OPAQUE"

def process_event(event_date, code, legend_dict):
    clean_code = str(code).strip()
    event_description = legend_dict.get(clean_code, clean_code)
    summary = event_description.split(",")[0].strip() if "," in event_description else event_description
    location = event_description.split(",")[-1].strip() if "," in event_description else ""

    if "," in event_description:
        parts = [p.strip() for p in event_description.split(",")]
        times = next((p for p in parts if "-" in p and ":" in p), None)
        if times:
            try:
                start_time, end_time = times.split("-")
                start_datetime = datetime.combine(event_date, datetime.strptime(start_time.strip(), "%H:%M").time())
                end_datetime = datetime.combine(event_date, datetime.strptime(end_time.strip(), "%H:%M").time())
                if end_datetime <= start_datetime:
                    end_datetime += timedelta(days=1)
            except ValueError:
                start_datetime = event_date
                end_datetime = event_date + timedelta(days=1)
        else:
            start_datetime = event_date
            end_datetime = event_date + timedelta(days=1)
    else:
        start_datetime = event_date
        end_datetime = event_date + timedelta(days=1)

    return {
        "dtstart": start_datetime,
        "dtend": end_datetime,
        "summary": summary,
        "location": location,
        "description": event_description,
        "transparency": determine_transparency(clean_code),
    }

def extract_year_from_c9(df, fallback_year=2027):
    """Leest het jaartal uit cel C9 (rij-index 8, kolom-index 2)."""
    try:
        val = df.iloc[8, 2]
        if pd.notna(val):
            if isinstance(val, (datetime, pd.Timestamp)):
                return int(val.year)
            digits = "".join(ch for ch in str(val) if ch.isdigit())
            if len(digits) >= 4:
                return int(digits[:4])
    except Exception:
        pass
    return fallback_year

def find_date_row_and_col(df):
    """Zoekt automatisch de rij en startkolom waar de dagen (1, 2, 3...) staan."""
    for r_idx in range(min(20, len(df))):
        row = df.iloc[r_idx]
        for c_idx in range(min(10, len(row) - 2)):
            v1, v2, v3 = row.iloc[c_idx], row.iloc[c_idx + 1], row.iloc[c_idx + 2]
            if (
                isinstance(v1, (int, float)) and not pd.isna(v1) and int(v1) == 1
                and isinstance(v2, (int, float)) and not pd.isna(v2) and int(v2) == 2
                and isinstance(v3, (int, float)) and not pd.isna(v3) and int(v3) == 3
            ):
                return r_idx, c_idx
    return 7, 3  # Fallback naar rij 8, kolom D

def find_user_row(df, search_name, fallback_row_1based):
    """Zoekt de rij van de gebruiker op naam; valt terug op het ingevulde rijnummer."""
    target = search_name.strip().lower()
    if target:
        for r_idx in range(len(df)):
            row_text = " ".join(str(x).strip().lower() for x in df.iloc[r_idx, :4] if pd.notna(x))
            if target in row_text:
                return r_idx
    return fallback_row_1based - 1

# --- STREAMLIT INTERFACE ---
st.set_page_config(page_title="Planning Extractor", page_icon="📅")
st.title("📅 Planning naar ICS Extractor")
st.markdown(f"Welkom, **{APP_LOGIN}**. Upload je Excel-planning en download direct een kalenderbestand.")

with st.sidebar:
    st.header("Instellingen")
    user_name = st.text_input("Naam in rooster / voor bestand", "BOUCHE G")
    auto_find_name = st.checkbox("Zoek rij automatisch op naam", value=True)
    row_input = st.number_input("Rij-index in Excel (fallback)", min_value=1, value=64)
    month_options = list(all_months.keys())
    selected_months = st.multiselect("Selecteer maand(en)", month_options, default=["januari"])

uploaded_file = st.file_uploader("Kies een Excel bestand", type=["xlsx", "xls"])

if uploaded_file and st.button("Genereer Kalender"):
    try:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_map = {sheet.strip().lower(): sheet for sheet in excel_file.sheet_names}
        all_output_events = []

        for m_name in selected_months:
            if m_name in all_months and m_name in sheet_map:
                actual_sheet = sheet_map[m_name]
                month_num = all_months[m_name]
                df = pd.read_excel(uploaded_file, sheet_name=actual_sheet, header=None)

                # 1. Lees jaar uit C9 (rij 9, kolom C)
                year = extract_year_from_c9(df, fallback_year=2027)

                # 2. Vind automatisch de rij met dagen (1, 2, 3...) en de startkolom
                date_row_idx, start_col_idx = find_date_row_and_col(df)

                # 3. Vind jouw rij (op naam of op rijnummer)
                user_row_idx = (
                    find_user_row(df, user_name, row_input)
                    if auto_find_name
                    else row_input - 1
                )

                dates = df.iloc[date_row_idx, start_col_idx:]
                events = df.iloc[user_row_idx, start_col_idx:]

                for day, code in zip(dates, events):
                    if pd.notna(day) and pd.notna(code):
                        if isinstance(day, (datetime, pd.Timestamp)):
                            day = day.day
                        if isinstance(day, (int, float)) and 1 <= int(day) <= 31:
                            event_date = datetime(year, month_num, int(day))
                            ev_data = process_event(event_date, str(code), legend)
                            ev_data["dtstart"] = convert_to_local_time(ev_data["dtstart"])
                            ev_data["dtend"] = convert_to_local_time(ev_data["dtend"])
                            all_output_events.append(ev_data)

        if all_output_events:
            cal = Calendar()
            for ev in all_output_events:
                e = Event(
                    name=ev["summary"],
                    begin=ev["dtstart"],
                    end=ev["dtend"],
                    location=ev["location"],
                    description=ev["description"],
                )
                cal.events.add(e)

            st.success(f"Klaar! {len(all_output_events)} diensten gevonden.")
            st.download_button(
                label="📥 Download .ics bestand",
                data=str(cal),
                file_name=f"{user_name}_planning.ics",
                mime="text/calendar",
            )
        else:
            st.warning("Geen data gevonden voor de geselecteerde maanden/rij.")

    except Exception as e:
        st.error(f"Fout tijdens verwerking: {e}")
