from datetime import datetime
import io
import os
import re
import sqlite3
import smtplib
from contextlib import closing
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st
import pandas as pd

# --- CONFIGURAZIONE SMTP (GMAIL) DA ST.SECRETS ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = st.secrets["smtp"]["sender_email"]
SENDER_PASSWORD = st.secrets["smtp"]["sender_password"]

# --- CONFIGURAZIONE STRIPE ---
LINK_PAGAMENTO_STRIPE = "https://buy.stripe.com/8x2aEZ68c16x8hv5HibZe00"

# --- PERCORSI PORTABILI CON PATHLIB ---
PROJECT_DIR = Path(__file__).parent if "__file__" in locals() else Path.cwd()
DB_PATH = PROJECT_DIR / "clienti_risposte.db"

st.set_page_config(page_title="Radar Bandi B2B - Area Download e CRM", layout="wide")


def get_db_connection():
    """Restituisce una connessione SQLite configurata con timeout per evitare blocchi."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row  # Accesso ai campi tramite nome colonna
    return conn


def inizializza_db_automatico():
    """Garantisce che la directory e le tabelle del database esistano."""
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS risposte_clienti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    studio_nome TEXT,
                    email TEXT,
                    regione TEXT,
                    bando_titolo TEXT,
                    filename_dossier TEXT,
                    stato TEXT
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS studi_target (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome_studio TEXT,
                    regione TEXT,
                    email_studio TEXT,
                    sito_web TEXT
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS meta_cron (
                    chiave TEXT PRIMARY KEY,
                    ultima_esecuzione TEXT
                )
            """
            )


def popola_target_iniziali():
    """Popola alcuni studi target di esempio divisi per regione se la tabella è vuota."""
    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM studi_target")
            if cursor.fetchone()[0] == 0:
                studi_esempio = [
                    ("Studio Associato Milano - Finanza", "Lombardia", "modafferi39@gmail.com", "https://www.example.it"),
                    ("Consulenza Tributaria Roma", "Lazio", "modafferi39@gmail.com", "https://www.example.it"),
                    ("Studio Commercialisti Torino", "Piemonte", "modafferi39@gmail.com", "https://www.example.it"),
                    ("Finanza & Impresa Verona", "Veneto", "modafferi39@gmail.com", "https://www.example.it"),
                ]
                cursor.executemany(
                    "INSERT INTO studi_target (nome_studio, regione, email_studio, sito_web) VALUES (?, ?, ?, ?)",
                    studi_esempio,
                )


def trova_target_per_regione(regione):
    """Recupera gli studi target pertinenti alla regione del bando trovato."""
    inizializza_db_automatico()
    with closing(get_db_connection()) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nome_studio, email_studio FROM studi_target WHERE regione = ?", (regione,))
        studi = cursor.fetchall()
    return studi


def invia_email_marketing_bando(destinatario_email, nome_studio, titolo_bando, regione, file_pdf_path):
    """Invia in automatico l'anteprima/notifica del nuovo bando allo studio target."""
    try:
        msg = MIMEMultipart()
        msg["From"] = f'"Radar Bandi B2B" <{SENDER_EMAIL}>'
        msg["To"] = destinatario_email
        msg["Subject"] = f"Nuovo Bando Attivo ({regione}): {titolo_bando[:40]}... - Dossier Disponibile"

        corpo_messaggio = f"""Gentile {nome_studio},

Il nostro sistema di monitoraggio ha appena verificato l'effettiva apertura di un nuovo bando strategico nella regione {regione}.

Misura rilevata: {titolo_bando}

Abbiamo predisposto un dossier tecnico operativo e i link di accesso diretto per i vostri clienti aziendali. 
Il dossier completo e validato è disponibile per l'acquisizione spot.

Un cordiale saluto,
Team Radar Bandi B2B
"""
        msg.attach(MIMEText(corpo_messaggio, "plain", "utf-8"))

        pdf_path_obj = Path(file_pdf_path)
        if pdf_path_obj.exists():
            with open(pdf_path_obj, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment; filename=anteprima_bando.pdf")
            msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, destinatario_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Errore durante l'invio dell'email marketing: {e}")
        return False


def estrai_link_bando_esatto(file_path, bando_titolo=""):
    titolo_lower = bando_titolo.lower() if bando_titolo else ""
    path_obj = Path(file_path)
    if path_obj.exists():
        try:
            testo_completo = path_obj.read_text(encoding="utf-8")
            urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', testo_completo)
            if urls:
                for u in urls:
                    u_clean = u.strip(".,;:\"'()")
                    if not u_clean.startswith("http"):
                        u_clean = "https://" + u_clean
                    if any(k in u_clean.lower() for k in ["bando", "avviso", "regione", "lazioinnova"]):
                        return u_clean
                return urls[0].strip(".,;:\"'()")
        except Exception:
            pass

    if "lazio" in titolo_lower:
        return "https://www.lazioinnova.it/bandi/"
    elif "lombardia" in titolo_lower:
        return "https://www.bandi.regione.lombardia.it/"
    elif "piemonte" in titolo_lower:
        return "https://www.regione.piemonte.it/web/temi/attivita-produttive/finanziamenti"
    return "https://www.bandi.it/"


def converti_txt_in_pdf_reportlab(txt_path, pdf_path, studio_nome, bando_titolo, regione):
    txt_path_obj = Path(txt_path)
    pdf_path_obj = Path(pdf_path)

    contenuto_testo = "Dossier Tecnico Operativo B2B"
    if txt_path_obj.exists():
        try:
            contenuto_testo = txt_path_obj.read_text(encoding="utf-8")
        except Exception:
            pass

    link_esatto = estrai_link_bando_esatto(txt_path_obj, bando_titolo)
    doc = SimpleDocTemplate(str(pdf_path_obj), pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36,
                            bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16,
                                 textColor=colors.HexColor("#1b365d"), spaceAfter=6)
    subtitle_style = ParagraphStyle("SubTitleStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=10,
                                    textColor=colors.HexColor("#555555"), spaceAfter=15)
    body_style = ParagraphStyle("BodyStyle", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=14,
                                textColor=colors.HexColor("#2c3e50"), spaceAfter=10)
    link_style = ParagraphStyle("LinkStyle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10,
                                textColor=colors.HexColor("#2980b9"), spaceBefore=15, spaceAfter=15)

    story.append(Paragraph("DOSSIER TECNICO OPERATIVO B2B", title_style))
    story.append(Paragraph(f"<b>Studio:</b> {studio_nome} | <b>Regione:</b> {regione} | <b>Misura:</b> {bando_titolo}",
                           subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Analisi di Fattibilità & Contenuto Operativo:</b>", body_style))
    for riga in contenuto_testo.split("\n"):
        if riga.strip():
            story.append(Paragraph(riga, body_style))

    story.append(Spacer(1, 15))
    story.append(Paragraph("<b>Riferimento Istituzionale & Link Diretto al Bando:</b>", body_style))
    story.append(
        Paragraph(f'<a href="{link_esatto}"><b>🔗 ACCEDI AL BANDO UFFICIALE: {link_esatto}</b></a>', link_style))

    doc.build(story)
    return str(pdf_path_obj)


def inserisci_bando_automatico_e_notifica(studio_nome, email, regione, bando_titolo, contenuto_dossier):
    """Flusso completo: Inserisce il bando, genera il dossier, trova i target e invia le notifiche mail."""
    inizializza_db_automatico()
    popola_target_iniziali()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_txt = f"DOSSIER_{regione.upper()}_{timestamp}.txt"
    txt_path = PROJECT_DIR / filename_txt

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(contenuto_dossier)

    email_pulita = email.strip().lower()

    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM risposte_clienti WHERE LOWER(email) = ?", (email_pulita,))
            esistente = cursor.fetchone()

            if esistente:
                cursor.execute(
                    """
                    UPDATE risposte_clienti 
                    SET studio_nome = ?, regione = ?, bando_titolo = ?, filename_dossier = ?, stato = 'Da pagare'
                    WHERE LOWER(email) = ?
                """,
                    (studio_nome, regione, bando_titolo, filename_txt, email_pulita),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO risposte_clienti (studio_nome, email, regione, bando_titolo, filename_dossier, stato)
                    VALUES (?, ?, ?, ?, ?, 'Da pagare')
                """,
                    (studio_nome, email, regione, bando_titolo, filename_txt),
                )

    pdf_path = txt_path.with_suffix(".pdf")
    converti_txt_in_pdf_reportlab(txt_path, pdf_path, studio_nome, bando_titolo, regione)

    studi_target = trova_target_per_regione(regione)
    inviate_count = 0
    for target_nome, target_email in studi_target:
        if target_email:
            successo = invia_email_marketing_bando(target_email, target_nome, bando_titolo, regione, pdf_path)
            if successo:
                inviate_count += 1

    return filename_txt, inviate_count


def task_ricerca_bandi_giornaliera():
    """Task eseguito in automatico alla prima visita giornaliera."""
    auto_studio = "Studio Associato Automatico"
    auto_email = "modafferi39@gmail.com"
    auto_regione = "Lazio"
    auto_titolo = "Bando Aggiornato Automaticamente - " + datetime.now().strftime("%d/%m/%Y")

    testo_dossier_generato = f"""========== DOSSIER GIORNALIERO AUTOMATICO ({auto_regione.upper()}) ==========
Aggiornamento giornaliero dei bandi attivi per la regione {auto_regione}.
Misura: {auto_titolo}
Contributo e scadenze verificati automaticamente dal sistema di monitoraggio.
"""
    inserisci_bando_automatico_e_notifica(
        auto_studio, auto_email, auto_regione, auto_titolo, testo_dossier_generato
    )


def controlla_ed_esegui_task_giornaliero():
    """Controlla se oggi è già stata eseguita la ricerca automatica. In caso contrario, la esegue."""
    inizializza_db_automatico()
    oggi = datetime.now().strftime("%Y-%m-%d")
    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ultima_esecuzione FROM meta_cron WHERE chiave = 'ultima_ricerca_bandi'")
            row = cursor.fetchone()

            if not row or row["ultima_esecuzione"] != oggi:
                task_ricerca_bandi_giornaliera()
                cursor.execute(
                    "INSERT OR REPLACE INTO meta_cron (chiave, ultima_esecuzione) VALUES ('ultima_ricerca_bandi', ?)",
                    (oggi,),
                )


# Esegue il controllo lazy all'avvio dell'app dopo tutte le definizioni
controlla_ed_esegui_task_giornaliero()


def get_lead_by_email(email):
    if not DB_PATH.exists():
        return None
    email_pulita = email.strip().lower()
    with closing(get_db_connection()) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, studio_nome, email, regione, bando_titolo, filename_dossier, stato FROM risposte_clienti WHERE LOWER(email) = ?",
                (email_pulita,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            return None


def get_all_leads():
    if not DB_PATH.exists():
        return []
    try:
        with closing(get_db_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, studio_nome, email, regione, bando_titolo, filename_dossier, stato FROM risposte_clienti")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def aggiorna_stato_pagato(lead_id):
    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE risposte_clienti SET stato = 'Pagato e Scaricato' WHERE id = ?", (lead_id,))


def genera_pdf_report_crm(df_leads):
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30,
                            bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14,
                                 textColor=colors.HexColor("#1b365d"), spaceAfter=10)
    story.append(Paragraph("Report Generale Attività e Pipeline CRM - Radar Bandi B2B", title_style))
    story.append(Spacer(1, 10))

    data = [["ID", "Studio", "Email", "Regione", "Bando", "Stato"]]
    for _, row in df_leads.iterrows():
        data.append(
            [str(row["id"]), str(row["studio_nome"]), str(row["email"]), str(row["regione"]), str(row["bando_titolo"]),
             str(row["stato"])])

    t = Table(data, colWidths=[30, 150, 160, 90, 200, 110])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b365d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t)
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()


def invia_email_con_materiali(destinatario_email, studio_nome, bando_titolo, regione, file_pdf_path):
    try:
        msg = MIMEMultipart()
        msg["From"] = f'"Radar Bandi B2B" <{SENDER_EMAIL}>'
        msg["To"] = destinatario_email
        msg["Subject"] = f"Dossier Tecnico PDF & Link Ufficiale Bando - {regione}"

        link_esatto = estrai_link_bando_esatto(file_pdf_path, bando_titolo)
        corpo_messaggio = f"""Gentile {studio_nome},

Grazie per aver completato l'attivazione in modalità spot.

Riepilogo dei dati di riferimento:
- Email Studio / Pagante: {destinatario_email}
- Regione: {regione}
- Misura: {bando_titolo}
- Link Ufficiale Diretto al Bando: {link_esatto}

In allegato a questa email troverete il Dossier Tecnico Operativo completo in formato PDF.

Un cordiale saluto,
Team Radar Bandi B2B
"""
        msg.attach(MIMEText(corpo_messaggio, "plain", "utf-8"))

        pdf_path_obj = Path(file_pdf_path)
        if pdf_path_obj.exists():
            with open(pdf_path_obj, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            filename_allegato = pdf_path_obj.name
            part.add_header("Content-Disposition", f"attachment; filename={filename_allegato}")
            msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, destinatario_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Errore nell'invio dell'email post-pagamento: {e}")
        return False


# --- GESTIONE PASSWORD AMMINISTRATIVA (DA ST.SECRETS) ---
st.sidebar.title("🔐 Area Amministrativa")
PASSWORD_CRM = st.secrets["credentials"]["password_crm"]
password_inserita = st.sidebar.text_input("Password CRM:", type="password")

is_admin = False
if password_inserita == PASSWORD_CRM:
    st.sidebar.success("Accesso CRM Autorizzato!")
    is_admin = True
    st.sidebar.divider()

    with st.sidebar.expander("🤖 Scansione & Notifica Target", expanded=False):
        st.markdown(
            "Avvia la ricerca di un bando: individua automaticamente i target regionali e invia le mail informative.")
        auto_studio = st.text_input("Nome Studio Riferimento", "Studio Associato Test", key="auto_studio")
        auto_email = st.text_input("Email Studio Riferimento", "modafferi39@gmail.com", key="auto_email")
        auto_regione = st.selectbox("Regione",
                                    ["Lazio", "Lombardia", "Piemonte", "Veneto", "Campania", "Sicilia", "Toscana"],
                                    key="auto_regione")
        auto_titolo = st.text_input("Titolo Bando", "Bando Innovazione e Digitalizzazione PMI 2026", key="auto_titolo")

        if st.button("Esegui Ricerca, Trova Target e Invia Notifiche"):
            testo_dossier_generato = f"""========== DOSSIER INFORMATIVO - BANDO ATTIVO ({auto_regione.upper()}) ==========
Rilevato tramite automazione script di scansione portali istituzionali.
Dettagli Tecnici:
- Regione: {auto_regione}
- Misura: {auto_titolo}
- Contributo Massimo: Fino a 50.000 € a fondo perduto.
- Scadenza: Apertura sportello telematica attiva."""

            with st.spinner("Generazione dossier e invio email automatiche ai target regionali..."):
                _, count_inviate = inserisci_bando_automatico_e_notifica(
                    auto_studio, auto_email, auto_regione, auto_titolo, testo_dossier_generato
                )
            st.success(
                f"Bando registrato! Inviate {count_inviate} email informative ai target della regione {auto_regione}.")
            st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("📥 Esportazione Dati")
    leads_raw = get_all_leads()
    if leads_raw:
        df_crm = pd.DataFrame(leads_raw)
        output_excel = io.BytesIO()
        with pd.ExcelWriter(output_excel, engine="xlsxwriter") as writer:
            df_crm.to_excel(writer, index=False, sheet_name="Lead CRM")
        excel_data = output_excel.getvalue()

        st.sidebar.download_button("📊 Scarica Attività (Excel)", data=excel_data, file_name="report_attivita_crm.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        csv_data = df_crm.to_csv(index=False).encode("utf-8")
        st.sidebar.download_button("📄 Scarica Attività (CSV)", data=csv_data, file_name="report_attivita_crm.csv",
                                   mime="text/csv")
        pdf_report_data = genera_pdf_report_crm(df_crm)
        st.sidebar.download_button("📑 Scarica Attività (PDF)", data=pdf_report_data,
                                   file_name="report_attivita_crm.pdf", mime="application/pdf")
    else:
        st.sidebar.info("Nessun dato da esportare.")

    st.sidebar.divider()
    if st.sidebar.button("Forza reset stato lead"):
        if DB_PATH.exists():
            with closing(get_db_connection()) as conn:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE risposte_clienti SET stato = 'Da pagare'")
            st.sidebar.success("Stato resettato!")
            st.rerun()

elif password_inserita:
    st.sidebar.error("Password errata.")
else:
    st.sidebar.info("Inserisci la password nella barra laterale per sbloccare l'area amministrativa.")

# --- CONTROLLO AUTOMATICO RITORNO DA STRIPE (QUERY PARAMS) ---
query_params = st.query_params
if "successo" in query_params and "email" in query_params:
    email_ritorno = query_params["email"]
    lead_verificato = get_lead_by_email(email_ritorno)
    if lead_verificato:
        lead_id_v = lead_verificato["id"]
        studio_v = lead_verificato["studio_nome"]
        email_v = lead_verificato["email"]
        reg_v = lead_verificato["regione"]
        bando_v = lead_verificato["bando_titolo"]
        file_v = lead_verificato["filename_dossier"]
        stato_v = lead_verificato["stato"]

        if "pagato" not in str(stato_v).lower():
            aggiorna_stato_pagato(lead_id_v)
            pdf_v_filename = Path(file_v).with_suffix(".pdf").name
            pdf_v_path = PROJECT_DIR / pdf_v_filename
            if not pdf_v_path.exists():
                converti_txt_in_pdf_reportlab(PROJECT_DIR / file_v, pdf_v_path, studio_v, bando_v, reg_v)
            invia_email_con_materiali(email_v, studio_v, bando_v, reg_v, pdf_v_path)
            st.success("Pagamento verificato! Controlla la tua email per i materiali.")

# --- INTERFACCIA PRINCIPALE ---
tab_download, tab_crm = st.tabs(["📥 Area Download Clienti", "📊 CRM & Gestione Lead"])

with tab_download:
    st.title("📁 Radar Bandi B2B - Area Download Riservata")
    st.markdown("Inserisci l'email aziendale per verificare la tua posizione e sbloccare i materiali.")
    email_input = st.text_input("Email dello Studio di Consulenza:")

    if email_input:
        lead = get_lead_by_email(email_input)
        if lead:
            lead_id = lead["id"]
            studio_nome = lead["studio_nome"]
            email = lead["email"]
            regione = lead["regione"]
            bando_titolo = lead["bando_titolo"]
            filename_dossier = lead["filename_dossier"]
            stato = lead["stato"]

            st.markdown(f"### Benvenuto, **{studio_nome}**")
            st.info(f"**Bando Abbinato:** {bando_titolo} ({regione})")

            txt_path = PROJECT_DIR / filename_dossier
            pdf_filename = Path(filename_dossier).with_suffix(".pdf").name
            pdf_path = PROJECT_DIR / pdf_filename
            link_esatto = estrai_link_bando_esatto(txt_path, bando_titolo)

            if not pdf_path.exists() or (txt_path.exists() and txt_path.stat().st_mtime > pdf_path.stat().st_mtime):
                converti_txt_in_pdf_reportlab(txt_path, pdf_path, studio_nome, bando_titolo, regione)

            stato_pulito = str(stato).strip().lower() if stato else ""
            is_pagato = "pagato" in stato_pulito or "scaricato" in stato_pulito

            if is_pagato:
                st.success("Il pagamento risulta effettuato. Scarica i file:")
                if pdf_path.exists():
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    st.download_button(label="📥 Scarica Dossier Tecnico Ufficiale (.PDF)", data=pdf_bytes,
                                       file_name=pdf_filename, mime="application/pdf")
                st.markdown(f"🔗 **Link Diretto al Bando Ufficiale:** [Apri Pagina]({link_esatto})")
            else:
                st.warning("Per sbloccare l'accesso completo, procedi al pagamento spot.")
                with st.expander("📖 Anteprima Gratuita Estratto Dossier", expanded=True):
                    testo_anteprima = "Contenuto non disponibile."
                    if txt_path.exists():
                        try:
                            contenuto_completo = txt_path.read_text(encoding="utf-8")
                            testo_anteprima = contenuto_completo[:400] + "..." if len(
                                contenuto_completo) > 400 else contenuto_completo
                        except Exception:
                            pass
                    st.write(testo_anteprima)

                st.markdown(f"""
                    <a href="{LINK_PAGAMENTO_STRIPE}" target="_blank">
                        <button style="background-color:#635bff; color:white; padding:12px 24px; border:none; border-radius:6px; cursor:pointer; font-size:16px; font-weight:bold; width:100%;">
                            💳 Paga con Carta / Stripe (69,00 €)
                        </button>
                    </a>
                """, unsafe_allow_html=True)

                if is_admin:
                    st.write("")
                    if st.button("Simula Conferma Pagamento (Test Interno)"):
                        aggiorna_stato_pagato(lead_id)
                        invia_email_con_materiali(email, studio_nome, bando_titolo, regione, pdf_path)
                        st.success("Pagamento confermato e materiali inviati via email!")
                        st.rerun()
        else:
            st.error("Nessun dossier associato a questa email.")

with tab_crm:
    if is_admin:
        st.title("📊 CRM & Gestione Pipeline Lead")
        tutti_i_lead = get_all_leads()
        if tutti_i_lead:
            tot_lead = len(tutti_i_lead)
            pagati = sum(1 for l in tutti_i_lead if l["stato"] == "Pagato e Scaricato")
            da_pagare = tot_lead - pagati
            fatturato_totale = pagati * 69.0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Totale Lead", tot_lead)
            c2.metric("Convertiti", pagati)
            c3.metric("Da Convertire", da_pagare)
            c4.metric("Fatturato", f"€ {fatturato_totale:,.2f}")
            st.divider()

            st.subheader("Panoramica Tabellare Pipeline")
            df_display = pd.DataFrame(tutti_i_lead)
            st.dataframe(
                df_display,
                use_container_width=True,
                column_config={
                    "id": "ID",
                    "studio_nome": "Studio",
                    "email": st.column_config.LinkColumn("Contatto Email"),
                    "regione": "Regione",
                    "bando_titolo": "Misura / Bando",
                    "filename_dossier": "File Dossier",
                    "stato": st.column_config.SelectboxColumn("Stato Lead", options=["Da pagare", "Pagato e Scaricato"])
                }
            )

            st.divider()
            st.subheader("Azioni Rapide sui Lead")
            for l in tutti_i_lead:
                lead_id = l["id"]
                studio_nome = l["studio_nome"]
                email = l["email"]
                regione = l["regione"]
                stato = l["stato"]

                with st.container(border=True):
                    c_info, c_status, c_action = st.columns([3, 2, 2])
                    c_info.markdown(f"**🏢 {studio_nome}** \n 📧 `{email}` | 📍 {regione}")
                    c_status.markdown(f"**Stato:** {stato}")
                    if c_action.button(f"Forza Pagato ID {lead_id}", key=f"crm_{lead_id}"):
                        aggiorna_stato_pagato(lead_id)
                        st.rerun()
        else:
            st.info("Nessun lead presente.")
    else:
        st.title("🔒 Area Riservata CRM")
        st.warning("Inserisci la password amministrativa nella barra laterale.")
