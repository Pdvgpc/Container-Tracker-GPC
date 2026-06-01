if st.session_state.page == "Dashboard":
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Active Containers</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Live overview. Completed and cancelled containers are hidden automatically.</div>', unsafe_allow_html=True)

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

        editor_df["status"] = editor_df["status"].apply(status_icon)

        display_statuses = [status_icon(s) for s in STATUSES]

        edited = st.data_editor(
            editor_df,
            use_container_width=True,
            hide_index=True,
            disabled=["container_id", "container_number", "supplier"],
            column_config={
                "container_id": None,
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=display_statuses,
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

        edited["status"] = edited["status"].str.replace("🔴 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("🔵 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("🟠 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("🟣 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("🟢 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("✅ ", "", regex=False)
        edited["status"] = edited["status"].str.replace("⚫ ", "", regex=False)
        edited["status"] = edited["status"].str.replace("⚪ ", "", regex=False)
        edited["status"] = edited["status"].str.replace("📘 ", "", regex=False)
        edited["status"] = edited["status"].str.replace("🚢 ", "", regex=False)

        if st.button("Save dashboard changes", use_container_width=True):
            original_df = dashboard_df[editable_cols].copy()
            save_edited_containers(original_df, edited)

        if is_admin:
            st.divider()
            st.subheader("Delete container")

            delete_options = dashboard_df["container_number"].tolist()

            delete_container = st.selectbox(
                "Select container to delete",
                delete_options,
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

                    write_csv(
                        "data/containers.csv",
                        containers,
                        f"Delete container {delete_container}"
                    )

                    add_log(
                        selected_row["container_id"],
                        "Container deleted",
                        delete_container,
                        ""
                    )

                    st.success("Container deleted.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
