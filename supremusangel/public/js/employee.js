frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Active") return;
		if (!frappe.user.has_role(["HR Manager", "HR User", "System Manager"])) return;

		frm.add_custom_button(
			__("Send Onboarding Checklist"),
			() => {
				frappe.call({
					method: "supremusangel.telegram_bots.hr_checklist.send_checklist_from_desk",
					args: { employee: frm.doc.name },
					freeze: true,
					callback: ({ message }) => {
						if (message.sent) {
							frappe.show_alert({ message: __("Checklist sent on Telegram"), indicator: "green" });
							return;
						}
						show_invite_dialog(message);
					},
				});
			},
			__("Telegram")
		);
	},
});

function show_invite_dialog(invite) {
	const d = new frappe.ui.Dialog({
		title: __("Employee has not linked the HR bot yet"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${__("Send this message to the employee. The checklist will reach them as soon as they link.")}</p>`,
			},
			{ fieldname: "text", fieldtype: "Small Text", read_only: 1, default: invite.text },
		],
		primary_action_label: invite.whatsapp_url ? __("Send on WhatsApp") : __("Copy message"),
		primary_action() {
			if (invite.whatsapp_url) {
				window.open(invite.whatsapp_url, "_blank");
			} else {
				frappe.utils.copy_to_clipboard(invite.text);
			}
			d.hide();
		},
		secondary_action_label: __("Copy message"),
		secondary_action() {
			frappe.utils.copy_to_clipboard(invite.text);
		},
	});
	d.show();
}
