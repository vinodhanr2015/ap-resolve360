"""
Senthur AP Resolve360 - MVP
One user (AP executive), one problem (invoice on hold because GRN is missing),
one workflow (stuck-invoice list -> case summary -> ready reminder -> follow-up tracker), one AI capability
(summarise + classify + draft follow-up). The AI recommends; the AP executive decides.
"""

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AP Resolve360", page_icon="📋", layout="wide")

MODEL = "gemini-3.8-flash"
TODAY = date.today()

CATEGORIES = [
    "Missing GRN - material received, GRN not posted",
    "Missing GRN - material not yet received",
    "Partial receipt",
    "Quantity mismatch",
    "Price mismatch",
    "Quality inspection pending / rejected",
    "Unclear - needs AP review",
]

# Default owning function per category (rule-based, editable by the user)
DEFAULT_OWNER = {
    CATEGORIES[0]: "Stores",
    CATEGORIES[1]: "Procurement",
    CATEGORIES[2]: "Stores",
    CATEGORIES[3]: "Supplier",
    CATEGORIES[4]: "Procurement",
    CATEGORIES[5]: "Quality",
    CATEGORIES[6]: "AP Senior",
}


# ---------------------------------------------------------------- rule layer
def rule_checks(row: pd.Series) -> dict:
    """Deterministic facts computed from the ERP export. The AI never changes these."""
    inv_date = pd.to_datetime(row["invoice_date"]).date()
    due_date = pd.to_datetime(row["due_date"]).date()
    grn_qty = 0 if pd.isna(row["grn_qty"]) else float(row["grn_qty"])
    flags = []
    if grn_qty == 0:
        flags.append("No GRN quantity posted in ERP")
    elif grn_qty < float(row["invoice_qty"]):
        flags.append(f"GRN qty {grn_qty:g} < invoice qty {float(row['invoice_qty']):g}")
    if float(row["invoice_rate"]) != float(row["po_rate"]):
        flags.append(f"Invoice rate {row['invoice_rate']} vs PO rate {row['po_rate']}")
    if float(row["invoice_qty"]) > float(row["po_qty"]):
        flags.append("Invoice qty exceeds PO qty")
    if str(row.get("quality_status", "")).strip().lower() in ("pending", "rejected"):
        flags.append(f"Quality status: {row['quality_status']}")
    age = (TODAY - inv_date).days
    days_to_due = (due_date - TODAY).days
    critical = str(row.get("supplier_critical", "No")).strip().lower() == "yes"
    # Risk-based priority: due date first, then supplier criticality (R6 closing, R8 and R12 P2-Q12)
    if days_to_due <= 3 or (critical and days_to_due <= 7):
        priority = "High"
    elif days_to_due <= 7 or critical:
        priority = "Medium"
    else:
        priority = "Normal"
    return {
        "ageing_days": age,
        "days_to_due": days_to_due,
        "priority": priority,
        "flags": flags,
        "critical": critical,
        "next_reminder": str(TODAY + timedelta(days=1 if priority == "High" else 2)),
    }


# ------------------------------------------------------------------ AI layer
def build_prompt(case: dict, checks: dict, email_trail: str) -> str:
    return f"""You are an assistant to an Accounts Payable (AP) executive in an Indian
manufacturing company. An invoice is on hold because the three-way match (PO, GRN,
invoice) failed. Help the AP executive resolve it faster. You only RECOMMEND. You must
never approve invoices, release holds, post entries, or change amounts, terms or bank details.

Case fields from the ERP export (treat as facts, do not alter numbers):
{json.dumps(case, default=str, indent=2)}

Rule-check results (facts):
{json.dumps(checks, indent=2)}

Email / Teams trail pasted by the AP executive (may be empty):
\"\"\"{email_trail.strip() or "(none)"}\"\"\"

Tasks:
1. Classify the root cause as exactly one of: {json.dumps(CATEGORIES)}.
   If the trail and the fields conflict or are insufficient, choose "Unclear - needs AP review".
2. Write a 2-3 sentence plain-English case summary.
3. List the documents/confirmations still missing before AP can process the invoice.
4. Suggest which function should act next (Stores, Procurement, Quality, Supplier, Business owner, AP Senior)
   with confidence High/Medium/Low and a one-line reason.
5. Count the previous follow-ups visible in the trail. ESCALATION RULE: if previous
   follow-ups are 3 or more, OR days_to_due is 3 or less, OR critical is true and previous
   follow-ups are 2 or more, write the message as a polite
   escalation addressed to the head of that function (copying the original contact),
   stating the follow-up history factually without blaming anyone. Otherwise write a
   normal follow-up to the owner.
6. Draft the message (max 130 words) in a professional, polite, non-blaming tone. Include invoice
   no, PO no, supplier, material description, expected quantity, GRN status, a one-line history
   of previous follow-ups (dates), the due date and the exact action requested. Make it easy for the recipient to answer in one line: end
   the message with a "Quick reply" block exactly like:
   Quick reply: Received qty ___ | GRN no. ___ | Date ___  OR  Not yet received / Quality hold
7. List which input fields or trail lines you relied on.

Return ONLY JSON with keys:
category, summary, missing_items (list), suggested_owner, confidence, owner_reason,
previous_follow_ups (integer), escalate (true/false), draft_subject, draft_body,
evidence_used (list).
"""


def escalation_needed(prev_follow_ups: int, days_to_due: int, critical: bool = False) -> bool:
    """Rule check that mirrors the AI instruction, so the escalation flag never depends on the AI alone.
    Escalate after 3 follow-ups or when due within 3 days (R6, R7 P2-Q12); one step earlier for a
    critical production supplier (R8, R12 P2-Q12)."""
    return prev_follow_ups >= 3 or days_to_due <= 3 or (critical and prev_follow_ups >= 2)


def call_gemini(prompt: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2, response_mime_type="application/json"
        ),
    )
    return json.loads(resp.text)


# ------------------------------------------------------------------------ UI
if "log" not in st.session_state:
    st.session_state.log = []

st.title("📋 AP Resolve360")
st.caption(
    "Clear invoices stuck because the GRN (Goods Receipt Note) is missing. "
    "AI suggests the cause, who to contact and a ready reminder; **AP decides and sends**."
)

with st.sidebar:
    st.header("1 · Load ERP report")
    up = st.file_uploader("Stuck invoices (spreadsheet export, .csv)", type="csv")
    st.caption("Columns: invoice_no, supplier, po_no, item, po_qty, invoice_qty, grn_qty, "
               "po_rate, invoice_rate, invoice_date, due_date, quality_status, "
               "stores_contact, procurement_contact, quality_contact, supplier_contact; "
               "optional: invoice_value, supplier_critical (Yes/No), *_head contacts")
    use_sample = st.checkbox("Use sample data", value=up is None)
    st.divider()
    st.markdown("**Guardrail**  \nThis tool never approves invoices, releases holds, "
                "posts entries or changes amounts, terms or bank details.")

if up is not None and not use_sample:
    df = pd.read_csv(up)
else:
    df = pd.read_csv("sample_erp_export.csv")

# Hold queue with rule checks
queue = df.copy()
checks_all = queue.apply(rule_checks, axis=1)
queue["ageing_days"] = [c["ageing_days"] for c in checks_all]
queue["days_to_due"] = [c["days_to_due"] for c in checks_all]
queue["priority"] = [c["priority"] for c in checks_all]
queue["_rank"] = queue["priority"].map({"High": 0, "Medium": 1, "Normal": 2})
queue["issue_flags"] = ["; ".join(c["flags"]) for c in checks_all]
queue = queue.sort_values(["_rank", "days_to_due"])

st.subheader("Stuck-invoice list (urgent first)")
LABELS = {"invoice_no": "Invoice", "supplier": "Supplier", "po_no": "PO", "invoice_value": "Value (₹)",
          "supplier_critical": "Key supplier", "invoice_qty": "Invoice qty", "grn_qty": "GRN qty",
          "ageing_days": "Days pending", "days_to_due": "Days to due date", "priority": "Urgency",
          "issue_flags": "Problem flagged"}
st.dataframe(
    queue[[c for c in LABELS if c in queue.columns]].rename(columns=LABELS),
    hide_index=True, width="stretch",
)

st.subheader("2 · Choose a stuck invoice")
inv = st.selectbox("Invoice", queue["invoice_no"].tolist())
row = df[df["invoice_no"] == inv].iloc[0]
checks = rule_checks(row)
email_trail = st.text_area(
    "Paste the email history for this invoice (optional, but improves the result)",
    height=150,
    value=open("sample_email_trail.txt").read() if (use_sample and inv == "INV-1023") else "",
)

if st.button("Build case summary", type="primary"):
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("Add GEMINI_API_KEY in Streamlit secrets to enable the AI step.")
    else:
        with st.spinner("Reading the case..."):
            try:
                case = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
                st.session_state.result = call_gemini(build_prompt(case, checks, email_trail))
                st.session_state.result_inv = inv
            except Exception as e:  # show a readable error instead of a stack trace
                st.error(f"AI step failed: {e}")

res = st.session_state.get("result")
if res and st.session_state.get("result_inv") == inv:
    st.subheader("3 · Case summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Days pending", f"{checks['ageing_days']} days")
    c2.metric("Due in", f"{checks['days_to_due']} days")
    c3.metric("Urgency", checks["priority"])
    prev = int(res.get("previous_follow_ups", 0) or 0)
    c4.metric("Reminders so far", prev)
    escalate = escalation_needed(prev, checks["days_to_due"], checks["critical"])
    if escalate:
        st.warning(f"⚠️ Escalation alert: {prev} reminders so far, due in "
                   f"{checks['days_to_due']} days. The draft is addressed to the function head, "
                   "copying the original contact. You decide whether to escalate.")

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Likely cause (AI suggestion):** {res.get('category')}")
        st.write(res.get("summary", ""))
        st.markdown("**What is missing:**")
        for m in res.get("missing_items", []):
            st.checkbox(m, key=f"miss-{inv}-{m}")
        st.markdown("**Problems flagged (from the ERP report):**")
        for f in checks["flags"] or ["No rule flags"]:
            st.markdown(f"- {f}")
    with right:
        owners = ["Stores", "Procurement", "Quality", "Supplier", "Business owner", "AP Senior"]
        sugg = res.get("suggested_owner", DEFAULT_OWNER.get(res.get("category"), "Stores"))
        st.markdown(f"**Who to contact (AI suggestion):** {sugg} · confidence **{res.get('confidence')}**")
        st.caption(res.get("owner_reason", ""))
        owner = st.selectbox("Confirm who to contact (you decide)", owners,
                             index=owners.index(sugg) if sugg in owners else 0)
        contact_col = {"Stores": "stores_contact", "Procurement": "procurement_contact",
                       "Quality": "quality_contact", "Supplier": "supplier_contact"}.get(owner)
        contact = row.get(contact_col, "") if contact_col else ""
        st.text_input("Send to", value="" if pd.isna(contact) else str(contact))
        if escalate:
            head_col = {"Stores": "stores_head", "Procurement": "procurement_head",
                        "Quality": "quality_head"}.get(owner)
            head = row.get(head_col, "") if head_col else ""
            st.text_input("Escalate to (function head)", value="" if pd.isna(head) else str(head))
        with st.expander("Evidence the AI used"):
            for e in res.get("evidence_used", []):
                st.markdown(f"- {e}")

    st.subheader("4 · Ready reminder (check before sending)")
    subj = st.text_input("Subject", value=res.get("draft_subject", ""))
    body = st.text_area("Message (edit if needed)", value=res.get("draft_body", ""), height=200)
    if st.button("✅ I checked this - add to tracker"):
        st.session_state.log.append({
            "logged_on": str(TODAY), "invoice_no": inv, "owner": owner,
            "ai_category": res.get("category"), "ai_owner": sugg,
            "owner_overridden": owner != sugg, "escalated": escalate,
            "follow_ups_before": prev,
            "draft_edited": body.strip() != res.get("draft_body", "").strip(),
            "subject": subj, "next_reminder": checks["next_reminder"],
        })
        st.success(f"Added to tracker. Next reminder: {checks['next_reminder']}. "
                   "Copy the message into Outlook/Teams to send.")

if st.session_state.log:
    st.subheader("5 · Follow-up tracker")
    log_df = pd.DataFrame(st.session_state.log)
    st.dataframe(log_df.rename(columns={
        "logged_on": "Date", "invoice_no": "Invoice", "owner": "Contacted", "ai_category": "AI cause",
        "ai_owner": "AI suggested", "owner_overridden": "Person changed", "escalated": "Escalated",
        "follow_ups_before": "Reminders before", "draft_edited": "Reminder edited",
        "subject": "Subject", "next_reminder": "Next reminder"}), hide_index=True, width="stretch")
    st.markdown("**Test results (for user testing)**")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cases tracked", len(log_df))
    m2.metric("Reminders sent without edits", f"{(~log_df['draft_edited']).mean():.0%}")
    m3.metric("AI suggestion accepted", f"{(~log_df['owner_overridden']).mean():.0%}")
    m4.metric("Avg reminders before tool", f"{log_df['follow_ups_before'].mean():.1f}")
    st.download_button("Download tracker (.csv)", log_df.to_csv(index=False),
                       "followup_log.csv", "text/csv")
