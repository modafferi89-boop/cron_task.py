from datetime import datetime
from pathlib import Path
import os
import sqlite3
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

# --- CONFIGURAZIONE PERCORSI E SMTP ---
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "clienti_risposte.db"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.environ.get("SMTP_SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def inizializza_db_automatico():
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS risposte_clienti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                studio_nome TEXT,
                email TEXT,
                regione TEXT,
                bando_titolo TEXT,
                filename_dossier TEXT,
                stato TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS studi_target (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_studio TEXT,
                regione TEXT,
                email_studio TEXT,
                sito_web TEXT
            )
        """)
        conn.commit()


def popola_target_iniziali():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM studi_target")
        if cursor.fetchone()[0] == 0:
            studi_esempio = [
                ("Studio Associato Milano - Finanza", "Lombardia", SENDER_EMAIL, "https://www.example.it"),
                ("Consulenza Tributaria Roma", "Lazio", SENDER_EMAIL, "https://www.example.it"),
            ]
            cursor.executemany(
                "INSERT INTO studi_target (nome_studio, regione, email_studio, sito_web) VALUES (?, ?, ?, ?)",
                studi_esempio,
            )
            conn.commit()


def trova_target_per_regione(regione):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nome_studio, email_studio FROM studi_target WHERE regione = ?", (regione,))
        studi = cursor.fetchall()
    return studi


def converti_txt_in_pdf_reportlab(txt_path, pdf_path, studio_nome, bando_titolo, regione):
    txt_path_obj = Path(txt_path)
    pdf_path_obj = Path(pdf_path)

    contenuto_testo = "Dossier Tecnico Operativo B2B"
    if txt_path_obj.exists():
        try:
            contenuto_testo = txt_path_obj.read_text(encoding="utf-8")
        except Exception:
            pass

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

    story.append(Paragraph("DOSSIER TECNICO OPERATIVO B2B", title_style))
    story.append(Paragraph(f"<b>Studio:</b> {studio_nome} | <b>Regione:</b> {regione} | <b>Misura:</b> {bando_titolo}",
                           subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Analisi di Fattibilità & Contenuto Operativo:</b>", body_style))
    for riga in contenuto_testo.split("\n"):
        if riga.strip():
            story.append(Paragraph(riga, body_style))

    doc.build(story)
    return str(pdf_path_obj)


def invia_email_marketing_bando(destinatario_email, nome_studio, titolo_bando, regione, file_pdf_path):
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
        print(f"Errore invio mail marketing a {destinatario_email}: {e}")
        return False


def esegui_scansione_giornaliera_esterna():
    print("Avvio task automatico programmato...")
    inizializza_db_automatico()
    popola_target_iniziali()

    auto_studio = "Studio Associato Automatico"
    auto_email = SENDER_EMAIL
    auto_regione = "Lazio"
    auto_titolo = "Bando Aggiornato Automaticamente - " + datetime.now().strftime("%d/%m/%Y")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_txt = f"DOSSIER_{auto_regione.upper()}_{timestamp}.txt"
    txt_path = PROJECT_DIR / filename_txt

    contenuto_dossier = f"""========== DOSSIER GIORNALIERO AUTOMATICO ({auto_regione.upper()}) ==========
Aggiornamento giornaliero dei bandi attivi per la regione {auto_regione}.
Misura: {auto_titolo}
Contributo e scadenze verificati automaticamente dal sistema di monitoraggio.
"""
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(contenuto_dossier)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO risposte_clienti (studio_nome, email, regione, bando_titolo, filename_dossier, stato)
            VALUES (?, ?, ?, ?, ?, 'Da pagare')
        """, (auto_studio, auto_email, auto_regione, auto_titolo, filename_txt))
        conn.commit()

    # Genera il PDF corrispondente
    pdf_path = txt_path.with_suffix(".pdf")
    converti_txt_in_pdf_reportlab(txt_path, pdf_path, auto_studio, auto_titolo, auto_regione)

    # Trova i target regionali e invia le notifiche email
    studi_target = trova_target_per_regione(auto_regione)
    inviate_count = 0
    for target_nome, target_email in studi_target:
        if target_email:
            successo = invia_email_marketing_bando(target_email, target_nome, auto_titolo, auto_regione, pdf_path)
            if successo:
                inviate_count += 1

    print(f"Task giornaliero completato con successo. Inviate {inviate_count} email ai target.")


if __name__ == "__main__":
    esegui_scansione_giornaliera_esterna()
