import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pytz import timezone
from ics import Calendar, Event

# --- CONFIGURATIE & SECRETS ---
LOCAL_TIMEZONE = timezone("Europe/Brussels")

APP_LOGIN = st.secrets["APP_LOGIN"]
APP_PASSWORD = st.secrets["APP_PASSWORD"]
legend = dict(st.secrets["legende_data"])

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

def parse_day_number(val):
    """Haalt een geldige dag (1-31) uit een cel."""
    if pd.isna(val):
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return int(val.day)
    if isinstance(val, (int, float)):
        num = int(val)
        return num if 1 <= num <= 31 else None
    text = str(val).strip()
    if text.isdigit():
        num = int(text)
        return num if 1 <= num <= 31 else None
    return None

def find_date_row_and_col(df):
    """Zoekt eerst in rij 9 en 10 (index 8 en 9), daarna breder, naar de rij met dagen en startkolom."""
    candidate_rows = [8, 9] + [r for r in range(min(25, len(df))) if r not in (8, 9)]
    for r_idx in candidate_rows:
        if r_idx >= len(df):
            continue
        row = df.iloc[r_idx]
        for c_idx in range(len(row)):
            d1 = parse_day_number(row.iloc[c_idx])
            if d1 == 1:
                valid_seq = 1
                for offset in range(1, 5):
                    if c_idx + offset < len(row):
                        d_next = parse_day_number(row.iloc[c_idx + offset])
                        if d_next == 1 + offset:
                            valid_seq += 1
                if valid_seq >= 2:
                    return r_idx, c_idx
    return 8, 3

def find_user_row(df, search_name, fallback_row_1based):
    """Zoekt de rij van de gebruiker op naam; valt terug op het ingevulde rijnummer."""
    target = search_name.strip().lower()
    if target:
        for r_idx in range(len(df)):
            row_text = " ".join(str(x).strip().lower() for x in df.iloc[r_idx, :6] if pd.notna(x))
            if target in row_text:
                return r_idx
    return fallback_row_1based - 1

# --- STREAMLIT INTERFACE ---
st.set_page_config(page_title="Planning Extractor", page_icon="📅")
st.title("📅 Planning naar ICS Extractor")
st.markdown(f"Welkom, **{APP_LOGIN}**. Upload je Excel-planning en download direct een kalenderbestand.")

with st.sidebar:
    st.header("Instellingen")
    user_name = st.text_input("Naam voor bestand", "BOUCHE G")
    auto_find_name = st.checkbox("Zoek rij automatisch op naam", value=True)
    row_input = st.number_input("Rij-index in Excel", min_value=1, value=64)
    month_input = st.text_input("Maand(en) (gescheiden door komma)", "januari")

uploaded_file = st.file_uploader("Kies een Excel bestand", type=["xlsx", "xls"])

if uploaded_file and st.button("Genereer Kalender"):
    try:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_map = {sheet.strip().lower(): sheet for sheet in excel_file.sheet_names}

        selected_months = [m.strip().lower() for m in month_input.split(",")]
        all_output_events = []

        for m_name in selected_months:
            if m_name in all_months and m_name in sheet_map:
                actual_sheet = sheet_map[m_name]
                month_num = all_months[m_name]
                df = pd.read_excel(uploaded_file, sheet_name=actual_sheet, header=None)

                year = extract_year_from_c9(df, fallback_year=2027)
                date_row_idx, start_col_idx = find_date_row_and_col(df)
                user_row_idx = (
                    find_user_row(df, user_name, row_input)
                    if auto_find_name
                    else row_input - 1
                )

                dates = df.iloc[date_row_idx, start_col_idx:]
                events = df.iloc[user_row_idx, start_col_idx:]

                for day_val, code in zip(dates, events):
                    day = parse_day_number(day_val)
                    if day is not None and pd.notna(code):
                        code_str = str(code).strip()
                        if code_str:
                            event_date = datetime(year, month_num, day)
                            ev_data = process_event(event_date, code_str, legend)
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

            ics_data = str(cal)
            st.success(f"Klaar! {len(all_output_events)} diensten gevonden.")
            st.download_button(
                label="📥 Download .ics bestand",
                data=ics_data,
                file_name=f"{user_name}_planning.ics",
                mime="text/calendar",
            )
        else:
            st.warning("Geen data gevonden voor de geselecteerde maanden/rij.")

    except Exception as e:
        st.error(f"Fout tijdens verwerking: {e}")
