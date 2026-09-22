// Shows the derived Incentive Role (RM / TL / BM) on the Sales Person form.
//
// The role is computed from the tree position on every load (never stored by
// hand, so it can't go stale). Wired via `doctype_js` in supremusangel/hooks.py.

frappe.ui.form.on("Sales Person", {
	refresh(frm) {
		if (frm.is_new()) return;

		frappe.call({
			method: "supremusangel.supremus_angel.sales_person_create.get_incentive_role",
			args: { sales_person: frm.doc.name },
			callback(r) {
				if (!r.message) return;
				const label = r.message.label || "";
				// Set without dirtying the form (read-only, display-only value).
				if (frm.doc.custom_incentive_role !== label) {
					frm.doc.custom_incentive_role = label;
					frm.refresh_field("custom_incentive_role");
				}
				const tone = { SA: "blue", TL: "green", BM: "orange" }[r.message.role] || "gray";
				frm.dashboard.add_indicator(__("Incentive Role: {0}", [label]), tone);
			},
		});
	},
});

// Direct Sales price ladder: an agent sets the price they charge their downline for
// each deal they sell under a direct sales rate (see unlisted_shares/direct_ladder.py).
frappe.ui.form.on("Sales Person", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.custom_tier) return;
		frm.add_custom_button(__("Direct Sales Prices"), () => show_downline_prices(frm));
	},
});

function show_downline_prices(frm) {
	const method = "supremusangel.unlisted_shares.direct_ladder.";
	frappe.call({
		method: method + "get_downline_prices",
		args: { sales_person: frm.doc.name },
		callback(r) {
			const data = r.message || {};
			if (!(data.deals || []).length) {
				frappe.msgprint(__("No direct sales rate covers this agent yet."));
				return;
			}
			// The dialog grid edits data.deals in place, so keep the saved prices aside.
			const saved = Object.fromEntries(data.deals.map((m) => [m.deal, flt(m.downline_price)]));
			const d = new frappe.ui.Dialog({
				title: __("Direct Sales Prices"),
				size: "large",
				fields: [
					{
						fieldtype: "HTML",
						options: data.has_downline
							? `<p class="text-muted">${__("Set what your downline pays. It must be between your buy price and the maximum selling rate.")}</p>`
							: `<p class="text-muted">${__("This agent has no downline, so only the buy price applies.")}</p>`,
					},
					{
						fieldname: "rows",
						fieldtype: "Table",
						cannot_add_rows: true,
						cannot_delete_rows: true,
						in_place_edit: true,
						data: data.deals,
						fields: [
							{ fieldname: "deal", label: __("Deal"), fieldtype: "Data", read_only: 1, in_list_view: 1 },
							{ fieldname: "sales_partner", label: __("Sales Partner"), fieldtype: "Data", read_only: 1, in_list_view: 1 },
							{ fieldname: "buy_price", label: __("Your Buy Price"), fieldtype: "Currency", read_only: 1, in_list_view: 1 },
							{ fieldname: "maximum_selling_rate", label: __("Max Rate"), fieldtype: "Currency", read_only: 1, in_list_view: 1 },
							{ fieldname: "downline_price", label: __("Downline Price"), fieldtype: "Currency", in_list_view: 1, read_only: !data.has_downline },
						],
					},
					{
						// Each saved Downline Price is an Item Price row with Agent = this agent.
						fieldname: "item_price_link",
						fieldtype: "HTML",
						options: `<a href="#" class="small">${__("View these prices in Item Price")} →</a>`,
					},
				],
				primary_action_label: data.has_downline ? __("Save Prices") : __("Close"),
				async primary_action() {
					if (!data.has_downline) return d.hide();
					// A grid cell only commits its value on blur, so commit the one still being
					// edited before reading the rows.
					document.activeElement && document.activeElement.blur();
					await new Promise((resolve) => setTimeout(resolve, 300));
					const changed = d.fields_dict.rows.grid
						.get_data()
						.filter((row) => flt(row.downline_price) && flt(row.downline_price) !== saved[row.deal]);
					if (!changed.length) {
						frappe.show_alert({ message: __("No price changes to save"), indicator: "orange" });
						return;
					}
					Promise.all(
						changed.map((row) =>
							frappe.call({
								method: method + "set_downline_price",
								args: { item_code: row.deal, price: row.downline_price, sales_person: frm.doc.name },
							})
						)
					).then(() => {
						d.hide();
						frappe.show_alert({ message: __("Prices saved"), indicator: "green" });
					});
				},
			});
			d.fields_dict.item_price_link.$wrapper.find("a").on("click", (e) => {
				e.preventDefault();
				d.hide();
				// Frappe turns "=" on a tree Link (Sales Person) into "descendants of", which would also
				// list the downline's prices; "in" with just this agent keeps it to their own rows.
				frappe.set_route("List", "Item Price", { custom_agent: ["in", [data.agent]] });
			});
			d.show();
		},
	});
}
