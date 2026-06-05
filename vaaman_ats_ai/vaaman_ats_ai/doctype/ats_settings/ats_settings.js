// Copyright (c) 2026, ajayshivhare047@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("ATS Settings", {
	refresh(frm) {
		const enabled = frm.doc.prioritize_new_emails_first;
		const btn_label = enabled
			? __("Turn OFF — parse oldest backlog first")
			: __("Turn ON — parse newest emails first");

		frm.add_custom_button(btn_label, () => {
			frm.set_value("prioritize_new_emails_first", enabled ? 0 : 1);
			frm.save();
		}).addClass(enabled ? "btn-primary" : "btn-default");
	},
});
