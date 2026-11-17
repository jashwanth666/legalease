import re

text = """MUTUAL NON-DISCLOSURE AGREEMENT
This Mutual Non-Disclosure Agreement (the 'Agreement') is entered into as of March 15, 2024 (the 'Effective Date'),
by and between Acme Corporation, a Delaware corporation ('Disclosing Party'), and Beta Technologies LLC ('Receiving Party').

1. Term and Duration. This Agreement shall continue in effect for a term of 2 years from the Effective Date.
The confidentiality obligations hereunder shall survive for a period of 5 years following termination.

2. Termination. Either party may terminate upon 30 days prior written notice.

3. Governing Law. This Agreement shall be construed in accordance with the laws of Delaware.
Any dispute arising shall be resolved by binding arbitration under the rules of the American Arbitration Association.
"""

# Test parties pattern
patterns = [
    r"by and between\s+([A-Za-z0-9\s,.\-'\"]+?)(?:,|\s+having|\s+with|\s*\()(?:\s*\(?[\"'][A-Za-z\s]+[\"']\)?|\s*a\s+[A-Za-z\s]+)?\s+and\s+([A-Za-z0-9\s,.\-'\"]+?)(?:,|\s+having|\s+with|\s*\()",
    r"by and between\s+([A-Z][A-Za-z0-9\s.\-]+?)(?:,|\s+a\s+|\s*\().*?\s+and\s+([A-Z][A-Za-z0-9\s.\-]+?)(?:,|\s+a\s+|\s*\(|[.\n])",
]

for pat in patterns:
    m = re.search(pat, text, re.IGNORECASE)
    print(pat[:40], "->", m.groups() if m else None)

m_date = re.search(
    r"(?:effective\s+date|effective\s+as\s+of|dated\s+as\s+of|entered\s+into\s+as\s+of|entered\s+into\s+on)\s*(?:is|:)?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    text,
    re.IGNORECASE,
)
print("Date ->", m_date.groups() if m_date else None)

m_conf = re.search(
    r"(?:confidentiality\s+(?:obligations?\s+hereunder\s+shall\s+survive|obligations?\s+shall\s+survive|period))\s*(?:for\s+a\s+period\s+of\s+|for\s+)?([^\.\n;]{3,40})",
    text,
    re.IGNORECASE,
)
print("Conf ->", m_conf.groups() if m_conf else None)
