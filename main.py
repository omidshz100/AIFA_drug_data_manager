import streamlit as st
import sqlite3
import pandas as pd

DB_NAME = "test_mohammad_omid.db"
TABLE_NAME = "sheet1"

COLUMNS = [
    "Principio Attivo",
    "Descrizione Gruppo",
    "Denominazione e Confezione",
    "Titolare AIC",
    "Codice  AIC",
    "Codice Gruppo Equivalenza",
    "Class",
    "ATC",
    "4.1 Indicazioni terapeutiche",
    "4.2 Posologia e modo di somministrazione",
    "4.3 Contraindications",
    "4.4 Special warnings and precautions for use",
    "4.5 Interactions with other medicinal products",
    "4.6 Fertility, pregnancy and lactation",
    "4.7 Effects on ability to drive and use machines",
    "4.8 Undesirable effects (side effects)",
    "4.9 Overdose",
    "6.2 Incompatibilities",
    "URL_PDF",
    "URL_json"
]

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            "Principio Attivo" TEXT,
            "Descrizione Gruppo" TEXT,
            "Denominazione e Confezione" TEXT PRIMARY KEY,
            "Titolare AIC" TEXT,
            "Codice AIC" INTEGER,
            "Codice Gruppo Equivalenza" TEXT,
            "Class" TEXT,
            "ATC" TEXT,
            "4.1 Indicazioni terapeutiche" TEXT,
            "4.2 Posologia e modo di somministrazione" TEXT,
            "4.3 Contraindications" TEXT,
            "4.4 Special warnings and precautions for use" TEXT,
            "4.5 Interactions with other medicinal products" TEXT,
            "4.6 Fertility, pregnancy and lactation" TEXT,
            "4.7 Effects on ability to drive and use machines" TEXT,
            "4.8 Undesirable effects (side effects)" TEXT,
            "4.9 Overdose" TEXT,
            "6.2 Incompatibilities" TEXT,
            "URL_PDF" TEXT,
            "URL_json" TEXT
        )
    """)
    conn.commit()
    conn.close()

def fetch_all(offset=0, limit=20):
    conn = get_connection()
    df = pd.read_sql_query(
        f'SELECT * FROM "{TABLE_NAME}" LIMIT ? OFFSET ?',
        conn, params=(limit, offset)
    )
    conn.close()
    return df

def search_data(term):
    conn = get_connection()
    query = f'''
        SELECT * FROM "{TABLE_NAME}"
        WHERE "Principio Attivo" LIKE ?
           OR "Denominazione e Confezione" LIKE ?
           OR "Codice  AIC" LIKE ?
    '''
    df = pd.read_sql_query(query, conn, params=(f"%{term}%", f"%{term}%", f"%{term}%"))
    conn.close()
    return df

def fetch_by_pk(pk):
    conn = get_connection()
    df = pd.read_sql_query(
        f'SELECT * FROM "{TABLE_NAME}" WHERE "Codice  AIC" = ?',
        conn, params=(pk,)
    )
    conn.close()
    return df.iloc[0] if not df.empty else None

def update_record(pk, data):
    conn = get_connection()
    c = conn.cursor()
    set_clause = ", ".join([f'"{col}"=?' for col in COLUMNS if col != "Codice  AIC"])
    values = [data[col] for col in COLUMNS if col != "Codice  AIC"]
    values.append(pk)
    try:
        c.execute(
            f'UPDATE "{TABLE_NAME}" SET {set_clause} WHERE "Codice  AIC" = ?',
            values
        )
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Update failed: {e}")
        return False
    finally:
        conn.close()

def insert_record(data):
    conn = get_connection()
    c = conn.cursor()
    placeholders = ", ".join(["?"] * len(COLUMNS))
    col_names = ', '.join([f'"{col}"' for col in COLUMNS])
    try:
        c.execute(
            f'INSERT INTO "{TABLE_NAME}" ({col_names}) VALUES ({placeholders})',
            [data[col] for col in COLUMNS]
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        st.error("A record with this Codice  AIC already exists.")
        return False
    except Exception as e:
        st.error(f"Insertion failed: {e}")
        return False
    finally:
        conn.close()

def delete_record(pk):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            f'DELETE FROM "{TABLE_NAME}" WHERE "Codice  AIC" = ?',
            (pk,)
        )
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Delete failed: {e}")
        return False
    finally:
        conn.close()

def main():
    st.set_page_config(page_title="Medicines DB Manager", layout="wide")
    st.title("Medicines Database Manager")

    init_db()

    menu = st.sidebar.radio("Menu", ["View All", "Search", "Add New", "Edit", "Delete"])

    if menu == "View All":
        st.header("All Drugs")
        page_size = st.number_input("Rows per page", 5, 100, 20)
        page = st.number_input("Page", 1, 100, 1)
        offset = (page - 1) * page_size
        df = fetch_all(offset=offset, limit=page_size)
        st.dataframe(df, use_container_width=True)

    elif menu == "Search":
        st.header("Search Drugs")
        term = st.text_input('Search by "Principio Attivo", "Denominazione e Confezione", or "Codice  AIC"')
        if term:
            df = search_data(term)
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                selected = st.selectbox("Select a record to edit", df["Codice  AIC"])
                if selected:
                    if st.button("Edit Selected"):
                        st.session_state["edit_pk"] = selected
                        st.rerun()

    elif menu == "Edit":
        st.header("Edit Drug")
        pk = st.text_input("Enter Codice  AIC (Primary Key) to edit", st.session_state.get("edit_pk", ""))
        if pk:
            record = fetch_by_pk(pk)
            if record is not None:
                with st.form("edit_form"):
                    new_data = {}
                    for col in COLUMNS:
                        value = st.text_area(col, str(record[col]) if pd.notnull(record[col]) else "")
                        new_data[col] = value
                    submitted = st.form_submit_button("Save Changes")
                    if submitted:
                        if update_record(pk, new_data):
                            st.success("Record updated successfully.")
            else:
                st.warning("Record not found.")

    elif menu == "Add New":
        st.header("Add New Drug")
        with st.form("add_form"):
            new_data = {}
            for col in COLUMNS:
                value = st.text_area(col, "")
                new_data[col] = value
            submitted = st.form_submit_button("Add Drug")
            if submitted:
                if insert_record(new_data):
                    st.success("New drug added successfully.")

    elif menu == "Delete":
        st.header("Delete Drug")
        pk = st.text_input("Enter Codice  AIC (Primary Key) to delete")
        if pk:
            if st.button("Delete"):
                if st.confirm("Are you sure you want to delete this record?"):
                    if delete_record(pk):
                        st.success("Record deleted successfully.")

if __name__ == "__main__":
    main()