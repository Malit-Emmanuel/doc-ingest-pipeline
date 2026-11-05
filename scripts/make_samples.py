"""Generate the sample corpus in samples/ (fictional organisation, fake personal data).

Run: python scripts/make_samples.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"

RETENTION = """Data Retention Guideline

Mwangaza Savings Bank is a fictional institution used for demonstration only.

Purpose
This guideline sets out how long customer records are kept and how they are disposed of. Records are kept only for as long as they are needed for the purpose they were collected for, or for as long as the law requires.

Retention periods
Account opening documents are kept for seven years after the account is closed. Transaction records are kept for seven years from the date of the transaction. Marketing consent records are kept for as long as the consent is valid and for two years after it is withdrawn. Call recordings are kept for ninety days unless they are linked to a complaint, in which case they are kept until the complaint is resolved and for one year after.

Disposal
When a retention period ends, records are deleted from production systems within thirty days and from backups within the next backup cycle. Paper records are shredded on site. Every disposal is logged with the record type, the date and the officer responsible.

Exceptions
A legal hold suspends disposal. The Legal department records each hold and releases it in writing. Records under a legal hold must not be altered or deleted.

Review
The Data Protection Officer reviews this guideline every year and after any change in the law.
"""

ONBOARDING = """# Customer Onboarding Policy

Mwangaza Savings Bank is a fictional institution used for demonstration only.

## Know your customer

Every new customer must provide a valid national identity card or passport, a KRA PIN certificate and proof of address dated within the last three months. Relationship officers verify documents against the original before the account is opened.

## Worked example

The example below shows the information captured during onboarding. All details are fake.

Customer: Jane Wanjiru, email jane.wanjiru@example.com, phone +254 712 345 678, ID No: 23456789, KRA PIN A012345678Z. Her debit card was issued as 4111 1111 1111 1111.

## Risk rating

Customers are rated low, medium or high risk. High-risk customers, including politically exposed persons, need approval from the branch manager and enhanced due diligence before activation. Ratings are reviewed every year, or sooner if the customer's activity changes significantly.

## Consent

Customers must give separate, explicit consent for marketing messages. Consent is recorded with a timestamp and the channel used, and can be withdrawn at any time through any branch, the mobile app or the contact centre on 0722 000 111.
"""

FAQ_PAGES = [
    [
        "What is the Jenga Biashara loan?",
        "The Jenga Biashara loan is a working-capital loan for small businesses that have",
        "traded for at least twelve months. Amounts range from fifty thousand to two",
        "million shillings, repayable over three to twenty-four months.",
        "",
        "Who can apply?",
        "Registered businesses and sole traders with an active account at the bank for at",
        "least six months may apply. Applicants need business records for the last six",
        "months, such as M-Pesa statements, bank statements or sales books.",
    ],
    [
        "How is the interest rate set?",
        "The rate depends on the loan term, the credit history of the business and the",
        "security offered. The full cost of the loan, including fees, is shown in the key",
        "facts document before the customer signs.",
        "",
        "How long does approval take?",
        "Complete applications are usually decided within three working days. The",
        "relationship officer explains the decision and, if the loan is declined, the",
        "main reasons for the decision.",
    ],
    [
        "Can I repay early?",
        "Yes. Early repayment is allowed at any time. Interest is charged only up to the",
        "date of repayment, and there is no early repayment penalty.",
        "",
        "What happens if I miss a payment?",
        "The bank contacts the customer by SMS and phone within three days of a missed",
        "payment to agree a plan. Late payment fees are listed in the key facts document.",
    ],
]


def write_pdf(path: Path, pages: list[list[str]], title: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(title)
    width, height = A4
    for n, lines in enumerate(pages, start=1):
        c.setFont("Helvetica", 9)
        c.drawString(50, height - 40, "Mwangaza Savings Bank - Product FAQ")  # running header
        c.setFont("Helvetica", 11)
        y = height - 80
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.setFont("Helvetica", 9)
        c.drawString(width / 2, 30, f"Page {n} of {len(pages)}")  # running footer
        c.showPage()
    c.save()


def write_blank_pdf(path: Path) -> None:
    """Simulates a scanned PDF: pages with no extractable text."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.rect(50, 400, 300, 200)
    c.showPage()
    c.save()


def write_docx(path: Path) -> None:
    doc = Document()
    doc.core_properties.title = "Branch Operations Memo"
    doc.add_heading("Branch Operations Memo", level=1)
    doc.add_paragraph("Mwangaza Savings Bank is a fictional institution used for demonstration only.")
    doc.add_paragraph(
        "From 1 December, all branches will open at 8.30 am and close at 4.30 pm on weekdays. "
        "Saturday hours stay at 9.00 am to 12.30 pm. Cash deliveries move to Tuesday and "
        "Friday mornings, and the cash count must be completed and signed by two officers "
        "before 10.00 am."
    )
    doc.add_paragraph(
        "Customer complaints must be logged in the complaints system on the day they are "
        "received, with a reference number given to the customer. Complaints not resolved "
        "within five working days are escalated to the regional manager."
    )
    doc.add_paragraph("Questions about this memo can be sent to operations@example.com.")
    doc.save(str(path))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "data-retention-guideline.txt").write_text(RETENTION)
    (OUT / "customer-onboarding-policy.md").write_text(ONBOARDING)
    write_pdf(OUT / "jenga-biashara-loan-faq.pdf", FAQ_PAGES, "Jenga Biashara Loan FAQ")
    write_docx(OUT / "branch-operations-memo.docx")
    write_blank_pdf(OUT / "scanned-statement.pdf")
    # Same content under another name: the pipeline should recognise and skip it.
    shutil.copy(OUT / "data-retention-guideline.txt", OUT / "data-retention-guideline_reupload.txt")
    (OUT / "branch-photos.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    print(f"samples written to {OUT}")


if __name__ == "__main__":
    main()
