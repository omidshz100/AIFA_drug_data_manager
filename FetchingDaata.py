import fitz  # PyMuPDF
import re
import requests
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials
import io
import unicodedata
from google.oauth2.service_account import Credentials
import time


SHEET_NAME= "TestMohammad-Omid"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("swift-atom-452517-m2-6029accc8a65.json", scopes=scope)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME)


def get_all_rows(sheet, column_names=None):
    """
    Retrieves all rows from the first worksheet of the Google Sheet, optionally mapping to specified column names.

    Args:
        sheet (gspread.Spreadsheet): The connected Google Sheet object.
        column_names (list, optional): List of column names to filter each row dict. If None, returns all columns.

    Returns:
        list: A list of dicts (if column_names provided) or lists (raw rows).
    """
    worksheet = sheet.sheet1
    rows = worksheet.get_all_values()
    if not rows:
        return []
    headers = rows[0]
    data_rows = rows[1:]
    dict_rows = [dict(zip(headers, row)) for row in data_rows]
    if column_names:
        # Only include specified columns in each dict
        filtered_rows = [{col: row.get(col, "") for col in column_names} for row in dict_rows]
        return filtered_rows
    return dict_rows
# Target sections
section_headers = {
    "4.1": "Indicazioni terapeutiche",
    "4.2": "Posologia e modo di somministrazione",
    "4.3": "Controindicazioni",
    "4.4": "Avvertenze speciali e precauzioni d’impiego",
    "4.5": "Interazioni con altri medicinali",
    "4.6": "Fertilità, gravidanza e allattamento",
    "4.7": "Effetti sulla capacità di guidare veicoli",
    "4.8": "Effetti indesiderati",
    "4.9": "Sovradosaggio",
    "6.2": "Incompatibilità"
}

def normalize_text(text):
    """Normalize text for comparison (lowercase, remove accents)."""
    text = text.lower()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    return text

# Step 1: Extract clean lines from PDF
def extract_lines_from_pdf(pdf_bytes):
    lines = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text()
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^(Pagina\s+\d+|AIFA|Ministero della Salute)", line, re.IGNORECASE):
                    continue
                lines.append(line)
    return lines

# Step 2: Extract sections based on section number + title format
def extract_sections_from_lines(lines):
    sections = {sec: "" for sec in section_headers}
    current_section = None
    capture = False

    # Precompute normalized titles for matching
    normalized_titles = {k: normalize_text(v)[:10] for k, v in section_headers.items()}

    i = 0
    while i < len(lines):
        line = lines[i]

        # Try to match section header with optional dot, dash, or extra spaces
        match = re.match(r"^(\d\.\d)[\.\-\s]*([\w\W]*)", line)
        if match:
            sec_num = match.group(1)
            possible_title = match.group(2).strip()
            if sec_num in section_headers:
                # Try to match title on the same line
                if possible_title:
                    if normalized_titles[sec_num] in normalize_text(possible_title):
                        current_section = sec_num
                        capture = True
                        i += 1
                        continue
                # Or try to match title on next line
                elif i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if normalized_titles[sec_num] in normalize_text(next_line):
                        current_section = sec_num
                        capture = True
                        i += 2
                        continue
            # If header found but title doesn't match, stop capturing
            if current_section and sec_num != current_section:
                capture = False

        # Stop if we hit another section header for a different section
        if re.match(r"^(\d\.\d)[\.\-\s]", line) and current_section:
            next_sec = re.match(r"^(\d\.\d)", line).group(1)
            if next_sec != current_section:
                capture = False

        # Append content if we are in a valid section
        if capture and current_section:
            # Avoid adding the section header line itself
            if not re.match(r"^(\d\.\d)[\.\-\s]*([\w\W]*)", line):
                sections[current_section] += " " + line

        i += 1

    # Final cleanup
    for sec in sections:
        sections[sec] = re.sub(r"\s+", " ", sections[sec].strip()) or "Not found"

    return sections

# Step 3: Extract from PDF bytes
def extract_sections_from_pdf(pdf_bytes):
    lines = extract_lines_from_pdf(pdf_bytes)
    return extract_sections_from_lines(lines)

# Step 4: Google Sheets auth
def init_google_sheet(sheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("swift-atom-452517-m2-6029accc8a65.json", scope)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1
def update_row_in_sheet(sheet, search_column, search_value, update_dict):
    """
    Searches for a row where search_column == search_value and updates columns with values from update_dict.

    Args:
        sheet (gspread.Spreadsheet): The connected Google Sheet object.
        search_column (str): The column name to search for.
        search_value (str): The value to match in the search_column.
        update_dict (dict): Dictionary of column names and their new values.

    Returns:
        bool: True if a row was updated, False otherwise.
    """
    worksheet = sheet.sheet1
    headers = worksheet.row_values(1)
    try:
        col_idx = headers.index(search_column)
    except ValueError:
        return False

    all_rows = worksheet.get_all_values()
    for i, row in enumerate(all_rows[1:], start=2):  # start=2 because row 1 is headers
        if len(row) > col_idx and row[col_idx] == search_value:
            # Prepare updated row
            updated_row = list(row) + [''] * (len(headers) - len(row))
            for key, value in update_dict.items():
                if key in headers:
                    idx = headers.index(key)
                    updated_row[idx] = value
            # Ensure updated_row is exactly the same length as headers
            updated_row = updated_row[:len(headers)]
            # Use gspread.utils.rowcol_to_a1 for robust range (row, col)
            from gspread.utils import rowcol_to_a1
            start_cell = rowcol_to_a1(i, 1)
            end_cell = rowcol_to_a1(i, len(headers))
            worksheet.update(range_name=f"{start_cell}:{end_cell}", values=[updated_row])
            return True
    return False
# Step 5: Full process from URLs
def process_pdfs_to_sheet(records_drug, sheet_name=SHEET_NAME):
    records = []
    # Adjust MAX_CELL_CHARS to leave more room for the "[TRUNCATED]" tag
    MAX_CELL_CHARS = 49900
    # [{'Codice  AIC': '43658032', 'URL_PDF':"jhbjhbjbjk"}]
    #  
    for url in records_drug[9 - 2:15 - 2]:
        try:
            print(f"📥 Downloading from {url['URL_PDF']}")
            response = requests.get(url['URL_PDF'])
            response.raise_for_status()
            pdf_bytes = io.BytesIO(response.content)

            sections = extract_sections_from_pdf(pdf_bytes)

            record = {"URL": url}
            for sec_num, sec_title in section_headers.items():
                # Truncate the extracted text if it exceeds the limit
                extracted_text = sections.get(sec_num, "Not found")
                if len(extracted_text) > MAX_CELL_CHARS:
                    record[f"{sec_num} {sec_title}"] = extracted_text[:MAX_CELL_CHARS] + " [TRUNCATED]"
                else:
                    record[f"{sec_num} {sec_title}"] = extracted_text
            
            data = {
        "4.1 Indicazioni terapeutiche": record.get("4.1 Indicazioni terapeutiche", "NON - TROVATO"),
        "4.2 Posologia e modo di somministrazione": record.get("4.2 Posologia e modo di somministrazione", "NON - TROVATO"),
        "4.3 Contraindications": record.get("4.3 Controindicazioni", "NON - TROVATO"),
        "4.4 Special warnings and precautions for use": record.get("4.4 Avvertenze speciali e precauzioni d’impiego", "NON - TROVATO"),
        "4.5 Interactions with other medicinal products": record.get("4.5 Interazioni con altri medicinali", "NON - TROVATO"),
        "4.6 Fertility, pregnancy and lactation": record.get("4.6 Fertilità, gravidanza e allattamento", "NON - TROVATO"),
        "4.7 Effects on ability to drive and use machines": record.get("4.7 Effetti sulla capacità di guidare veicoli", "NON - TROVATO"),
        "4.8 Undesirable effects (side effects)": record.get("4.8 Effetti indesiderati", "NON - TROVATO"),
        "4.9 Overdose": record.get("4.9 Sovradosaggio", "NON - TROVATO"),
        "6.2 Incompatibilities": record.get("6.2 Incompatibilità", "NON - TROVATO")
    }
            update_row_in_sheet(sheet, "Codice  AIC", url['Codice  AIC'], data)
            print(f"{url['Codice  AIC']} Done ✅")
            records.append(record)

        except Exception as e:
            print(f"❌ Failed to process {url}: {e}")
            data = {
        "4.1 Indicazioni terapeutiche": "NON - TROVATO",
        "4.2 Posologia e modo di somministrazione": "NON - TROVATO",
        "4.3 Contraindications": "NON - TROVATO",
        "4.4 Special warnings and precautions for use": "NON - TROVATO",
        "4.5 Interactions with other medicinal products": "NON - TROVATO",
        "4.6 Fertility, pregnancy and lactation": "NON - TROVATO",
        "4.7 Effects on ability to drive and use machines": "NON - TROVATO",
        "4.8 Undesirable effects (side effects)": "NON - TROVATO",
        "4.9 Overdose": "NON - TROVATO",
        "6.2 Incompatibilities": "NON - TROVATO"
    }
            update_row_in_sheet(sheet, "Codice  AIC", url['Codice  AIC'], data)
        # solve goggle sheet request limit
        time.sleep(1.5)  # Be nice to the server



# Fetching all rows from the Google Sheet to get URLs and AIC codes from Google Sheet
rows = get_all_rows(sheet, column_names=["Codice  AIC", "URL_PDF"])
process_pdfs_to_sheet(rows)
