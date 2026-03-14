import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pytz import timezone
from ics import Calendar, Event
import io

# --- CONFIGURATIE ---
LOCAL_TIMEZONE = timezone("Europe/Brussels")

# Laad login en legende uit Secrets
APP_LOGIN = st.secrets["APP_LOGIN"]
APP_PASSWORD = st.secrets["APP_PASSWORD"]
legend = st.secrets["legende_data"]

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

# --- LOGICA ---
def convert_to_local_time(event_time):
    naive_time = LOCAL_TIMEZONE.localize(event_time, is_dst=None)
    return naive_time.astimezone(LOCAL_TIMEZONE)

all_months = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12
}

def determine_transparency(code):
    transparent_codes = {"V", "SV", "VW", "R", "r", "VF", "VB", "OV", "UV", "VGR", "X"}
    return "TRANSPARENT" if code in transparent_codes else "OPAQUE"

def process_event(event_date, code, legend):
    event_description = legend.get(code, code)
    summary = event_description.split(",")[0] if "," in event_description else event_description
    location = event_description.split(",")[-1].strip() if "," in event_description else ""

    if "," in event_description:
        parts = [p.strip() for p in event_description.split(",")]
        times = next((p for p in parts if "-" in p and ":" in p), None)
        if times:
            try:
                start_str, end_str = times.split("-")
                start_datetime = datetime.combine(event_date, datetime.strptime(start_str.strip(), "%H:%M").time())
                end_datetime = datetime.combine(event_date, datetime.strptime(end_str.strip(), "%H:%M").time())
                if end_datetime <= start_datetime:
                    end_datetime += timedelta(days=1)
            except:
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
        "transparency": determine_transparency(code),
    }

# --- INTERFACE ---
st.title("📅 Planning naar iCal")
st.markdown(f"Welkom, **{APP_LOGIN}**. Upload je Excel en kies de maanden.")

with st.sidebar:
    st.header("Instellingen")
    user_name = st.text_input("Naam voor bestand", "BOUCHE G")
    row_input = st.number_input("Rij-index in Excel (jouw rij)", min_value=1, value=64)
    month_options = list(all_months.keys())
    selected_months = st.multiselect("Selecteer maand(en)", month_options, default=["januari"])

uploaded_file = st.file_uploader("Kies Excel bestand", type=["xlsx"])

if uploaded_file and st.button("Genereer Kalender"):
    try:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_map = {sheet.lower(): sheet for sheet in excel_file.sheet_names}
        all_output_events = []
        
        for m_name in selected_months:
            if m_name in sheet_map:
                df = pd.read_excel(uploaded_file, sheet_name=sheet_map[m_name], header=None)
                year = datetime.now().year if all_months[m_name] >= datetime.now().month else datetime.now().year + 1
                
                # Data: Rij 8 (index 7) heeft de dagen, row_input de codes
                dates = df.iloc[7, 3:] 
                events = df.iloc[row_input - 1, 3:]
                
                for day, code in zip(dates, events):
                    if pd.notna(day) and pd.notna(code):
                        if isinstance(day, datetime): day = day.day
                        if isinstance(day, (int, float)) and 1 <= day <= 31:
                            event_date = datetime(year, all_months[m_name], int(day))
                            ev_data = process_event(event_date, str(code), legend)
                            ev_data['dtstart'] = convert_to_local_time(ev_data['dtstart'])
                            ev_data['dtend'] = convert_to_local_time(ev_data['dtend'])
                            all_output_events.append(ev_data)
        
        if all_output_events:
            cal = Calendar()
            for ev in all_output_events:
                e = Event(name=ev["summary"], begin=ev["dtstart"], end=ev["dtend"], 
                          location=ev["location"], description=ev["description"])
                cal.events.add(e)
            
            st.success(f"Gereed! {len(all_output_events)} diensten verwerkt.")
            st.download_button("📥 Download .ics bestand", str(cal), f"{user_name}_planning.ics", "text/calendar")
    except Exception as e:
        st.error(f"Fout: {e}")
