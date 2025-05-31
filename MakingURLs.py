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


def get_aifa_urls(aic):
    """
    Given an AIC code, fetches codiceSis and aic6 from the AIFA API and returns the PDF and JSON URLs.
    Returns None if the content is missing.
    """
    json_url = f"https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=0{aic}&spellingCorrection=true&page=0"
    try:
        response = requests.get(json_url)
        response.raise_for_status()
        data = response.json()
        content = data.get("data", {}).get("content")
        if content and len(content) > 0:
            medicinale = content[0].get("medicinale", {})
            codiceSis = medicinale.get("codiceSis")
            aic6 = medicinale.get("aic6")
            # Check if codiceSis and aic6 are not None
            codiceAtc = content[0].get("codiceAtc")[0] if content[0].get("codiceAtc") else None
            descrizioneAtc = content[0].get("descrizioneAtc")[0] if content[0].get("descrizioneAtc") else None
            if codiceSis and aic6:
                return {
                    "URL_PDF": f"https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/organizzazione/{codiceSis}/farmaci/{aic6}/stampati?ts=RCP",
                    "URL_json": f"https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=0{aic}&spellingCorrection=true&page=0",
                    "ATC": f"{codiceAtc} - {descrizioneAtc}"
                }
    except Exception:
        pass
    return None

rows = get_all_rows(sheet, column_names=["Codice  AIC"])

for row in rows:
    codice_aic = row.get("Codice  AIC")
    if codice_aic:
        urlData = get_aifa_urls(codice_aic)
        if urlData is not None:
            # print(f"Codice AIC: {codice_aic}")
            # print(f"URL PDF: {urlData['URL_PDF']}")
            # print(f"URL JSON: {urlData['URL_json']}")
            # print(f"ATC: {urlData['ATC']}")
            # Update the row in the Google Sheet
            update_row_in_sheet(sheet, "Codice  AIC", codice_aic, {
                "URL_PDF": urlData["URL_PDF"],
                "URL_json": urlData["URL_json"],
                "ATC": urlData["ATC"]
            })
        else: # urlData is None
            update_row_in_sheet(sheet, 'Codice  AIC', codice_aic, {
                    'ATC': 'NON',  
                    'URL_PDF': 'NON',
                    'URL_json': 'NON'
                })
        
        
    else:
        print("No Codice AIC found in this row.")