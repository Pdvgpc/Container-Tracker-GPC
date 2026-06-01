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

USER_COLUMNS = [
    "user_id", "username", "password_sha256", "role",
    "supplier_name", "active", "created_at", "updated_at"
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


def login():
    users = read_csv("data/users.csv", USER_COLUMNS)

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if st.session_state.logged_in:
        return True

    st.title("Container Tracker GPC")
    st.subheader("Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        match = users[
            (users["username"] == username.strip())
            & (users["active"].astype(str).str.lower() == "true")
        ]

        if match.empty:
            st.error("Wrong username or password")
            return False

        user = match.iloc[0]

        if sha256_hash(password) == user["password_sha256"]:
            st.session_state.logged_in = True
            st.session_state.username = user["username"]
            st.session_state.role = user["role"]
            st.session_state.supplier_name = user["supplier_name"]
            st.rerun()
        else:
            st.error("Wrong username or password")

    return False


if not login():
    st.stop()


containers = read_csv("data/containers.csv", CONTAINER_COLUMNS)
suppliers = read_csv("data/suppliers.csv", SUPPLIER_COLUMNS)
users = read_csv("data/users.csv", USER_COLUMNS)

is_admin = st.session_state.role == "admin"
user_supplier = st.session_state.supplier_name

if not is_admin:
    containers_view = containers[containers["supplier"] == user_supplier].copy()
else:
    containers_view = containers.copy()

active_view = containers_view[
    ~containers_view["status"].isin(["Completed", "Cancelled"])
].copy()

supplier_options = suppliers[
    suppliers["active"].astype(str).str.lower() != "false"
]["supplier_name"].tolist()

supplier_options = sorted([s for s in supplier_options if s])


st.markdown("# Container Tracker GPC")

nav_cols = st.columns([1.2, 1.2, 1.2, 1.2, 1.2, 2])

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if nav_cols[0].button("Dashboard", use_container_width=True):
    st.session_state.page = "Dashboard"

if nav_cols[1].button("Containers", use_container_width=True):
    st.session_state.page = "Containers"

if is_admin:
    if nav_cols[2].button("Suppliers", use_container_width=True):
        st.session_state.page = "Suppliers"

    if nav_cols[3].button("Users", use_container_width=True):
        st.session_state.page = "Users"

if nav_cols[4].button("Logs", use_container_width=True):
    st.session_state.page = "Logs"

if nav_cols[5].button("🚪 Logout", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.caption(f"👤 {st.session_state.username} | Role: {st.session_state.role}")

st.divider()


total = len(active_view)
on_water = len(active_view[active_view["status"] == "On water"])
arriving_this_week = len(active_view[active_view["arrival_week"] == current_week_code()])
delayed = len(active_view[active_view["status"] == "Delayed"])

k1, k2, k3, k4 = st.columns(4)
k1.metric("Active Containers", total)
k2.metric("On Water", on_water)
k3.metric("Arriving This Week", arriving_this_week)
k4.metric("Delayed", delayed)

st.divider()


def save_edited_containers(original_df, edited_df):
    global containers

    changes = 0

    for _, edited_row in edited_df.iterrows():
        cid = edited_row["container_id"]

        original_row = original_df[original_df["container_id"] == cid]

        if original_row.empty:
            continue

        original_row = original_row.iloc[0]
        main_idx = containers[containers["container_id"] == cid].index

        if len(main_idx) == 0:
            continue

        main_idx = main_idx[0]

        editable_columns = [
            "invoice_number", "origin_port", "destination_port",
            "departure_week", "arrival_week", "eta_date", "status",
            "shipping_line", "bl_number", "notes"
        ]

        for col in editable_columns:
            old = "" if pd.isna(original_row[col]) else str(original_row[col])
            new = "" if pd.isna(edited_row[col]) else str(edited_row[col])

            if col == "eta_date" and new:
                new = str(pd.to_datetime(new).date())

            if old != new:
                containers.at[main_idx, col] = new
                containers.at[main_idx, "updated_at"] = now_str()
                changes += 1

                if col == "status":
                    add_log(cid, "Status changed", old, new)

    if changes > 0:
        write_csv("data/containers.csv", containers, "Update containers from dashboard")
        st.success("Changes saved.")
        st.rerun()
    else:
        st.info("No changes detected.")


if st.session_state.page == "Dashboard":
    st.subheader("Active Containers")

    f1, f2, f3, f4 = st.columns(4)

    search = f1.text_input("Search")
    status_filter = f2.selectbox("Status", ["All"] + STATUSES)
    week_sort = f3.selectbox("Sort arrival week", ["Ascending", "Descending"])

    if is_admin:
        supplier_filter = f4.selectbox("Supplier", ["All"] + supplier_options)
    else:
        supplier_filter = user_supplier
        f4.text_input("Supplier", value=user_supplier, disabled=True)

    dashboard_df = active_view.copy()

    if search:
        dashboard_df = dashboard_df[
            dashboard_df["container_number"].str.contains(search, case=False, na=False)
            | dashboard_df["invoice_number"].str.contains(search, case=False, na=False)
            | dashboard_df["bl_number"].str.contains(search, case=False, na=False)
        ]

    if status_filter != "All":
        dashboard_df = dashboard_df[dashboard_df["status"] == status_filter]

    if is_admin and supplier_filter != "All":
        dashboard_df = dashboard_df[dashboard_df["supplier"] == supplier_filter]

    dashboard_df = dashboard_df.sort_values(
        by=["arrival_week", "eta_date"],
        ascending=(week_sort == "Ascending")
    )

    if dashboard_df.empty:
        st.info("No active containers.")
    else:
        editable_cols = [
            "container_id", "container_number", "invoice_number", "supplier",
            "origin_port", "destination_port", "departure_week", "arrival_week",
            "eta_date", "status", "shipping_line", "bl_number", "notes"
        ]

        editor_df = dashboard_df[editable_cols].copy()

        editor_df["eta_date"] = pd.to_datetime(
            editor_df["eta_date"],
            errors="coerce"
        ).dt.date

        edited = st.data_editor(
            editor_df,
            use_container_width=True,
            hide_index=True,
            disabled=["container_id", "container_number", "supplier"],
            column_config={
                "container_id": None,
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=STATUSES,
                    required=True
                ),
                "departure_week": st.column_config.SelectboxColumn(
                    "Departure Week",
                    options=week_options(),
                    required=True
                ),
                "arrival_week": st.column_config.SelectboxColumn(
                    "Arrival Week",
                    options=week_options(),
                    required=True
                ),
                "eta_date": st.column_config.DateColumn(
                    "ETA Date",
                    format="YYYY-MM-DD"
                ),
            },
            key="dashboard_editor",
        )

        if st.button("Save dashboard changes"):
            original_df = dashboard_df[editable_cols].copy()
            save_edited_containers(original_df, edited)


elif st.session_state.page == "Containers":
    st.subheader("Containers")

    tab1, tab2 = st.tabs(["Overview / Edit", "Add Container"])

    with tab1:
        f1, f2, f3, f4 = st.columns(4)

        search = f1.text_input("Search container / invoice / B/L")
        status_filter = f2.selectbox("Status", ["All"] + STATUSES)
        arrival_filter = f3.selectbox("Arrival Week", ["All"] + week_options())
        sort_order = f4.selectbox("Sort arrival week", ["Ascending", "Descending"])

        filtered = containers_view.copy()

        if search:
            filtered = filtered[
                filtered["container_number"].str.contains(search, case=False, na=False)
                | filtered["invoice_number"].str.contains(search, case=False, na=False)
                | filtered["bl_number"].str.contains(search, case=False, na=False)
            ]

        if status_filter != "All":
            filtered = filtered[filtered["status"] == status_filter]

        if arrival_filter != "All":
            filtered = filtered[filtered["arrival_week"] == arrival_filter]

        filtered = filtered.sort_values(
            by=["arrival_week", "eta_date"],
            ascending=(sort_order == "Ascending")
        )

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

        if containers_view.empty:
            st.info("No containers to edit.")
        else:
            selected_container = st.selectbox(
                "Select container",
                containers_view["container_number"].tolist(),
            )

            row = containers_view[
                containers_view["container_number"] == selected_container
            ].iloc[0]

            with st.form("edit_container_form"):
                c1, c2, c3 = st.columns(3)

                invoice_number = c1.text_input("Invoice Number", value=row["invoice_number"])

                if is_admin:
                    supplier = c2.selectbox(
                        "Supplier",
                        supplier_options if supplier_options else [row["supplier"]],
                        index=supplier_options.index(row["supplier"]) if row["supplier"] in supplier_options else 0,
                    )
                else:
                    supplier = row["supplier"]
                    c2.text_input("Supplier", value=supplier, disabled=True)

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

                eta_value = date.today()
                if row["eta_date"]:
                    parsed_eta = pd.to_datetime(row["eta_date"], errors="coerce")
                    if not pd.isna(parsed_eta):
                        eta_value = parsed_eta.date()

                eta_date = c9.date_input("ETA Date", value=eta_value)

                bl_number = st.text_input("B/L Number", value=row["bl_number"])
                notes = st.text_area("Notes", value=row["notes"])

                save = st.form_submit_button("Save Changes")

                if save:
                    idx = containers[containers["container_id"] == row["container_id"]].index[0]
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

            if is_admin:
                with st.expander("Danger zone"):
                    if st.button("Delete selected container"):
                        containers = containers[
                            containers["container_id"] != row["container_id"]
                        ]
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

            if is_admin:
                supplier = c3.selectbox("Supplier", supplier_options if supplier_options else [""])
            else:
                supplier = user_supplier
                c3.text_input("Supplier", value=supplier, disabled=True)

            c4, c5, c6 = st.columns(3)

            origin_port = c4.text_input("Origin Port")
            destination_port = c5.text_input("Destination Port")
            shipping_line = c6.text_input("Shipping Line")

            c7, c8, c9 = st.columns(3)

            weeks = week_options()
            departure_week = c7.selectbox(
                "Departure Week",
                weeks,
                index=weeks.index(current_week_code())
            )

            arrival_week = c8.selectbox(
                "Arrival Week",
                weeks,
                index=weeks.index(current_week_code())
            )

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
                elif not supplier:
                    st.error("Supplier is required.")
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

                    containers = pd.concat(
                        [containers, pd.DataFrame([new_row])],
                        ignore_index=True
                    )

                    write_csv("data/containers.csv", containers, f"Add container {container_number}")
                    add_log(container_id, "Container created", "", container_number)

                    st.success("Container added.")
                    st.rerun()


elif st.session_state.page == "Suppliers" and is_admin:
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

            selected_supplier = st.selectbox(
                "Select supplier",
                suppliers["supplier_name"].tolist()
            )

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

                    suppliers = pd.concat(
                        [suppliers, pd.DataFrame([new_supplier])],
                        ignore_index=True
                    )

                    write_csv("data/suppliers.csv", suppliers, f"Add supplier {supplier_name}")
                    st.success("Supplier added.")
                    st.rerun()


elif st.session_state.page == "Users" and is_admin:
    st.subheader("Users")

    tab1, tab2 = st.tabs(["User List", "Add User"])

    with tab1:
        if users.empty:
            st.info("No users yet.")
        else:
            st.dataframe(
                users[["username", "role", "supplier_name", "active", "created_at", "updated_at"]],
                use_container_width=True,
                hide_index=True,
            )

    with tab2:
        with st.form("add_user_form"):
            username = st.text_input("Username")
            password = st.text_input("Temporary Password", type="password")
            role = st.selectbox("Role", ["admin", "supplier"])
            supplier_name = st.selectbox("Supplier", [""] + supplier_options)
            active = st.checkbox("Active", value=True)

            add_user = st.form_submit_button("Add User")

            if add_user:
                if not username.strip() or not password:
                    st.error("Username and password are required.")
                elif username.strip() in users["username"].tolist():
                    st.error("Username already exists.")
                elif role == "supplier" and not supplier_name:
                    st.error("Supplier user must be linked to a supplier.")
                else:
                    new_user = {
                        "user_id": str(uuid.uuid4()),
                        "username": username.strip(),
                        "password_sha256": sha256_hash(password),
                        "role": role,
                        "supplier_name": supplier_name,
                        "active": str(active),
                        "created_at": now_str(),
                        "updated_at": now_str(),
                    }

                    users = pd.concat(
                        [users, pd.DataFrame([new_user])],
                        ignore_index=True
                    )

                    write_csv("data/users.csv", users, f"Add user {username}")
                    st.success("User added.")
                    st.rerun()


elif st.session_state.page == "Logs":
    st.subheader("Container Logs")

    logs = read_csv("data/container_logs.csv", LOG_COLUMNS)

    if not is_admin:
        allowed_ids = containers_view["container_id"].tolist()
        logs = logs[logs["container_id"].isin(allowed_ids)]

    if logs.empty:
        st.info("No logs yet.")
    else:
        st.dataframe(
            logs.sort_values("created_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
