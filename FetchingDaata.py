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
def process_pdfs_to_sheet(urls, sheet_name=SHEET_NAME):
    records = []
    # Adjust MAX_CELL_CHARS to leave more room for the "[TRUNCATED]" tag
    MAX_CELL_CHARS = 49900
    # [{'Codice  AIC': '43658032', 'URL_PDF':"jhbjhbjbjk"}]
    #  
    for url in urls[9 - 2:15 - 2]:
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
        time.sleep(1.5)  # Be nice to the server
        
    # print(records)
    # # # Send to Google Sheets
    # df = pd.DataFrame(records)
    # sheet = init_google_sheet(sheet_name)
    # sheet.clear()
    # set_with_dataframe(sheet, df)
    # print("✅ Data written to Google Sheet")



rows = get_all_rows(sheet, column_names=["Codice  AIC", "URL_PDF"])
process_pdfs_to_sheet(rows)

# ✅ Call with live AIFA URLs
# process_pdfs_to_sheet([{'Codice  AIC': "1000000", 'URL_PDF': "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4815/farmaci/38773/stampati?ts=RCP"}])
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4815/farmaci/38773/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3295/farmaci/39055/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3295/farmaci/39055/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7020/farmaci/32932/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4311/farmaci/36102/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/5297/farmaci/42471/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4110/farmaci/26888/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4110/farmaci/26888/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/45870/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/45870/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/45870/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/45870/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4375/farmaci/27268/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4375/farmaci/27268/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4375/farmaci/27268/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3438/farmaci/45789/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37378/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37378/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46713/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46713/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4995/farmaci/42410/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/42589/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/43436/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/43584/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/45017/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46713/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/107/farmaci/36967/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/107/farmaci/36967/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/107/farmaci/36967/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4311/farmaci/36321/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4311/farmaci/36321/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/549/farmaci/43811/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/549/farmaci/43811/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/549/farmaci/43811/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/549/farmaci/43811/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3646/farmaci/41225/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3646/farmaci/41225/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3646/farmaci/41225/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3646/farmaci/41225/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3646/farmaci/41225/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/5144/farmaci/27735/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3298/farmaci/44563/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/200/farmaci/37697/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/200/farmaci/37697/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/764/farmaci/39943/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/764/farmaci/39943/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7184/farmaci/28681/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7184/farmaci/28681/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7184/farmaci/28681/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8057/farmaci/44734/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8057/farmaci/44734/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/194/farmaci/41358/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1230/farmaci/47424/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4311/farmaci/38049/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3665/farmaci/43091/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3665/farmaci/43091/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2278/farmaci/23564/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2278/farmaci/23564/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2278/farmaci/27665/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2278/farmaci/27665/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2278/farmaci/23308/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3010/farmaci/50382/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2753/farmaci/37545/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8043/farmaci/37631/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/37741/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3018/farmaci/38866/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/41917/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/37741/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3018/farmaci/38866/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/41917/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/45015/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1896/farmaci/45043/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/45178/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/45342/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/45468/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8043/farmaci/50663/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/45178/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/47875/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8043/farmaci/50664/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1378/farmaci/37804/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1771/farmaci/37967/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/38435/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/37486/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/706/farmaci/38012/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37371/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1378/farmaci/37804/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1771/farmaci/37967/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/38435/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37371/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/34749/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/36171/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/36175/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/36488/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3018/farmaci/38651/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46073/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2812/farmaci/36595/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/38401/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8043/farmaci/39914/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/42121/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/34749/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/36171/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/36488/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3018/farmaci/38651/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/42121/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46073/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/34749/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/36171/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/36175/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2322/farmaci/36488/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3018/farmaci/38651/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/46073/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/36175/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2812/farmaci/36595/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2812/farmaci/36595/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/8043/farmaci/39914/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/813/farmaci/42121/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37382/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1561/farmaci/37382/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/348/farmaci/27066/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/348/farmaci/27066/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7001/farmaci/25682/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/7001/farmaci/25682/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/959/farmaci/46169/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/959/farmaci/46169/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4080/farmaci/46899/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4080/farmaci/46899/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/6515/farmaci/15628/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4037/farmaci/37641/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2869/farmaci/44039/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/819/farmaci/44207/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/911/farmaci/35768/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/911/farmaci/35768/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/911/farmaci/35768/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2829/farmaci/44996/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/45155/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3773/farmaci/45443/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/45447/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/5587/farmaci/45672/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2826/farmaci/47070/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2829/farmaci/44996/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/1392/farmaci/45155/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3773/farmaci/45443/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/3199/farmaci/45447/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/5587/farmaci/45672/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/2826/farmaci/47070/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/898/farmaci/45276/stampati?ts=RCP",
    # "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/4852/farmaci/45675/stampati?ts=RCP"
# ])




