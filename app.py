# Roles:
# admin    = sees everything
# handler  = dashboard only, sees all containers, can edit dashboard rows, cannot add/delete/manage
# supplier = sees, edits and deletes own containers, and can add containers

import streamlit as st
import pandas as pd
import hashlib
import uuid
import base64
import hmac
import json
import logging
import time
from html import escape
from io import StringIO, BytesIO
from datetime import datetime, date
from github import Github, GithubException, InputGitTreeElement
from requests.exceptions import ConnectionError, Timeout

st.set_page_config(page_title="Container Tracker GPC", page_icon="🚢", layout="wide")

logger = logging.getLogger(__name__)
CONTAINERS_PATH = "data/containers.csv"
LOGS_PATH = "data/container_logs.csv"
USERS_PATH = "data/users.csv"
csv_versions = {}

STATUSES = [
    "Planned", "Booked", "Departed", "On water", "Arrived at port",
    "Customs", "Released", "Delivered", "Completed", "Delayed", "Cancelled"
]

CONTAINER_COLUMNS = [
    "container_id", "container_number", "invoice_number", "supplier",
    "origin_port", "destination_port", "departure_week", "arrival_week",
    "eta_date", "status", "shipping_line", "bl_number", "booking_number",
    "notes", "shipping_cost", "tracking_status", "last_event",
    "last_location", "vessel", "voyage", "tracking_eta",
    "tracking_updated_at", "created_at", "updated_at"
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

REQUEST_COLUMNS = [
    "request_id", "supplier", "article", "quantity",
    "arrival_week_nl", "status", "created_by", "created_at", "updated_at"
]

REQUEST_STATUSES = [
    "Pending", "Confirmed", "Not Available",
    "Alternative Offered", "Completed"
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


def dataframe_to_excel(df):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Container Planning")
        ws = writer.sheets["Container Planning"]
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        widths = [22, 22, 19, 24, 78]
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width
        ws.row_dimensions[1].height = 34
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.font = Font(name="Aptos", size=12, bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center", horizontal="left", indent=1)
        for row in ws.iter_rows(min_row=2):
            row_num = row[0].row
            ws.row_dimensions[row_num].height = 29
            for cell in row:
                cell.fill = PatternFill("solid", fgColor="F0F5FA" if row_num % 2 == 0 else "FFFFFF")
                cell.font = Font(name="Aptos", size=11, color="243247")
                cell.alignment = Alignment(vertical="center", wrap_text=True, indent=1)
                cell.border = Border(bottom=Side(style="hair", color="DCE5EF"))
            notes = row[4].value
            if notes:
                ws.row_dimensions[row_num].height = min(90, max(29, 16 * (str(notes).count("\n") + 1)))
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.print_options.horizontalCentered = True
    output.seek(0)
    return output.getvalue()


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


def tracking_ready(row):
    container_no = str(row.get("container_number", "")).strip()
    bl_no = str(row.get("bl_number", "")).strip()
    booking_no = str(row.get("booking_number", "")).strip()
    return bool((container_no and container_no.upper() != "PENDING") or bl_no or booking_no)


def tracking_reference(row):
    container_no = str(row.get("container_number", "")).strip()
    bl_no = str(row.get("bl_number", "")).strip()
    booking_no = str(row.get("booking_number", "")).strip()
    if container_no and container_no.upper() != "PENDING":
        return container_no
    if bl_no:
        return bl_no
    return booking_no


@st.cache_resource
def get_repo():
    g = Github(st.secrets["GITHUB_TOKEN"])
    return g.get_repo(st.secrets["GITHUB_REPO"])


def github_branch():
    return st.secrets.get("GITHUB_BRANCH", "main")


def read_csv_version(repo, path, columns, ref, *, required=False):
    try:
        file = repo.get_contents(path, ref=ref)
    except GithubException as exc:
        if exc.status == 404 and not required:
            return pd.DataFrame(columns=columns), None
        raise

    if isinstance(file, list):
        raise ValueError(f"Expected a CSV file at {path}")
    # The contents endpoint can omit the payload for files larger than 1 MB.
    blob = repo.get_git_blob(file.sha) if file.encoding == "none" else file
    if blob.encoding != "base64":
        raise ValueError(f"Could not read CSV content at {path}")
    content = base64.b64decode("".join(blob.content.split()), validate=True).decode("utf-8-sig")
    df = pd.read_csv(StringIO(content), dtype=str, keep_default_na=False) if content.strip() else pd.DataFrame()
    if required and not set(columns).issubset(df.columns):
        raise ValueError(f"Missing required columns in {path}")
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    # Retain any additional columns already stored in GitHub.
    return df, file.sha


def read_csv(path, columns):
    df, csv_versions[path] = read_csv_version(get_repo(), path, columns, github_branch())
    return df


def write_csv(path, df, message):
    repo = get_repo()
    branch = github_branch()
    content = df.to_csv(index=False)
    sha = csv_versions[path]
    if sha is None:
        result = repo.create_file(path, message, content, branch=branch)
    else:
        result = repo.update_file(path, message, content, sha, branch=branch)
    csv_versions[path] = result["content"].sha


def log_entry(container_id, action, old_value="", new_value="", note=""):
    return {
        "log_id": str(uuid.uuid4()),
        "container_id": container_id,
        "action": action,
        "old_value": old_value,
        "new_value": new_value,
        "note": note,
        "created_at": now_str(),
    }


def add_log(container_id, action, old_value="", new_value="", note=""):
    logs = read_csv(LOGS_PATH, LOG_COLUMNS)
    logs = pd.concat([logs, pd.DataFrame([log_entry(container_id, action, old_value, new_value, note)])],
                     ignore_index=True)
    write_csv(LOGS_PATH, logs, "Update container logs")


def load_login_users():
    required_columns = ["username", "password_sha256", "role", "supplier_name", "active"]
    for attempt in range(3):
        try:
            users, _ = read_csv_version(get_repo(), USERS_PATH, required_columns, github_branch(), required=True)
            return users
        except (GithubException, ConnectionError, Timeout) as exc:
            if isinstance(exc, GithubException) and exc.status not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(0.25 * (attempt + 1))


def normalize_username(value):
    return value.strip().casefold()


def authenticate(users, username, password):
    if not username.strip() or not password:
        return None
    # Prefer an exact match to preserve legacy accounts that differ only in case.
    stored_names = users["username"].str.strip()
    matches = users[stored_names == username.strip()]
    if matches.empty:
        matches = users[stored_names.str.casefold() == normalize_username(username)]
    if len(matches) != 1:
        return None

    user = matches.iloc[0]
    role = user["role"].strip().lower()
    stored_hash = user["password_sha256"].strip().lower()
    if (
        user["active"].strip().lower() == "true"
        and role in {"admin", "handler", "supplier"}
        and (role != "supplier" or user["supplier_name"].strip())
        and stored_hash.isascii()
        and hmac.compare_digest(sha256_hash(password), stored_hash)
    ):
        return user
    return None


def login():
    if st.session_state.get("logged_in", False):
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

    with st.form("login_form", clear_on_submit=True):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        try:
            users = load_login_users()
        except Exception:
            logger.exception("Could not load the login user list")
            st.error("Login is temporarily unavailable. Please try again.")
            return False

        user = authenticate(users, username, password)
        if user is None:
            st.error("Wrong username or password")
        else:
            st.session_state.logged_in = True
            st.session_state.username = user["username"]
            st.session_state.role = user["role"].strip().lower()
            st.session_state.supplier_name = user["supplier_name"]
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    return False


if not login():
    st.stop()

role = st.session_state.role
is_admin = role == "admin"
is_handler = role == "handler"
is_supplier = role == "supplier"
user_supplier = st.session_state.supplier_name

try:
    containers = read_csv(CONTAINERS_PATH, CONTAINER_COLUMNS)
    suppliers = read_csv("data/suppliers.csv", SUPPLIER_COLUMNS)
    requests = read_csv("data/requests.csv", REQUEST_COLUMNS) if not is_handler else None
except Exception:
    logger.exception("Could not load tracker data")
    st.error("Tracker data is temporarily unavailable. Please try again.")
    st.stop()

if is_supplier:
    containers_view = containers[containers["supplier"] == user_supplier].copy()
    requests_view = requests[requests["supplier"] == user_supplier].copy()
else:
    containers_view = containers.copy()
    requests_view = requests.copy() if requests is not None else None

active_view = containers_view[~containers_view["status"].isin(["Completed", "Cancelled"])].copy()

supplier_options = suppliers[
    suppliers["active"].astype(str).str.lower() != "false"
]["supplier_name"].tolist()
supplier_options = sorted([s for s in supplier_options if s])


st.markdown(f"""
<div class="top-shell">
    <div class="app-title">Container Tracker GPC</div>
    <div class="app-subtitle">Import container overview, ETA tracking and supplier portal</div>
    <div class="user-pill">👤 {escape(st.session_state.username)} &nbsp; | &nbsp; Role: {role}</div>
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

        if nav_cols[2].button("Requests", use_container_width=True):
            st.session_state.page = "Requests"

        if nav_cols[3].button("Suppliers", use_container_width=True):
            st.session_state.page = "Suppliers"

        if nav_cols[4].button("Users", use_container_width=True):
            st.session_state.page = "Users"

        if nav_cols[5].button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    else:
        nav_cols = st.columns([1.1, 1.1, 4, 1.5])

        if nav_cols[0].button("Dashboard", use_container_width=True):
            st.session_state.page = "Dashboard"

        if nav_cols[1].button("Containers", use_container_width=True):
            st.session_state.page = "Containers"

        if nav_cols[2].button("Requests", use_container_width=True):
            st.session_state.page = "Requests"

        if nav_cols[3].button("🚪 Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

        if st.session_state.page in ["Logs", "Suppliers", "Users"]:
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


BULK_FIELDS = [
    "container_number", "invoice_number", "supplier", "origin_port", "destination_port",
    "departure_week", "arrival_week", "eta_date", "status", "shipping_line", "bl_number",
]
EDIT_FIELDS = set(BULK_FIELDS) | {"booking_number", "notes", "shipping_cost"}
TABLE_COLUMNS = BULK_FIELDS + ["notes"]
TABLE_LABELS = {
    "container_number": "Container No.",
    "invoice_number": "Invoice No.",
    "supplier": "Supplier",
    "origin_port": "Origin Port",
    "destination_port": "Destination Port",
    "departure_week": "Departure Week",
    "arrival_week": "Arrival Week",
    "eta_date": "ETA Date",
    "status": "Status",
    "shipping_line": "Shipping Line",
    "bl_number": "B/L No.",
    "notes": "Notes",
}


class ContainerChangeError(Exception):
    pass


def can_manage_container(row, *, delete=False):
    if is_admin or (is_handler and not delete):
        return True
    return is_supplier and bool(user_supplier.strip()) and row["supplier"] == user_supplier


def save_container_changes(originals, *, edits=None, delete=False):
    """Save the container and audit CSVs in the same GitHub commit."""
    if not originals:
        raise ContainerChangeError("Select at least one container.")
    repo = get_repo()
    ref = repo.get_git_ref(f"heads/{github_branch()}")
    head = ref.object.sha
    latest, _ = read_csv_version(repo, CONTAINERS_PATH, CONTAINER_COLUMNS, head)
    target_ids = [row["container_id"] for row in originals]
    targets = latest[latest["container_id"].isin(target_ids)]
    if len(targets) != len(target_ids) or not targets["container_id"].is_unique:
        raise ContainerChangeError("A selected container is missing or has a duplicate ID. Refresh the overview.")
    by_id = targets.set_index("container_id", drop=False)
    entries = []
    actor = st.session_state.username

    for original in originals:
        container_id = original["container_id"]
        current = by_id.loc[container_id]
        if not container_id or not can_manage_container(current, delete=delete):
            raise ContainerChangeError("You do not have permission to change this container.")
        if current.to_dict() != original:
            raise ContainerChangeError("A selected container has changed. Refresh the overview and try again.")

        if delete:
            entries.append(log_entry(container_id, "Container deleted", container_label(current),
                                     note=f"Deleted by {actor}"))
            continue

        fields = edits[container_id]
        if not fields.keys() <= EDIT_FIELDS:
            raise ContainerChangeError("The change includes unsupported container fields.")
        if "supplier" in fields and not is_admin:
            raise ContainerChangeError("Only an admin can change the supplier.")
        matches = latest["container_id"] == container_id
        for column, value in fields.items():
            latest.loc[matches, column] = value
        latest.loc[matches, "updated_at"] = now_str()
        if "status" in fields:
            entries.append(log_entry(container_id, "Status changed", current["status"], fields["status"],
                                     note=f"Updated by {actor}"))
        entries.append(log_entry(container_id, "Details updated", note=f"Updated by {actor}"))

    if delete:
        latest = latest[~latest["container_id"].isin(target_ids)]

    logs, _ = read_csv_version(repo, LOGS_PATH, LOG_COLUMNS, head)
    logs = pd.concat([logs, pd.DataFrame(entries)], ignore_index=True)
    parent = repo.get_git_commit(head)
    tree = repo.create_git_tree([
        InputGitTreeElement(CONTAINERS_PATH, "100644", "blob", content=latest.to_csv(index=False)),
        InputGitTreeElement(LOGS_PATH, "100644", "blob", content=logs.to_csv(index=False)),
    ], base_tree=parent.tree)
    message = "Delete selected containers" if delete else "Update selected containers"
    commit = repo.create_git_commit(message, tree, [parent])
    # A concurrent write advances the ref and makes this update non-fast-forward.
    ref.edit(commit.sha, force=False)


def submit_container_changes(originals, *, edits=None, delete=False, error_key=None):
    try:
        save_container_changes(originals, edits=edits, delete=delete)
    except ContainerChangeError as exc:
        message = str(exc)
    except Exception:
        logger.exception("Could not save container changes")
        message = "The change could not be confirmed. Refresh the overview before trying again."
    else:
        return True

    if error_key:
        st.session_state[error_key] = message
    else:
        st.error(message)
    return False


def filter_values(series):
    return sorted(set(series) - {""}, key=str.casefold)


def filter_containers(view, key):
    search = st.text_input(
        "Search containers", placeholder="Container No., Invoice No., Supplier or B/L No.",
        key=f"{key}_search",
    ).strip()
    c1, c2, c3, c4 = st.columns(4)

    def choose(column, label, values, widget_key):
        widget_key = f"{key}_{widget_key}"
        previous = st.session_state.get(widget_key)
        if previous is not None and previous not in values:
            values = values + [previous]
        return column.selectbox(
            label, [None] + values, key=widget_key,
            format_func=lambda value: "All" if value is None else value,
        )

    if is_supplier:
        c1.text_input("Supplier", value=user_supplier, disabled=True, key=f"{key}_own_supplier")
        supplier = None
    else:
        supplier = choose(c1, "Supplier", filter_values(view["supplier"]), "supplier")
    status = choose(c2, "Status", list(dict.fromkeys(STATUSES + filter_values(view["status"]))), "status")
    arrival = choose(c3, "Arrival Week", filter_values(view["arrival_week"]), "arrival")
    sort = c4.selectbox("Sort arrival week", ["Ascending", "Descending"], key=f"{key}_sort")
    return apply_container_filters(view, search, supplier, status, arrival, sort == "Ascending")


def apply_container_filters(view, search, supplier, status, arrival, ascending):
    if search:
        matches = pd.Series(False, index=view.index)
        for field in ("container_number", "invoice_number", "supplier", "bl_number"):
            matches |= view[field].str.contains(search, case=False, regex=False, na=False)
        view = view[matches]
    for field, value in (("supplier", supplier), ("status", status), ("arrival_week", arrival)):
        if value is not None:
            view = view[view[field] == value]
    return view.sort_values(["arrival_week", "eta_date", "container_id"], ascending=ascending)


def reset_container_editor(key, checked_ids=()):
    generation_key = f"{key}_selection_generation"
    st.session_state[generation_key] = st.session_state.get(generation_key, 0) + 1
    st.session_state[f"{key}_checked_ids"] = checked_ids


def finish_container_action(key, message=None):
    st.session_state.pop(f"{key}_action", None)
    if message:
        st.session_state[f"{key}_notice"] = message
        reset_container_editor(key)
    st.rerun()


def display_tracking(row):
    t1, t2, t3 = st.columns(3)
    t1.metric("Tracking Status", row["tracking_status"] or "Not synced")
    t2.metric("Live ETA", row["tracking_eta"] or "–")
    t3.metric("Last Updated", row["tracking_updated_at"] or "–")

    t4, t5 = st.columns(2)
    t4.text_input("Last Event", value=row["last_event"], disabled=True)
    t5.text_input("Last Location", value=row["last_location"], disabled=True)

    t6, t7 = st.columns(2)
    t6.text_input("Vessel", value=row["vessel"], disabled=True)
    t7.text_input("Voyage", value=row["voyage"], disabled=True)

    if tracking_ready(row):
        if st.button("Track now"):
            st.info("Tracking API is nog niet gekoppeld. Deze knop staat alvast klaar voor ShipsGo/Vizion/etc.")
    else:
        st.warning("Tracking werkt pas zodra Container Number, B/L Number of Booking Number is ingevuld.")


def render_container_edit(row, key):
    form_key = f"{key}_edit_{row['container_id']}"
    with st.form(form_key):
        general, planning = st.tabs(["General", "Notes / Cost"])
        values = {}
        with general:
            c1, c2, c3 = st.columns(3)
            values["container_number"] = c1.text_input("Container Number", row["container_number"])
            values["invoice_number"] = c2.text_input("Invoice Number", row["invoice_number"])
            if is_admin:
                names = sorted(set(supplier_options) | {row["supplier"]}, key=str.casefold)
                values["supplier"] = c3.selectbox("Supplier", names, index=names.index(row["supplier"]))
            else:
                c3.text_input("Supplier", row["supplier"], disabled=True)

            c4, c5, c6 = st.columns(3)
            values["origin_port"] = c4.text_input("Origin Port", row["origin_port"])
            values["destination_port"] = c5.text_input("Destination Port", row["destination_port"])
            values["shipping_line"] = c6.text_input("Shipping Line", row["shipping_line"])

            c7, c8, c9 = st.columns(3)
            for column, field, label in [
                (c7, "departure_week", "Departure Week"), (c8, "arrival_week", "Arrival Week"),
                (c9, "status", "Status"),
            ]:
                choices = STATUSES if field == "status" else week_options()
                choices = list(dict.fromkeys([row[field]] + choices))
                values[field] = column.selectbox(label, choices, format_func=lambda value: value or "—")

            c10, c11, c12 = st.columns(3)
            parsed_eta = pd.to_datetime(row["eta_date"], errors="coerce")
            initial_eta = None if pd.isna(parsed_eta) else parsed_eta.date()
            eta = c10.date_input("ETA Date", value=initial_eta)
            values["eta_date"] = row["eta_date"] if eta == initial_eta else str(eta or "")
            values["booking_number"] = c11.text_input("Booking Number", row["booking_number"])
            values["bl_number"] = c12.text_input("B/L Number", row["bl_number"])

        with planning:
            values["notes"] = st.text_area("Notes", value=row["notes"])
            values["shipping_cost"] = st.text_input("Shipping Cost", row["shipping_cost"])
        submitted = st.form_submit_button("Save Changes", type="primary")

    if submitted:
        if values["container_number"] != row["container_number"]:
            values["container_number"] = values["container_number"].strip() or "PENDING"
        changes = {field: value for field, value in values.items() if value != row[field]}
        if not changes:
            st.info("No changes detected.")
        elif submit_container_changes([row], edits={row["container_id"]: changes}):
            finish_container_action(key, "Container updated.")

    with st.expander("Live Tracking"):
        display_tracking(row)


def render_container_actions(selected, key):
    action_key = f"{key}_action"
    error = st.session_state.pop(f"{key}_status_error", None)
    if error:
        st.error(error)
    notice = st.session_state.pop(f"{key}_notice", None)
    if notice:
        st.success(notice)

    action = st.session_state.get(action_key)
    selected_ids = [row["container_id"] for row in selected]
    if action and [row["container_id"] for row in action[1]] != selected_ids:
        st.session_state.pop(action_key, None)
        action = None

    if action:
        mode, originals = action
        if mode == "delete":
            st.warning("Permanently delete the following container(s)?")
            for row in originals:
                st.text(container_label(row))
            cancel, confirm = st.columns(2)
            if cancel.button("Cancel", key=f"{key}_cancel_delete"):
                finish_container_action(key)
            if confirm.button("Confirm deletion", type="primary", key=f"{key}_confirm_delete"):
                if submit_container_changes(originals, delete=True):
                    count = len(originals)
                    finish_container_action(key, "Container deleted." if count == 1 else f"{count} containers deleted.")
        else:
            row = originals[0]
            st.subheader(f"Edit · {container_label(row)}")
            if st.button("Back to overview", key=f"{key}_back"):
                finish_container_action(key)
            render_container_edit(row, key)
        return

    c1, c2, c3 = st.columns([1, 1, 3])
    editable = len(selected) == 1 and can_manage_container(selected[0])
    if c1.button("Edit", type="primary", disabled=not editable, key=f"{key}_edit"):
        st.session_state[action_key] = ("edit", selected)
        st.rerun()
    if not is_handler:
        deletable = bool(selected) and all(can_manage_container(row, delete=True) for row in selected)
        if c2.button("Delete", disabled=not deletable, key=f"{key}_delete"):
            st.session_state[action_key] = ("delete", selected)
            st.rerun()

    if len(selected) == 1:
        c3.text(container_label(selected[0]))
    elif selected:
        c3.caption(f"{len(selected)} containers selected.")
    else:
        c3.caption("Select a row using the checkbox at the left of the table.")


STATUS_BY_LABEL = {status_icon(status): status for status in STATUSES}


def save_overview_statuses(key, editor_key, rows, initial_checked):
    # The widget reports positions from the table that was displayed to the user.
    edited_rows = st.session_state[editor_key]["edited_rows"]
    originals = []
    changes = {}
    for position, fields in edited_rows.items():
        if 0 <= position < len(rows):
            row = rows[position]
            status = STATUS_BY_LABEL.get(fields.get("status"))
            if status and status != row["status"]:
                originals.append(row)
                changes[row["container_id"]] = {"status": status}

    if not originals:
        return

    if submit_container_changes(originals, edits=changes, error_key=f"{key}_status_error"):
        st.session_state[f"{key}_notice"] = (
            f"Status updated to {changes[originals[0]['container_id']]['status']}."
            if len(originals) == 1 else f"Status updated for {len(originals)} containers."
        )

    checked = tuple(
        row["container_id"] for position, row in enumerate(rows)
        if edited_rows.get(position, {}).get("_checked", row["container_id"] in initial_checked)
    )
    st.session_state.pop(f"{key}_action", None)
    reset_container_editor(key, checked)


def render_container_overview(view, key):
    actions = st.container()
    filtered = filter_containers(view, key)
    selected = []
    if filtered.empty:
        st.info("No containers match your search and filters.")
    else:
        st.caption("Double-click a Status cell to change it. Changes save automatically.")
        table = filtered[TABLE_COLUMNS].reset_index(drop=True)
        table["status"] = table["status"].map(status_icon)
        rows = filtered.to_dict("records")
        signature = sha256_hash(json.dumps(rows))
        generation = st.session_state.get(f"{key}_selection_generation", 0)
        editor_key = f"{key}_rows_{generation}_{signature}"
        seed_key = f"{key}_checked_seed"
        seed_editor, initial_checked = st.session_state.get(seed_key, (None, ()))
        if seed_editor != editor_key:
            # Keep the editor's input stable while its checkbox changes are pending in the widget.
            initial_checked = st.session_state.get(f"{key}_checked_ids", ())
            st.session_state[seed_key] = editor_key, initial_checked
        table.insert(0, "_checked", filtered["container_id"].isin(initial_checked).to_numpy())
        column_config = {
            **TABLE_LABELS,
            "_checked": st.column_config.CheckboxColumn("Select", width="small", default=False),
            "status": st.column_config.SelectboxColumn("Status", options=list(STATUS_BY_LABEL), required=True),
        }
        edited = st.data_editor(
            table, use_container_width=True, hide_index=True, column_config=column_config,
            disabled=[col for col in TABLE_COLUMNS if col != "status"], key=editor_key,
            on_change=save_overview_statuses, args=(key, editor_key, rows, initial_checked),
        )
        selected = [row for row, checked in zip(rows, edited["_checked"]) if checked]
    st.session_state[f"{key}_checked_ids"] = tuple(row["container_id"] for row in selected)
    with actions:
        render_container_actions(selected, key)
    return filtered


def render_bulk_editor(filtered):
    if filtered.empty:
        return
    with st.expander("Edit multiple rows"):
        editable = filtered[filtered.apply(can_manage_container, axis=1)]
        if editable.empty:
            return
        editor_df = editable[BULK_FIELDS].reset_index(drop=True)
        editor_df["eta_date"] = pd.to_datetime(editor_df["eta_date"], errors="coerce").dt.date
        editor_df["status"] = editor_df["status"].map(clean_status)
        weeks = sorted(set(week_options()) | set(editor_df["departure_week"]) | set(editor_df["arrival_week"]))
        config = dict(TABLE_LABELS)
        config.update({
            "departure_week": st.column_config.SelectboxColumn("Departure Week", options=weeks),
            "arrival_week": st.column_config.SelectboxColumn("Arrival Week", options=weeks),
            "eta_date": st.column_config.DateColumn("ETA Date", format="YYYY-MM-DD"),
            "status": st.column_config.SelectboxColumn("Status", options=list(dict.fromkeys(STATUSES + list(editor_df["status"])))),
        })
        # Never apply a positional widget edit to a different row or newer snapshot.
        signature = sha256_hash(json.dumps(editable.to_dict("records")))
        with st.form(f"dashboard_bulk_{signature}"):
            edited = st.data_editor(editor_df, use_container_width=True, hide_index=True,
                                    disabled=["supplier", "notes"], column_config=config)
            submitted = st.form_submit_button("Save dashboard changes")

        if submitted:
            originals = []
            changes = {}
            for position, row in enumerate(editable.to_dict("records")):
                before = editor_df.iloc[position].fillna("")
                after = edited.iloc[position].fillna("")
                fields = {col: str(after[col]) for col in BULK_FIELDS if col != "supplier" and before[col] != after[col]}
                if fields:
                    originals.append(row)
                    changes[row["container_id"]] = fields
            if not changes:
                st.info("No changes detected.")
            elif submit_container_changes(originals, edits=changes):
                finish_container_action("dashboard", "Changes saved.")


if st.session_state.page == "Dashboard":
    st.subheader("Container Overview")
    include_closed = st.checkbox("Include completed and cancelled containers")
    dashboard_view = render_container_overview(containers_view if include_closed else active_view, "dashboard")
    render_bulk_editor(dashboard_view)


elif st.session_state.page == "Containers" and not is_handler:
    st.subheader("Containers")
    tab1, tab2 = st.tabs(["Overview", "Add Container"])

    with tab1:
        filtered = render_container_overview(containers_view, "containers")
        export_df = filtered[["departure_week", "arrival_week", "eta_date", "status", "notes"]].rename(
            columns=TABLE_LABELS
        )
        st.download_button(
            label="📥 Download planning as Excel",
            data=dataframe_to_excel(export_df),
            file_name=f"container_planning_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_container_planning_excel",
        )

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
            b1, b2 = st.columns(2)
            booking_number = b1.text_input("Booking Number")
            bl_number = b2.text_input("B/L Number")
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
                        "booking_number": booking_number.strip(),
                        "bl_number": bl_number.strip(),
                                                "tracking_status": "",
                        "last_event": "",
                        "last_location": "",
                        "vessel": "",
                        "voyage": "",
                        "tracking_eta": "",
                        "tracking_updated_at": "",
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


elif st.session_state.page == "Requests" and not is_handler:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Requests</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Create and follow up purchase requests.</div>', unsafe_allow_html=True)

    if is_admin:
        tab1, tab2 = st.tabs(["Request Overview", "New Request"])
    else:
        tab1, tab2 = st.tabs(["My Requests", "Update Status"])

    with tab1:
        f1, f2, f3 = st.columns(3)

        request_status_filter = f1.selectbox(
            "Status",
            ["All"] + REQUEST_STATUSES,
            key="request_status_filter"
        )

        if is_admin:
            request_supplier_filter = f2.selectbox(
                "Supplier",
                ["All"] + supplier_options,
                key="request_supplier_filter"
            )
        else:
            request_supplier_filter = user_supplier
            f2.text_input("Supplier", value=user_supplier, disabled=True)

        request_search = f3.text_input("Search article", key="request_search")

        request_table = requests_view.copy()

        if request_status_filter != "All":
            request_table = request_table[request_table["status"] == request_status_filter]

        if is_admin and request_supplier_filter != "All":
            request_table = request_table[request_table["supplier"] == request_supplier_filter]

        if request_search:
            request_table = request_table[
                request_table["article"].str.contains(request_search, case=False, na=False)
            ]

        if request_table.empty:
            st.info("No requests found.")
        else:
            request_table = request_table.sort_values(
                by=["arrival_week_nl", "created_at"],
                ascending=True
            )

            st.dataframe(
                request_table[
                    [
                        "supplier", "article", "quantity",
                        "arrival_week_nl", "status", "created_by",
                        "created_at", "updated_at"
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "supplier": "Supplier",
                    "article": "Article",
                    "quantity": "Qty",
                    "arrival_week_nl": "Arrival Week NL",
                    "status": "Status",
                    "created_by": "Created By",
                    "created_at": "Created",
                    "updated_at": "Updated",
                }
            )

    with tab2:
        if is_admin:
            with st.form("new_request_form"):
                r1, r2, r3, r4 = st.columns(4)

                request_supplier = r1.selectbox(
                    "Supplier",
                    supplier_options if supplier_options else [""],
                    key="new_request_supplier"
                )
                article = r2.text_input("Article")
                quantity = r3.text_input("Quantity")
                arrival_week_nl = r4.selectbox(
                    "Arrival Week NL",
                    week_options(),
                    index=week_options().index(current_week_code())
                )

                create_request = st.form_submit_button("Create Request")

                if create_request:
                    if not request_supplier:
                        st.error("Supplier is required.")
                    elif not article.strip():
                        st.error("Article is required.")
                    elif not quantity.strip():
                        st.error("Quantity is required.")
                    else:
                        new_request = {
                            "request_id": str(uuid.uuid4()),
                            "supplier": request_supplier,
                            "article": article.strip(),
                            "quantity": quantity.strip(),
                            "arrival_week_nl": arrival_week_nl,
                            "status": "Pending",
                            "created_by": st.session_state.username,
                            "created_at": now_str(),
                            "updated_at": now_str(),
                        }

                        requests_new = pd.concat(
                            [requests, pd.DataFrame([new_request])],
                            ignore_index=True
                        )

                        write_csv(
                            "data/requests.csv",
                            requests_new,
                            f"Add request {article.strip()}"
                        )

                        st.success("Request created.")
                        st.rerun()
        else:
            supplier_requests = requests_view.copy()

            if supplier_requests.empty:
                st.info("No requests to update.")
            else:
                supplier_requests = supplier_requests.sort_values(
                    by=["arrival_week_nl", "created_at"],
                    ascending=True
                ).reset_index(drop=True)

                selected_request_idx = st.selectbox(
                    "Select request",
                    options=list(supplier_requests.index),
                    format_func=lambda i: (
                        f"{supplier_requests.loc[i]['article']} | "
                        f"Qty: {supplier_requests.loc[i]['quantity']} | "
                        f"Week: {supplier_requests.loc[i]['arrival_week_nl']} | "
                        f"{supplier_requests.loc[i]['status']}"
                    ),
                    key="supplier_request_select"
                )

                selected_request = supplier_requests.loc[selected_request_idx]

                new_status = st.selectbox(
                    "Status",
                    REQUEST_STATUSES,
                    index=REQUEST_STATUSES.index(selected_request["status"])
                    if selected_request["status"] in REQUEST_STATUSES else 0,
                    key="supplier_request_status"
                )

                if st.button("Save request status", use_container_width=True):
                    request_idx = requests[
                        requests["request_id"] == selected_request["request_id"]
                    ].index[0]

                    old_status = requests.at[request_idx, "status"]
                    requests.at[request_idx, "status"] = new_status
                    requests.at[request_idx, "updated_at"] = now_str()

                    write_csv(
                        "data/requests.csv",
                        requests,
                        f"Update request {selected_request['article']}"
                    )

                    if old_status != new_status:
                        add_log(
                            selected_request["request_id"],
                            "Request status changed",
                            old_status,
                            new_status
                        )

                    st.success("Request status updated.")
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
    users = read_csv(USERS_PATH, USER_COLUMNS)
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
                elif normalize_username(username) in users["username"].map(normalize_username).tolist():
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
