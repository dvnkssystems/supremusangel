# Feature: Supremus Telegram Bots (HR, CRM, Customer Onboarding)

Status: design approved 2026-09-16. Target: production site `portal.supremusangel.com`.

## 1. Goal

Give Supremus Angel's internal team three Telegram bots that drive day-to-day workflows from inside Telegram, with ERPNext as the system of record:

| Bot | Username | Users |
|---|---|---|
| Supremus HR Bot | `@supremus_hr_bot` | New employees, HR |
| Supremus CRM Bot | `@supremus_crm_bot` | Tele Caller, Relationship Manager, Team Lead, Branch Manager |
| Supremus Customer Onboarding Bot | `@supremus_customer_onboarding_bot` | Relationship Managers only (not customers) |

Bot tokens live in the `Telegram Settings` doctype of `erpnext_telegram_integration` (records named as in the table). They are never committed to git.

## 2. Existing data this builds on (verified on production)

- Roles: `Tele Caller`, `Relationship Manager`, `Wealth Relationship Manager`, `Team Lead`, `Branch Manager`, `HR Manager`, `HR User`, `Share Transfer Team`, `KYC Verification User`.
- Lead: `custom_rm` (Employee), `custom_telecaller_user` (User), `custom_branch`, `custom_branch_manager` (User), `custom_next_follow_up_date`, `custom_telecalling_status` (Open / Interested / Meeting / Not Interested / DND / Cancelled), `custom_contact_log` (`Lead Contact Log`). `rm_performance/lead_hooks.py` mirrors the latest contact-log row onto the Lead.
- `Meeting` (supremus_angel): `meeting_with` + `meeting_party`, `meeting_type` (Offline/Online), `status`, `host` (User), `meeting_attendee` table, `meeting_start_time`, `meeting_end_time`, `meeting_url`, `meeting_venue`.
- `Meeting Room Booking` (scope_connect): `assigned_rm`, `start_datetime`, `end_datetime`, `status`.
- Employee: workflow **Employee Profile Review** (Pending → Under Review → Profile Completed) on `custom_profile_status`; `custom_onboarding_completed`; `reports_to`, `branch`, `department`, `designation`, `cell_number`, `personal_email`, `user_id`.
- `Company Policy` (`mandatory_for_new_joinee`, `active`, `policy_content`, `policy_pdf`) and `Company Policy Acknowledgement` (`user`, `employee`, `policy`, `acknowledged_on`, `user_agent`, `ip_address`).
- Customer: `custom_kyc_status` (Pending / In Progress / Verified / Rejected), KYC attach fields (`custom_pan_card_image`, `custom_aadhaar_front_image`, `custom_aadhaar_back_image`, `custom_passbook_cheque_image`), `custom_relationship_manager`, `custom_branch`.
- Workflows: **Payment Verification** (Payment Entry: Pending → Approved/Rejected), **SA Share Purchase Approval** (Sales Invoice: Draft → Pending Approval → Approved/Rejected/Cancelled). Notification **SA Shares Transferred** (Sales Invoice) marks the transfer step.

## 3. Architecture

New module `telegram_bots` inside the `supremusangel` app.

```
Telegram ──HTTPS webhook──▶ /api/method/supremusangel.telegram_bots.api.webhook?bot=<key>
                               │  verify X-Telegram-Bot-Api-Secret-Token
                               │  store raw update, return 200 immediately
                               ▼
                         frappe.enqueue(short) ─▶ router ─▶ bot handler (hr / crm / onboarding)
                                                             │  session (flow, step, data)
                                                             │  permission check as linked User
                                                             ▼
                                                   ERPNext docs  +  outbound via tg client
ERPNext doc_events / scheduler ─▶ notifier ─▶ tg client ─▶ Telegram
```

- `tg.py`: thin synchronous client over the Bot API using `requests` (sendMessage, editMessageText, answerCallbackQuery, sendDocument, getFile, setWebhook, createChatInviteLink). No `python-telegram-bot` async code in workers.
- Bot keys: `hr`, `crm`, `onboarding`, mapped to `Telegram Settings` names in `Supremus Bot Settings`.
- Webhook secret: random per-bot secret stored (password field) in `Supremus Bot Settings`; setup command `bench --site <site> execute supremusangel.telegram_bots.setup.set_webhooks`.
- Callback data format: `<action>:<id>[:<arg>]`, max 64 bytes.
- Every handler executes with `frappe.set_user(linked_user)` so standard permissions apply (a telecaller only sees leads they can read; a BM only their branch).
- Idempotency: `update_id` stored on `Telegram Message Log` with a unique constraint; duplicates are dropped.

### 3.1 New doctypes

| Doctype | Purpose | Key fields |
|---|---|---|
| `Supremus Bot Settings` (single) | Configuration | bot → Telegram Settings mapping + webhook secrets; working days (Mon–Sat), day start 10:00, day end 19:00, slot minutes 60; stall days (KYC, purchase, share transfer — all 3); BM escalation hours 2; policy reminder days 2; child table `Telegram Group Access` (chat id, title, department / designation / branch filters); child table `Employee KYC Document Type` |
| `Telegram Link` | Telegram identity ↔ ERP user | bot, user, employee, telegram_user_id, chat_id, username, linked_on, link_method (Phone / Invite), enabled; unique (bot, telegram_user_id) |
| `Telegram Invite` | One-time deep-link codes | bot, code (unique), user, employee, customer_onboarding_request, expires_on, used_on |
| `Telegram Session` | Conversation state | bot, chat_id, flow, step, data (JSON), modified; one per (bot, chat_id) |
| `Telegram Message Log` | Audit trail | bot, direction (In/Out), chat_id, update_id, message_id, text, reference_doctype, reference_name, relay_to_message_id |
| `Employee KYC Document` (child of Employee, via custom field `custom_kyc_documents`) | Per-document status | document_type, file, status (Pending / Submitted / Approved / Rejected), rejection_reason, reviewed_by, reviewed_on |
| `Customer Onboarding Request` | CRM → Onboarding hand-off and pipeline anchor | lead, customer, rm (Employee), rm_user, branch, status (Open / Customer Created / Completed / Cancelled), current_stage, stage_since, last_digest_on |

### 3.2 Custom fields / changes to existing doctypes

- `Meeting`: `custom_lead` (Link Lead), `custom_rm` (Link Employee), `custom_requested_by` (Link User), `custom_rejection_reason` (Small Text), `custom_reassigned_by` (Link User), `custom_reminder_sent` (Check); add statuses `Pending RM Acceptance`, `Rejected by RM` via Property Setter on `status`.
- `Employee`: `custom_kyc_documents` (Table Employee KYC Document), `custom_hr_contact` (Link User — defaults to Employee creator if HR role).
- `Company Policy Acknowledgement`: rows created by the bot set `user_agent = "Telegram:<bot>"`.

All custom fields and property setters ship as fixtures filtered by `module = "Telegram Bots"`.

## 4. Linking a Telegram user

Two methods; both create a `Telegram Link` and a matching stock `Telegram User Settings` (party User, chat id filled) so standard `Telegram Notification` records keep working.

1. **Share phone number (self-service, internal staff).** On `/start` with no link the bot replies with a reply-keyboard button **📱 Share my phone number** (`request_contact: true`). On the contact message the bot checks `contact.user_id == from.id` (it must be the sender's own number), normalises to the last 10 digits, and matches an active `Employee.cell_number` with a `user_id`, or `User.mobile_no`. Exactly one match → linked. Zero or many → "Ask HR to send you an invite link."
2. **Invite link (HR-driven, required for new joiners).** Button **Send Telegram Invite** on Employee (HR Manager / HR User) creates a `Telegram Invite` (7-day expiry) and emails `personal_email` (and shows copyable link) `https://t.me/supremus_hr_bot?start=<code>`. Opening it links immediately. The CRM → Onboarding hand-off uses the same mechanism with `start=cob_<code>`.

Access control per bot: HR bot — any linked employee; CRM bot — user must hold Tele Caller, Relationship Manager, Wealth Relationship Manager, Team Lead or Branch Manager; Onboarding bot — Relationship Manager, Wealth Relationship Manager, Team Lead or Branch Manager. Disabled Employees/Users are unlinked by a daily job.

## 5. HR bot

Trigger: Employee `after_insert` / `on_update` with status Active and `custom_onboarding_completed = 0` → HR sees the Send Telegram Invite button (not auto-sent, HR controls timing).

Flow after link:
1. **Welcome** — name, designation, department, branch, date of joining.
2. **KYC collection** — iterate `Employee KYC Document Type` rows (seeded: Aadhaar Front, Aadhaar Back, PAN Card, Passport Photo, Cancelled Cheque / Passbook, Education Certificates, Last Relieving Letter — the last two allow "Not applicable"). Photo or PDF accepted; saved as private File attached to Employee; row → Submitted. When all mandatory rows are Submitted, workflow state → Under Review (via `apply_workflow` as Administrator) and HR contact notified with per-document ✅ Approve / ❌ Reject buttons. Reject asks HR for a reason, employee receives it and is asked to re-upload that document. HR may also review from the Employee form; the same `on_update` notifier fires.
3. **HR ↔ Employee channel** — any free text/file from the employee outside a flow is forwarded to `custom_hr_contact` (via HR bot) prefixed with employee name and added as a Comment on Employee. HR replies using Telegram *Reply* on that forwarded message; the bot relays it to the employee (`relay_to_message_id` in the log). HR can also start a thread with `/msg <employee id>`.
4. **Orientation & hierarchy** — `Meeting` insert/update where an attendee or `meeting_party` is the Employee → message with title, time, online link or venue, plus reporting chain (`reports_to` walk up to 3 levels), department and branch. Reminder 1 hour before.
5. **KYC complete** — Employee workflow reaches Profile Completed → notify employee.
6. **Job responsibilities** — `Designation.description` sent after welcome. Designations with empty description are listed to HR on the first run.
7. **Channel access** — for each `Telegram Group Access` row matching the employee, bot calls `createChatInviteLink(member_limit=1, expire 7 days)` and sends it. Bot must be admin in each group; rows where it is not are reported to HR. (Group list to be filled by HR in settings — none configured at launch.)
8. **Policies** — for each active `mandatory_for_new_joinee` Company Policy without acknowledgement: send title + plain-text summary (first 800 chars of `policy_content`) + PDF if present, with button **I Agree to <policy title>**. Tap → `Company Policy Acknowledgement` insert. Telegram gives bots no read receipts, so the agreement tap is the recorded receipt. Daily job reminds employee after 2 days and HR after 4.
9. When KYC is Profile Completed and all policies acknowledged → set `custom_onboarding_completed = 1`, congratulate employee, notify HR.

## 6. CRM bot

Commands (also exposed as a persistent menu): `/today`, `/lead <name or phone>`, `/slots`, `/book`, `/meetings`.

- **Lead assignment notifications** (Lead `on_update`, `has_value_changed`): `custom_rm` → RM; `custom_telecaller_user` → telecaller; `custom_branch` / `custom_branch_manager` → BM. Message includes lead name, phone, source, status and buttons (Open card, Log call).
- **Daily follow-ups** (scheduler 09:30 IST, Mon–Sat): per linked user, leads visible to them with `custom_next_follow_up_date <= today` and status not in Not Interested / DND / Cancelled / Converted; capped at 20 with count of remainder.
- **Lead card / updates**: buttons Log call (mode → outcome → next follow-up date → remark; appends `Lead Contact Log` row), Set status, Book meeting, Start customer onboarding.
- **Calendar**: `Meeting` is the calendar. Free slots for RM on a date = working hours (Mon–Sat 10:00–19:00, 60-min slots) minus Meetings where RM user is host or attendee with status Scheduled / Pending RM Acceptance, minus `Meeting Room Booking` with `assigned_rm` = RM (not cancelled), minus approved Leave Application days, minus Holiday List dates of the RM's Employee. Past slots on today excluded. Visible RMs: Branch Manager / Team Lead → active RMs in same branch; Tele Caller → RMs in the lead's branch (or own branch); RM → self.
- **Booking** (Tele Caller, TL, BM): lead → RM (default `Lead.custom_rm`) → date (next 7 working days) → free slot → Online (paste link) / Offline (venue, default "Office – <branch>") → confirm. Creates Meeting: `meeting_with = Lead`, host = RM user, status Pending RM Acceptance, `custom_requested_by`. RM receives ✅ Accept / ❌ Reject.
  - Accept → status Scheduled, Lead `custom_telecalling_status = Meeting`, requester notified. RM morning agenda at 09:00 and reminder 1 h before (`custom_reminder_sent`).
  - Reject → bot requires a reason (min 10 characters) → status Rejected by RM, `custom_rejection_reason` → requester + BM (`Lead.custom_branch_manager`, else Branch Manager users of the RM's branch) notified with **Reassign to RM** (lists RMs free in that slot) or **Attend myself**. Either choice → new host, status Pending RM Acceptance (reassign) or Scheduled (BM self), `custom_reassigned_by`; parties notified. No BM action within 2 h → reminder.
  - Slot re-checked at confirm time to prevent double booking.
- **Customer onboarding request**: from the lead card (RM/TL/BM) → creates `Customer Onboarding Request` (Open) + `Telegram Invite` → RM receives button opening `t.me/supremus_customer_onboarding_bot?start=cob_<code>`.

## 7. Customer Onboarding bot (RMs only)

- **Entry via CRM**: `start=cob_<code>` loads the request; prefilled from Lead (name, mobile, email, branch). RM confirms or edits, adds PAN.
- **Entry directly**: `/new` asks name → mobile → email → PAN → branch (RM's branch default) → confirm; creates a Lead if none matches the mobile, then the request.
- On confirm: Customer created from Lead (ERPNext `make_customer` mapping) with `custom_kyc_status = Pending`, `custom_relationship_manager`, `custom_branch`; existing **User Creation** notification gives portal access. Optional uploads of PAN / Aadhaar front/back / cheque into the Customer attach fields.
- **Stages**, computed live from source documents (no mirrored status beyond `current_stage` + `stage_since` for stall timing):
  1. Customer Created
  2. KYC Verified — `custom_kyc_status = Verified`
  3. Purchase Started — Sales Order or Sales Invoice for the customer (not cancelled)
  4. Payment Approved — Payment Entry for the customer in workflow state Approved
  5. Purchase Approved — Sales Invoice workflow state Approved
  6. Shares Transferred — same condition as the SA Shares Transferred notification
- **Event notifications**: doc_events on Customer, Sales Order, Sales Invoice, Payment Entry recompute the stage for open requests of that customer; any change → RM notified; stage 1 reached → "Customer onboarded".
- **Daily digest** 10:00 IST to each RM: open requests with stage and days in stage.
- **Stalled** (all thresholds 3 days, configurable): KYC not verified 3 days after Customer Created; no purchase 3 days after KYC Verified; shares not transferred 3 days after Payment Approved (also notify Share Transfer Team users linked to the CRM bot or HR bot). Stalled items are flagged ⚠️ in the digest and pushed once per day.
- `/pipeline` lists the RM's open requests on demand.

## 8. Error handling

- Webhook never raises to Telegram: exceptions logged to Error Log with update id; user gets "Something went wrong, please try again or contact admin."
- Telegram API 403 (user blocked bot) → `Telegram Link.enabled = 0`.
- 429 → retry once honouring `retry_after`, then Error Log.
- Session expiry: 30 minutes idle → session cleared; `/cancel` clears any time.
- Outbound notifications are enqueued (`enqueue_after_commit=True`) so doc saves never fail because of Telegram.

## 9. Testing

`FrappeTestCase` tests with `tg` client mocked:
- phone normalisation + link matching (one / zero / many)
- slot calculation (meetings, room bookings, leave, holiday, past slots)
- booking accept / reject / reassign state transitions and notifications
- stage computation for each pipeline stage and stall detection
- HR KYC flow step transitions and policy acknowledgement creation
- callback-data permission checks (user cannot act on another RM's meeting)

Production verification: pilot with 1 BM, 2 RMs, 1 Tele Caller, 1 HR user before announcing to all staff.

## 10. Deployment

Development happens on a feature branch of `supremusangel`, merged to `develop` and pulled on production (the prod bench tracks `develop`). Per deploy: `bench --site portal.supremusangel.com backup` → `git pull` → `bench --site portal.supremusangel.com migrate` → `bench build --app supremusangel` → restart web/workers → `set_webhooks` (first deploy only).

## 11. Open items

- Telegram groups for new-joiner access: not yet provided (the value given was the HR bot itself, which is not a group). HR adds rows to `Telegram Group Access` later.
- Designations with empty `description` need responsibilities text from HR.
- Bot tokens were shared in chat; rotate via @BotFather after go-live and update `Telegram Settings`.
