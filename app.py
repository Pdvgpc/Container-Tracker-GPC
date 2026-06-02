# Roles:
# admin    = sees everything
# handler  = dashboard only, sees all containers, can edit dashboard rows, cannot add/delete/manage
# supplier = sees only own supplier containers, can edit own rows and add own containers

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
    "shipping_cost", "created_at", "updated_at"
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

st.markdown("""
<style>
.stApp {
    background: linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%);
    color: #111827;
}
.block-container {
    padding-top: 3.8rem;
    padding-bottom: 3rem;
    max-width: 1500px;
}
.top-shell {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
    padding: 30px 30px;
    border-radius: 22px;
    color: white;
    box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22);
    margin-top: 8px;
    margin-bottom: 20px;
}
.app-title {
    font-size: 34px;
    font-weight: 800;
    letter-spacing: -0.04em;
    margin-bottom: 4px;
}
.app-subtitle {
    font-size: 14px;
    opacity: 0.82;
}
.user-pill {
    display: inline-block;
    background: rgba(255,255,255,0.13);
    border: 1px solid rgba(255,255,255,0.25);
    padding: 8px 13px;
    border-radius: 999px;
    font-size: 13px;
    margin-top: 14px;
}
div.stButton > button {
    border-radius: 999px;
    border: 1px solid #d1d5db;
    background: white;
    color: #111827;
    font-weight: 650;
    height: 42px;
    box-shadow: 0 3px 10px rgba(15, 23, 42, 0.05);
}
div.stButton > button:hover {
    border-color: #2563eb;
    color: #1d4ed8;
    background: #eff6ff;
}
.metric-card {
    background: white;
    padding: 22px 22px;
    border-radius: 20px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
}
.metric-label {
    color: #6b7280;
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.metric-value {
    margin-top: 8px;
    font-size: 34px;
    font-weight: 850;
    color: #111827;
    letter-spacing: -0.04em;
}
.section-card {
    background: white;
    border-radius: 22px;
    padding: 24px;
    border: 1px solid #e5e7eb;
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
    margin-top: 16px;
}
.section-title {
    font-size: 22px;
    font-weight: 800;
    color: #111827;
    letter-spacing: -0.03em;
    margin-bottom: 4px;
}
.section-subtitle {
    color: #6b7280;
    font-size: 14px;
    margin-bottom: 18px;
}
div[data-testid="stDataFrame"] {
    border-radius: 18px;
    overflow: hidden;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}
.stTabs [data-baseweb="tab"] {
    background: #f3f4f6;
    border-radius: 999px;
    padding: 8px 18px;
    font-weight: 700;
}
.stTabs [aria-selected="true"] {
    background: #dbeafe;
    color: #1d4ed8;
}
</style>
""", unsafe_allow_html=True)


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


def status_icon(status):
    icons = {
        "Delayed": "🔴",
        "On water": "🔵",
        "Arrived at port": "🟠",
        "Customs": "🟣",
        "Released": "🟢",
        "Delivered": "✅",
        "Completed": "✅",
        "Cancelled": "⚫",
        "Planned": "⚪",
        "Booked": "📘",
        "Departed": "🚢",
    }
    return f"{icons.get(status, '⚪')} {status}"


def clean_status(value):
    value = str(value)
    for icon in ["🔴 ", "🔵 ", "🟠 ", "🟣 ", "🟢 ", "✅ ", "⚫ ", "⚪ ", "📘 ", "🚢 "]:
        value = value.replace(icon, "")
    return value


def container_label(row):
    container_no = str(row.get("container_number", "")).strip() or "PENDING"
    invoice_no = str(row.get("invoice_number", "")).strip()
    supplier = str(row.get("supplier", "")).strip()
    parts = [container_no]
    if invoice_no:
        parts.append(f"Inv: {invoice_no}")
    if supplier:
        parts.append(supplier)
    return " | ".join(parts)


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

    st.markdown("""
    <div class="top-shell">
        <div class="app-title">Container Tracker GPC</div>
        <div class="app-subtitle">Secure container tracking portal</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Login</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Enter your username and password.</div>', unsafe_allow_html=True)

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login", use_container_width=True):
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

    st.markdown('</div>', unsafe_allow_html=True)
    return False


if not login():
    st.stop()


containers = read_csv("data/containers.csv", CONTAINER_COLUMNS)
suppliers = read_csv("data/suppliers.csv", SUPPLIER_COLUMNS)
users = read_csv("data/users.csv", USER_COLUMNS)

role = st.session_state.role
is_admin = role == "admin"
is_handler = role == "handler"
is_supplier = role == "supplier"
user_supplier = st.session_state.supplier_name

if is_supplier:
    containers_view = containers[containers["supplier"] == user_supplier].copy()
else:
    containers_view = containers.copy()

active_view = containers_view[~containers_view["status"].isin(["Completed", "Cancelled"])].copy()

supplier_options = suppliers[
    suppliers["active"].astype(str).str.lower() != "false"
]["supplier_name"].tolist()
supplier_options = sorted([s for s in supplier_options if s])


st.markdown(f"""
<div class="top-shell">
    <div class="app-title">Container Tracker GPC</div>
    <div class="app-subtitle">Import container overview, ETA tracking and supplier portal</div>
    <div class="user-pill">👤 {st.session_state.username} &nbsp; | &nbsp; Role: {role}</div>
</div>
""", unsafe_allow_html=True)

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if is_handler:
    nav_cols = st.columns([1.2, 4, 1.5])
    if nav_cols[0].button("Dashboard", use_container_width=True):
        st.session_state.page = "Dashboard"
    if nav_cols[2].button("🚪 Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.session_state.page = "Dashboard"
else:
    if is_admin:
        nav_cols = st.columns([1.1, 1.1, 1.1, 1.1, 1.1, 2.2])

        if nav_cols[0].button("Dashboard", use_container_width=True):
            st.session_state.page = "Dashboard"

        if nav_cols[1].button("Containers", use_container_width=True):
            st.session_state.page = "Containers"

        if nav_cols[2].button("Suppliers", use_container_width=True):
            st.session_state.page = "Suppliers"

        if nav_cols[3].button("Users", use_container_width=True):
            st.session_state.page = "Users"

        if nav_cols[4].button("Logs", use_container_width=True):
            st.session_state.page = "Logs"

        if nav_cols[5].button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    else:
        nav_cols = st.columns([1.1, 1.1, 4, 1.5])

        if nav_cols[0].button("Dashboard", use_container_width=True):
            st.session_state.page = "Dashboard"

        if nav_cols[1].button("Containers", use_container_width=True):
            st.session_state.page = "Containers"

        if nav_cols[3].button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

        if st.session_state.page == "Logs":
            st.session_state.page = "Dashboard"


total = len(active_view)
on_water = len(active_view[active_view["status"] == "On water"])
arriving_this_week = len(active_view[active_view["arrival_week"] == current_week_code()])
delayed = len(active_view[active_view["status"] == "Delayed"])

k1, k2, k3, k4 = st.columns(4)

with k1:
    st.markdown(f'<div class="metric-card"><div class="metric-label">Active Containers</div><div class="metric-value">{total}</div></div>', unsafe_allow_html=True)
with k2:
    st.markdown(f'<div class="metric-card"><div class="metric-label">On Water</div><div class="metric-value">{on_water}</div></div>', unsafe_allow_html=True)
with k3:
    st.markdown(f'<div class="metric-card"><div class="metric-label">Arriving This Week</div><div class="metric-value">{arriving_this_week}</div></div>', unsafe_allow_html=True)
with k4:
    st.markdown(f'<div class="metric-card"><div class="metric-label">Delayed</div><div class="metric-value">{delayed}</div></div>', unsafe_allow_html=True)


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
            "container_number", "invoice_number", "origin_port", "destination_port",
            "departure_week", "arrival_week", "eta_date", "status",
            "shipping_line", "bl_number"
        ]

        for col in editable_columns:
            old = "" if pd.isna(original_row[col]) else str(original_row[col])
            new = "" if pd.isna(edited_row[col]) else str(edited_row[col])

            if col == "eta_date" and new:
                new = str(pd.to_datetime(new).date())

            if col == "status":
                new = clean_status(new)

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
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Active Containers</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Completed and cancelled containers are hidden automatically.</div>', unsafe_allow_html=True)

    f1, f2, f3, f4 = st.columns(4)

    search = f1.text_input("Search")
    status_filter = f2.selectbox("Status", ["All"] + STATUSES)
    week_sort = f3.selectbox("Sort arrival week", ["Ascending", "Descending"])

    if is_admin or is_handler:
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

    if (is_admin or is_handler) and supplier_filter != "All":
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
            "eta_date", "status", "shipping_line", "bl_number"
        ]

        editor_df = dashboard_df[editable_cols].copy()
        editor_df["eta_date"] = pd.to_datetime(editor_df["eta_date"], errors="coerce").dt.date
        editor_df["status"] = editor_df["status"].apply(status_icon)
        display_statuses = [status_icon(s) for s in STATUSES]

        edited = st.data_editor(
            editor_df,
            use_container_width=True,
            hide_index=True,
            disabled=["container_id", "supplier"],
            column_config={
                "container_id": None,
                "container_number": st.column_config.TextColumn("Cont No."),
                "invoice_number": st.column_config.TextColumn("Inv No."),
                "supplier": st.column_config.TextColumn("Suppl"),
                "origin_port": st.column_config.TextColumn("Origin Port"),
                "destination_port": st.column_config.TextColumn("Destination Port"),
                "departure_week": st.column_config.SelectboxColumn("Departure WK", options=week_options(), required=True),
                "arrival_week": st.column_config.SelectboxColumn("Arrival WK", options=week_options(), required=True),
                "eta_date": st.column_config.DateColumn("ETA Date", format="YYYY-MM-DD"),
                "status": st.column_config.SelectboxColumn("Status", options=display_statuses, required=True),
                "shipping_line": st.column_config.TextColumn("Shipper"),
                "bl_number": st.column_config.TextColumn("B/L No."),
            },
            key="dashboard_editor",
        )

        edited["status"] = edited["status"].apply(clean_status)

        if st.button("Save dashboard changes", use_container_width=True):
            original_df = dashboard_df[editable_cols].copy()
            save_edited_containers(original_df, edited)

        st.divider()
        st.subheader("Open container details")

        detail_options = dashboard_df.apply(container_label, axis=1).tolist()
        detail_map = dict(zip(detail_options, dashboard_df["container_id"].tolist()))

        selected_detail = st.selectbox(
            "Select container",
            detail_options,
            key="dashboard_detail_select"
        )

        detail_id = detail_map[selected_detail]
        detail_row = containers[containers["container_id"] == detail_id].iloc[0]

        d1, d2 = st.columns(2)

        with d1:
            st.markdown("#### Notes")
            detail_notes = st.text_area(
                "Notes",
                value=detail_row.get("notes", ""),
                height=180,
                key=f"notes_{detail_id}"
            )

        with d2:
            st.markdown("#### Shipping Cost")
            detail_shipping_cost = st.text_input(
                "Shipping Cost",
                value=detail_row.get("shipping_cost", ""),
                key=f"shipping_cost_{detail_id}"
            )

        if st.button("Save details", use_container_width=True):
            idx = containers[containers["container_id"] == detail_id].index[0]
            containers.at[idx, "notes"] = detail_notes.strip()
            containers.at[idx, "shipping_cost"] = detail_shipping_cost.strip()
            containers.at[idx, "updated_at"] = now_str()

            write_csv("data/containers.csv", containers, f"Update details {detail_row.get('container_number', '')}")
            add_log(detail_id, "Details updated", "", "", "Notes / shipping cost updated")
            st.success("Details saved.")
            st.rerun()

        if is_admin or is_supplier:
            st.divider()
            st.subheader("Delete container")

            delete_container = st.selectbox(
                "Select container to delete",
                dashboard_df["container_number"].tolist(),
                key="dashboard_delete_select"
            )

            confirm_delete = st.checkbox(
                f"I confirm deleting container {delete_container}",
                key="dashboard_delete_confirm"
            )

            if st.button("Delete selected container", use_container_width=True):
                if not confirm_delete:
                    st.error("Please confirm before deleting.")
                else:
                    selected_row = dashboard_df[
                        dashboard_df["container_number"] == delete_container
                    ].iloc[0]

                    containers = read_csv("data/containers.csv", CONTAINER_COLUMNS)
                    containers = containers[
                        containers["container_id"] != selected_row["container_id"]
                    ]

                    write_csv("data/containers.csv", containers, f"Delete container {delete_container}")
                    add_log(selected_row["container_id"], "Container deleted", delete_container, "")

                    st.success("Container deleted.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


elif st.session_state.page == "Containers" and not is_handler:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Containers</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Create, review and update import containers.</div>', unsafe_allow_html=True)

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

        filtered = filtered.sort_values(by=["arrival_week", "eta_date"], ascending=(sort_order == "Ascending"))

        table_df = filtered[
            [
                "container_number", "invoice_number", "supplier",
                "origin_port", "destination_port", "departure_week",
                "arrival_week", "eta_date", "status",
                "shipping_line", "bl_number", "notes"
            ]
        ].copy()

        table_df["status"] = table_df["status"].apply(status_icon)

        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "container_number": "Container No.",
                "invoice_number": "Invoice No.",
                "origin_port": "Origin Port",
                "destination_port": "Destination Port",
                "departure_week": "Departure Week",
                "arrival_week": "Arrival Week",
                "eta_date": "ETA Date",
                "shipping_line": "Shipping Line",
                "bl_number": "B/L No.",
            }
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

            row = containers_view[containers_view["container_number"] == selected_container].iloc[0]

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
                    supplier = user_supplier
                    c2.text_input("Supplier", value=user_supplier, disabled=True)

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
                shipping_cost = st.text_input("Shipping Cost", value=row.get("shipping_cost", ""))
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
                    containers.at[idx, "shipping_cost"] = shipping_cost
                    containers.at[idx, "updated_at"] = now_str()

                    write_csv("data/containers.csv", containers, f"Update container {selected_container}")

                    if old_status != status:
                        add_log(row["container_id"], "Status changed", old_status, status)

                    st.success("Container updated.")
                    st.rerun()

    with tab2:
        with st.form("add_container_form"):
            c1, c2, c3 = st.columns(3)

            container_number = c1.text_input("Container Number")
            invoice_number = c2.text_input("Invoice Number")

            if is_admin:
                supplier = c3.selectbox("Supplier", supplier_options if supplier_options else [""])
            else:
                supplier = user_supplier
                c3.text_input("Supplier", value=user_supplier, disabled=True)

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
            shipping_cost = st.text_input("Shipping Cost")
            notes = st.text_area("Notes")

            add = st.form_submit_button("Add Container")

            if add:
                clean_container_number = container_number.strip() if container_number.strip() else "PENDING"

                if (
                    clean_container_number != "PENDING"
                    and clean_container_number in containers["container_number"].tolist()
                ):
                    st.error("Container Number already exists.")
                elif not supplier:
                    st.error("Supplier is required.")
                else:
                    container_id = str(uuid.uuid4())

                    new_row = {
                        "container_id": container_id,
                        "container_number": clean_container_number,
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
                        "shipping_cost": shipping_cost.strip(),
                        "created_at": now_str(),
                        "updated_at": now_str(),
                    }

                    containers = pd.concat([containers, pd.DataFrame([new_row])], ignore_index=True)

                    write_csv("data/containers.csv", containers, f"Add container {clean_container_number}")
                    add_log(container_id, "Container created", "", clean_container_number)

                    st.success("Container added.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


elif st.session_state.page == "Suppliers" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Suppliers</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Manage suppliers.</div>', unsafe_allow_html=True)

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

    st.markdown('</div>', unsafe_allow_html=True)


elif st.session_state.page == "Users" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Users</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Create admin, handler or supplier users.</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["User List", "Add User"])

    with tab1:
        st.dataframe(
            users[["username", "role", "supplier_name", "active", "created_at", "updated_at"]],
            use_container_width=True,
            hide_index=True,
        )

    with tab2:
        with st.form("add_user_form"):
            username = st.text_input("Username")
            password = st.text_input("Temporary Password", type="password")
            role_input = st.selectbox("Role", ["admin", "handler", "supplier"])
            supplier_name = st.selectbox("Supplier", [""] + supplier_options)
            active = st.checkbox("Active", value=True)

            add_user = st.form_submit_button("Add User")

            if add_user:
                if not username.strip() or not password:
                    st.error("Username and password are required.")
                elif username.strip() in users["username"].tolist():
                    st.error("Username already exists.")
                elif role_input == "supplier" and not supplier_name:
                    st.error("Supplier user must be linked to a supplier.")
                elif role_input in ["admin", "handler"] and supplier_name:
                    st.error("Admin/handler user should not be linked to a supplier.")
                else:
                    new_user = {
                        "user_id": str(uuid.uuid4()),
                        "username": username.strip(),
                        "password_sha256": sha256_hash(password),
                        "role": role_input,
                        "supplier_name": supplier_name,
                        "active": str(active),
                        "created_at": now_str(),
                        "updated_at": now_str(),
                    }

                    users = pd.concat([users, pd.DataFrame([new_user])], ignore_index=True)
                    write_csv("data/users.csv", users, f"Add user {username}")
                    st.success("User added.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


elif st.session_state.page == "Logs" and is_admin:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Container Logs</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Audit trail for container status changes and edits.</div>', unsafe_allow_html=True)

    logs = read_csv("data/container_logs.csv", LOG_COLUMNS)

    if logs.empty:
        st.info("No logs yet.")
    else:
        st.dataframe(
            logs.sort_values("created_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)
