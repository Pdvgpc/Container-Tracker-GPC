import streamlit as st
import pandas as pd
import hashlib
import uuid
import base64
from io import StringIO
from datetime import datetime, date
from github import Github

st.set_page_config(page_title="Container Tracker GPC", page_icon="🚢", layout="wide")

STATUSES = [
    "Planned", "Booked", "Departed", "On water", "Arrived at port",
    "Customs", "Released", "Delivered", "Completed", "Delayed", "Cancelled"
]

CONTAINER_COLUMNS = [
    "container_id", "container_number", "invoice_number", "supplier",
    "origin_port", "destination_port", "departure_week", "arrival_week",
    "eta_date", "status", "shipping_line", "bl_number", "notes",
    "created_at", "updated_at"
]

SUPPLIER_COLUMNS = [
    "supplier_id", "supplier_name", "contact_name", "email",
    "notes", "active", "created_at", "updated_at"
]

LOG_COLUMNS = [
    "log_id", "container_id", "action", "old_value",
    "new_value", "note", "created_at"
]


def sha256_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_week_code():
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def week_options():
    year = date.today().year
    return [f"{y}-W{w:02d}" for y in range(year - 1, year + 3) for w in range(1, 54)]


def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if st.session_state.logged_in:
        return True

    st.title("Container Tracker GPC")
    st.subheader("Login")

    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if sha256_hash(password) == st.secrets.get("APP_PASSWORD_SHA256", ""):
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Wrong password")

    return False


if not check_login():
    st.stop()


@st.cache_resource
def get_repo():
    g = Github(st.secrets["GITHUB_TOKEN"])
    return g.get_repo(st.secrets["GITHUB_REPO"])


def read_csv(path, columns):
    repo = get_repo()
    branch = st.secrets.get("GITHUB_BRANCH", "main")

    try:
        file = repo.get_contents(path, ref=branch)
        content = base64.b64decode(file.content).decode("utf-8")
        if not content.strip():
            return pd.DataFrame(columns=columns)

        df = pd.read_csv(StringIO(content), dtype=str).fillna("")
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        return df[columns]
    except Exception:
        return pd.DataFrame(columns=columns)


def write_csv(path, df, message):
    repo = get_repo()
    branch = st.secrets.get("GITHUB_BRANCH", "main")
    content = df.to_csv(index=False)

    try:
        file = repo.get_contents(path, ref=branch)
        repo.update_file(path, message, content, file.sha, branch=branch)
    except Exception:
        repo.create_file(path, message, content, branch=branch)


def add_log(container_id, action, old_value="", new_value="", note=""):
    logs = read_csv("data/container_logs.csv", LOG_COLUMNS)
    new_log = {
        "log_id": str(uuid.uuid4()),
        "container_id": container_id,
        "action": action,
        "old_value": old_value,
        "new_value": new_value,
        "note": note,
        "created_at": now_str(),
    }
    logs = pd.concat([logs, pd.DataFrame([new_log])], ignore_index=True)
    write_csv("data/container_logs.csv", logs, "Update container logs")


containers = read_csv("data/containers.csv", CONTAINER_COLUMNS)
suppliers = read_csv("data/suppliers.csv", SUPPLIER_COLUMNS)

st.markdown("# Container Tracker GPC")

nav1, nav2, nav3, nav4, nav5 = st.columns([1.2, 1.2, 1.2, 1.2, 4])

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if nav1.button("Dashboard", use_container_width=True):
    st.session_state.page = "Dashboard"
if nav2.button("Containers", use_container_width=True):
    st.session_state.page = "Containers"
if nav3.button("Suppliers", use_container_width=True):
    st.session_state.page = "Suppliers"
if nav4.button("Logs", use_container_width=True):
    st.session_state.page = "Logs"
if nav5.button("Logout", use_container_width=False):
    st.session_state.logged_in = False
    st.rerun()

st.divider()

total = len(containers)
on_water = len(containers[containers["status"] == "On water"])
arriving_this_week = len(containers[containers["arrival_week"] == current_week_code()])
delayed = len(containers[containers["status"] == "Delayed"])

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Containers", total)
k2.metric("On Water", on_water)
k3.metric("Arriving This Week", arriving_this_week)
k4.metric("Delayed", delayed)

st.divider()

supplier_options = suppliers[
    suppliers["active"].astype(str).str.lower() != "false"
]["supplier_name"].tolist()
supplier_options = sorted([s for s in supplier_options if s])


if st.session_state.page == "Dashboard":
    st.subheader("Active Containers")

    active = containers[~containers["status"].isin(["Completed", "Cancelled"])].copy()

    if active.empty:
        st.info("No active containers yet.")
    else:
        st.dataframe(
            active[
                [
                    "container_number", "invoice_number", "supplier",
                    "origin_port", "destination_port", "departure_week",
                    "arrival_week", "eta_date", "status",
                    "shipping_line", "bl_number", "notes"
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


elif st.session_state.page == "Containers":
    st.subheader("Containers")

    tab1, tab2 = st.tabs(["Overview / Edit", "Add Container"])

    with tab1:
        f1, f2, f3, f4 = st.columns(4)

        search = f1.text_input("Search container / invoice / B/L")
        status_filter = f2.selectbox("Status", ["All"] + STATUSES)
        supplier_filter = f3.selectbox("Supplier", ["All"] + supplier_options)
        arrival_filter = f4.selectbox("Arrival Week", ["All"] + week_options())

        filtered = containers.copy()

        if search:
            filtered = filtered[
                filtered["container_number"].str.contains(search, case=False, na=False)
                | filtered["invoice_number"].str.contains(search, case=False, na=False)
                | filtered["bl_number"].str.contains(search, case=False, na=False)
            ]

        if status_filter != "All":
            filtered = filtered[filtered["status"] == status_filter]

        if supplier_filter != "All":
            filtered = filtered[filtered["supplier"] == supplier_filter]

        if arrival_filter != "All":
            filtered = filtered[filtered["arrival_week"] == arrival_filter]

        st.dataframe(
            filtered[
                [
                    "container_number", "invoice_number", "supplier",
                    "origin_port", "destination_port", "departure_week",
                    "arrival_week", "eta_date", "status",
                    "shipping_line", "bl_number", "notes"
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.subheader("Edit Container")

        if containers.empty:
            st.info("No containers to edit.")
        else:
            selected_container = st.selectbox(
                "Select container",
                containers["container_number"].tolist(),
            )

            row = containers[containers["container_number"] == selected_container].iloc[0]

            with st.form("edit_container_form"):
                c1, c2, c3 = st.columns(3)
                invoice_number = c1.text_input("Invoice Number", value=row["invoice_number"])
                supplier = c2.selectbox(
                    "Supplier",
                    supplier_options if supplier_options else [row["supplier"]],
                    index=supplier_options.index(row["supplier"]) if row["supplier"] in supplier_options else 0,
                )
                status = c3.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0,
                )

                c4, c5, c6 = st.columns(3)
                origin_port = c4.text_input("Origin Port", value=row["origin_port"])
                destination_port = c5.text_input("Destination Port", value=row["destination_port"])
                shipping_line = c6.text_input("Shipping Line", value=row["shipping_line"])

                c7, c8, c9 = st.columns(3)
                weeks = week_options()

                departure_week = c7.selectbox(
                    "Departure Week",
                    weeks,
                    index=weeks.index(row["departure_week"]) if row["departure_week"] in weeks else 0,
                )
                arrival_week = c8.selectbox(
                    "Arrival Week",
                    weeks,
                    index=weeks.index(row["arrival_week"]) if row["arrival_week"] in weeks else 0,
                )
                eta_date = c9.date_input(
                    "ETA Date",
                    value=pd.to_datetime(row["eta_date"]).date() if row["eta_date"] else date.today(),
                )

                bl_number = st.text_input("B/L Number", value=row["bl_number"])
                notes = st.text_area("Notes", value=row["notes"])

                save = st.form_submit_button("Save Changes")

                if save:
                    idx = containers[containers["container_number"] == selected_container].index[0]
                    old_status = containers.at[idx, "status"]

                    containers.at[idx, "invoice_number"] = invoice_number
                    containers.at[idx, "supplier"] = supplier
                    containers.at[idx, "origin_port"] = origin_port
                    containers.at[idx, "destination_port"] = destination_port
                    containers.at[idx, "departure_week"] = departure_week
                    containers.at[idx, "arrival_week"] = arrival_week
                    containers.at[idx, "eta_date"] = str(eta_date)
                    containers.at[idx, "status"] = status
                    containers.at[idx, "shipping_line"] = shipping_line
                    containers.at[idx, "bl_number"] = bl_number
                    containers.at[idx, "notes"] = notes
                    containers.at[idx, "updated_at"] = now_str()

                    write_csv("data/containers.csv", containers, f"Update container {selected_container}")

                    if old_status != status:
                        add_log(row["container_id"], "Status changed", old_status, status)

                    st.success("Container updated.")
                    st.rerun()

            with st.expander("Danger zone"):
                if st.button("Delete selected container"):
                    containers = containers[containers["container_number"] != selected_container]
                    write_csv("data/containers.csv", containers, f"Delete container {selected_container}")
                    add_log(row["container_id"], "Container deleted", selected_container, "")
                    st.success("Container deleted.")
                    st.rerun()

    with tab2:
        st.subheader("Add Container")

        with st.form("add_container_form"):
            c1, c2, c3 = st.columns(3)
            container_number = c1.text_input("Container Number")
            invoice_number = c2.text_input("Invoice Number")
            supplier = c3.selectbox("Supplier", supplier_options if supplier_options else [""])

            c4, c5, c6 = st.columns(3)
            origin_port = c4.text_input("Origin Port")
            destination_port = c5.text_input("Destination Port")
            shipping_line = c6.text_input("Shipping Line")

            c7, c8, c9 = st.columns(3)
            weeks = week_options()
            departure_week = c7.selectbox("Departure Week", weeks, index=weeks.index(current_week_code()))
            arrival_week = c8.selectbox("Arrival Week", weeks, index=weeks.index(current_week_code()))
            eta_date = c9.date_input("ETA Date", value=date.today())

            status = st.selectbox("Status", STATUSES)
            bl_number = st.text_input("B/L Number")
            notes = st.text_area("Notes")

            add = st.form_submit_button("Add Container")

            if add:
                if not container_number.strip():
                    st.error("Container Number is required.")
                elif container_number.strip() in containers["container_number"].tolist():
                    st.error("Container Number already exists.")
                else:
                    container_id = str(uuid.uuid4())

                    new_row = {
                        "container_id": container_id,
                        "container_number": container_number.strip(),
                        "invoice_number": invoice_number.strip(),
                        "supplier": supplier,
                        "origin_port": origin_port.strip(),
                        "destination_port": destination_port.strip(),
                        "departure_week": departure_week,
                        "arrival_week": arrival_week,
                        "eta_date": str(eta_date),
                        "status": status,
                        "shipping_line": shipping_line.strip(),
                        "bl_number": bl_number.strip(),
                        "notes": notes.strip(),
                        "created_at": now_str(),
                        "updated_at": now_str(),
                    }

                    containers = pd.concat([containers, pd.DataFrame([new_row])], ignore_index=True)
                    write_csv("data/containers.csv", containers, f"Add container {container_number}")
                    add_log(container_id, "Container created", "", container_number)

                    st.success("Container added.")
                    st.rerun()


elif st.session_state.page == "Suppliers":
    st.subheader("Suppliers")

    tab1, tab2 = st.tabs(["Supplier List", "Add Supplier"])

    with tab1:
        if suppliers.empty:
            st.info("No suppliers yet.")
        else:
            st.dataframe(
                suppliers[["supplier_name", "contact_name", "email", "notes", "active"]],
                use_container_width=True,
                hide_index=True,
            )

            st.divider()
            st.subheader("Edit Supplier")

            selected_supplier = st.selectbox("Select supplier", suppliers["supplier_name"].tolist())
            row = suppliers[suppliers["supplier_name"] == selected_supplier].iloc[0]

            with st.form("edit_supplier_form"):
                contact_name = st.text_input("Contact Name", value=row["contact_name"])
                email = st.text_input("Email", value=row["email"])
                notes = st.text_area("Notes", value=row["notes"])
                active = st.checkbox("Active", value=str(row["active"]).lower() != "false")

                save_supplier = st.form_submit_button("Save Supplier")

                if save_supplier:
                    idx = suppliers[suppliers["supplier_name"] == selected_supplier].index[0]
                    suppliers.at[idx, "contact_name"] = contact_name
                    suppliers.at[idx, "email"] = email
                    suppliers.at[idx, "notes"] = notes
                    suppliers.at[idx, "active"] = str(active)
                    suppliers.at[idx, "updated_at"] = now_str()

                    write_csv("data/suppliers.csv", suppliers, f"Update supplier {selected_supplier}")
                    st.success("Supplier updated.")
                    st.rerun()

    with tab2:
        with st.form("add_supplier_form"):
            supplier_name = st.text_input("Supplier Name")
            contact_name = st.text_input("Contact Name")
            email = st.text_input("Email")
            notes = st.text_area("Notes")
            active = st.checkbox("Active", value=True)

            add_supplier = st.form_submit_button("Add Supplier")

            if add_supplier:
                if not supplier_name.strip():
                    st.error("Supplier Name is required.")
                elif supplier_name.strip() in suppliers["supplier_name"].tolist():
                    st.error("Supplier already exists.")
                else:
                    new_supplier = {
                        "supplier_id": str(uuid.uuid4()),
                        "supplier_name": supplier_name.strip(),
                        "contact_name": contact_name.strip(),
                        "email": email.strip(),
                        "notes": notes.strip(),
                        "active": str(active),
                        "created_at": now_str(),
                        "updated_at": now_str(),
                    }

                    suppliers = pd.concat([suppliers, pd.DataFrame([new_supplier])], ignore_index=True)
                    write_csv("data/suppliers.csv", suppliers, f"Add supplier {supplier_name}")
                    st.success("Supplier added.")
                    st.rerun()


elif st.session_state.page == "Logs":
    st.subheader("Container Logs")

    logs = read_csv("data/container_logs.csv", LOG_COLUMNS)

    if logs.empty:
        st.info("No logs yet.")
    else:
        st.dataframe(
            logs.sort_values("created_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
