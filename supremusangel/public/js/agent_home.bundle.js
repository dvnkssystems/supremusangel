/*
 * Share agents are not employees, so the ESS dashboard (which the ess app opens
 * for every non-admin user landing on Home) is empty for them. Send agents to
 * their Agent Desk workspace instead, whether they land on Home or open ESS.
 */
frappe.router.on("change", () => {
	const roles = frappe.user_roles || [];
	const is_agent =
		roles.includes("Agent") && !roles.includes("System Manager") && !roles.includes("Admin");
	if (!is_agent) return;

	const route = frappe.get_route();
	const on_home = route[0] === "Workspaces" && route[1] === "Home";
	if (on_home || route[0] === "ess") {
		frappe.set_route("app", "agent-desk");
	}
});
