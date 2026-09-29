frappe.listview_settings["Communication"] = {
	onload(listview) {
		listview.page.add_action_item(__("Run Resume Parsing"), () => {
			const checked = listview.get_checked_items() || [];
			if (!checked.length) {
				frappe.msgprint(__("Select at least one Communication."));
				return;
			}

			const names = checked.map((row) => row.name).filter(Boolean);
			if (!names.length) {
				frappe.msgprint(__("No valid Communication selected."));
				return;
			}

			frappe.confirm(
				__("Queue resume parsing for {0} selected communication(s)?", [names.length]),
				() => {
					frappe.call({
						method: "vaaman_ats_ai.api.email.fetch_resumes.enqueue_selected_email_resumes",
						args: {
							communication_names: names,
							force_reprocess: 1,
						},
						freeze: true,
						freeze_message: __("Queueing selected communications..."),
						callback: (r) => {
							const data = (r && r.message) || {};
							const queued = data.queued || 0;
							const skippedProcessing = data.skipped_processing || 0;
							const skippedProcessed = data.skipped_already_processed || 0;
							const failed = data.enqueue_errors || 0;
							const msg = __(
								"Queued: {0}<br>Already Running: {1}<br>Skipped Processed: {2}<br>Queue Errors: {3}",
								[queued, skippedProcessing, skippedProcessed, failed]
							);
							frappe.msgprint(msg);
							listview.refresh();
						},
					});
				}
			);
		});
	},
};
