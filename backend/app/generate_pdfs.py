"""
Generates synthetic PDF documents used by the RAG pipeline:
- SOP: room cleaning checklist
- HR policy: leave & absence policy
- Labor policy: working hours & overtime compliance
- Contract summary: agency-hotel service level agreement

Run: python -m app.generate_pdfs
"""
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Table, TableStyle
)
from reportlab.lib import colors

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")
os.makedirs(OUT_DIR, exist_ok=True)

styles = getSampleStyleSheet()
h1 = styles["Title"]
h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
body = ParagraphStyle("body", parent=styles["Normal"], spaceAfter=8, leading=15)


def _doc(filename):
    return SimpleDocTemplate(
        os.path.join(OUT_DIR, filename), pagesize=letter,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
    )


def build_sop_cleaning_checklist():
    story = [
        Paragraph("CleanSweep Facility Services", h1),
        Paragraph("Standard Operating Procedure: Guest Room Cleaning Checklist", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph("Document ID: SOP-CLN-01 &nbsp;&nbsp; Version: 3.2 &nbsp;&nbsp; Effective date: applies to all agency hotels", body),

        Paragraph("1. Purpose and scope", h2),
        Paragraph(
            "This procedure defines the minimum required steps for cleaning a guest room "
            "at any CleanSweep-managed hotel. It applies to all cleaning staff and is used "
            "by checkers as the basis for the room inspection score.", body),

        Paragraph("2. Standard cleaning sequence", h2),
        ListFlowable([
            ListItem(Paragraph("Enter room, open curtains and windows to ventilate for at least 5 minutes.", body)),
            ListItem(Paragraph("Strip and remake all bedding; bathrobe and slippers replaced if soiled.", body)),
            ListItem(Paragraph("Dust all surfaces top to bottom, including light fixtures and headboards.", body)),
            ListItem(Paragraph("Clean and disinfect bathroom: sink, toilet, shower or tub, and mirror.", body)),
            ListItem(Paragraph("Restock amenities: toiletries, coffee/tea set, drinking glasses, tissues.", body)),
            ListItem(Paragraph("Vacuum carpets or mop hard floors, working from the far corner to the door.", body)),
            ListItem(Paragraph("Empty all trash bins and replace liners.", body)),
            ListItem(Paragraph("Final walkthrough: check for stains, missed spots, or maintenance issues.", body)),
        ], bulletType="bullet"),

        Paragraph("3. Target cleaning times", h2),
        Paragraph(
            "These are guideline durations, not hard limits — quality takes priority over speed. "
            "A standard room should typically take 25-35 minutes. Deluxe rooms typically take "
            "35-45 minutes. Suites typically take 45-65 minutes due to additional living space "
            "and furnishings.", body),

        Paragraph("4. Inspection and scoring", h2),
        Paragraph(
            "Checkers inspect a sample of completed rooms daily using the standard scorecard. "
            "A room scoring 80 or above is marked pass. A room scoring below 75 is marked fail "
            "and must be re-cleaned before the room is released to housekeeping status "
            "'inspected'. Scores between 75 and 79 are logged as needs_rework at the checker's "
            "discretion.", body),

        Paragraph("5. Escalation", h2),
        Paragraph(
            "A cleaner with more than two failed inspections in a rolling 7-day window should "
            "be flagged to the hotel supervisor for a coaching conversation. Repeated failures "
            "across 3 consecutive weeks should be escalated to the head of supervisors for "
            "a formal performance review.", body),
    ]
    _doc("SOP_room_cleaning_checklist.pdf").build(story)


def build_hr_leave_policy():
    story = [
        Paragraph("CleanSweep Facility Services", h1),
        Paragraph("HR Policy: Leave and Absence Management", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph("Document ID: HR-POL-04 &nbsp;&nbsp; Version: 2.1 &nbsp;&nbsp; Applies to: all hourly cleaning and checking staff", body),

        Paragraph("1. Leave categories", h2),
        Paragraph(
            "Staff may request leave under the following categories: sick leave, personal leave, "
            "family emergency leave, and unpaid leave. Sick leave for a single day does not "
            "require a doctor's note; absences of 3 or more consecutive days require documentation.", body),

        Paragraph("2. Notice requirements", h2),
        Paragraph(
            "Personal leave must be requested at least 48 hours in advance through the "
            "supervisor. Sick leave and family emergencies may be reported on the day of "
            "absence but must be logged in the app before the end of the shift.", body),

        Paragraph("3. Approval authority", h2),
        Paragraph(
            "Hotel supervisors can approve leave requests of up to 3 consecutive days for "
            "staff at their hotel. Leave requests longer than 3 days, or any request that "
            "would leave a hotel below 80% of its rostered cleaning headcount for the day, "
            "must be escalated to the head of supervisors for approval.", body),

        Paragraph("4. Absenteeism monitoring", h2),
        Paragraph(
            "A worker with an unplanned absence rate above 8% over a rolling 30-day window "
            "is flagged automatically for supervisor review. Three or more unplanned absences "
            "in a single month should trigger a documented conversation between the supervisor "
            "and the worker.", body),

        Paragraph("5. Attendance and pay", h2),
        Paragraph(
            "Unapproved absences are unpaid and are recorded as 'absent' in the shift log. "
            "Approved sick and personal leave up to the annual allowance is paid at the "
            "worker's standard hourly rate.", body),
    ]
    _doc("HR_leave_policy.pdf").build(story)


def build_labor_hours_policy():
    story = [
        Paragraph("CleanSweep Facility Services", h1),
        Paragraph("Labor Policy: Working Hours and Overtime Compliance", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph("Document ID: LAB-POL-02 &nbsp;&nbsp; Version: 4.0 &nbsp;&nbsp; Jurisdiction: Germany (Arbeitszeitgesetz aligned)", body),

        Paragraph("1. Standard working hours", h2),
        Paragraph(
            "The standard scheduled shift is 8 hours per day, 5 days per week. Total weekly "
            "scheduled hours must not exceed 40 hours under standard rostering.", body),

        Paragraph("2. Maximum hours cap", h2),
        Paragraph(
            "In line with German labor law, no worker may exceed 10 hours of actual work in "
            "a single day, and average daily hours over any 6-month period must not exceed 8. "
            "Any shift logged above 10 actual hours in a single day is a compliance violation "
            "and must be reviewed by the head of supervisors within 48 hours.", body),

        Paragraph("3. Overtime approval", h2),
        Paragraph(
            "Overtime (any actual hours beyond the scheduled 8) must be pre-approved by the "
            "hotel supervisor except in emergency coverage situations. Overtime is paid at "
            "1.25x the standard hourly rate for the first 2 overtime hours, and 1.5x beyond that.", body),

        Paragraph("4. Rest periods", h2),
        Paragraph(
            "A minimum rest period of 11 consecutive hours is required between the end of one "
            "shift and the start of the next. Workers are entitled to a 30-minute unpaid break "
            "for shifts exceeding 6 hours, and 45 minutes for shifts exceeding 9 hours.", body),

        Paragraph("5. Weekly hours reporting", h2),
        Paragraph(
            "Each hotel supervisor must review weekly actual-hours reports every Monday for "
            "the prior week. Any worker averaging above 45 hours/week for 2 consecutive weeks "
            "should be flagged in the compliance dashboard and discussed with the head of "
            "supervisors.", body),
    ]
    _doc("Labor_hours_compliance_policy.pdf").build(story)


def build_contract_summary():
    story = [
        Paragraph("CleanSweep Facility Services", h1),
        Paragraph("Service Level Agreement Summary — Hotel Client Contracts", styles["Heading2"]),
        Spacer(1, 12),
        Paragraph("Document ID: SLA-SUM-01 &nbsp;&nbsp; Version: 1.4 &nbsp;&nbsp; Covers: Grand Meridian Hotel, Harbor View Suites, Alpine Plaza Hotel", body),

        Paragraph("1. Service scope", h2),
        Paragraph(
            "CleanSweep Facility Services provides daily housekeeping (cleaning) and quality "
            "assurance (checking) staff for guest rooms at each contracted hotel, along with "
            "an on-site supervisor per hotel and a shared head of supervisors overseeing all "
            "contracted properties.", body),

        Paragraph("2. Quality SLA targets", h2),
        Table(
            [["Metric", "Target", "Review cadence"],
             ["Room inspection pass rate", ">= 90%", "Weekly"],
             ["Same-day room cleaning completion", ">= 98%", "Daily"],
             ["Guest complaint rate re: cleanliness", "< 1.5% of stays", "Monthly"],
             ["Staff absenteeism rate", "< 8%", "Monthly"]],
            colWidths=[220, 120, 120],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C2C2A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1EFE8")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        ),
        Spacer(1, 14),

        Paragraph("3. Penalties for missed SLA targets", h2),
        Paragraph(
            "If the room inspection pass rate falls below 90% for two consecutive months at "
            "any hotel, CleanSweep issues a 2% service credit against that hotel's monthly "
            "invoice. If it falls below 80% for any single month, the hotel may request a "
            "formal corrective action plan within 10 business days.", body),

        Paragraph("4. Staffing commitments", h2),
        Paragraph(
            "CleanSweep commits to maintaining at least 90% of each hotel's rostered cleaning "
            "and checking headcount on any given day. Hotels experiencing sustained understaffing "
            "below this threshold for more than 3 consecutive days may escalate directly to the "
            "head of supervisors.", body),

        Paragraph("5. Contract review", h2),
        Paragraph(
            "Each hotel contract is reviewed annually against actual performance data, including "
            "total hours delivered, inspection pass rates, and absenteeism trends recorded in the "
            "workforce management system.", body),
    ]
    _doc("Hotel_contract_SLA_summary.pdf").build(story)


def run():
    build_sop_cleaning_checklist()
    build_hr_leave_policy()
    build_labor_hours_policy()
    build_contract_summary()
    print("Generated PDFs in", OUT_DIR)
    for f in sorted(os.listdir(OUT_DIR)):
        print(" -", f)


if __name__ == "__main__":
    run()
