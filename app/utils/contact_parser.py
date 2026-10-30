import re
import urllib.parse
from typing import List, Optional, Tuple

EMAIL_BLACKLIST = [
    "glints.com",
    "linkedin.com",
    "jobstreet.com",
    "jobstreet.co.id",
    "kalibrr.com",
    "indeed.com",
    "google.com",
    "perusahaan.co.id",
    "example.com",
    "sentry.io",
    "w3.org",
    "domain.com",
    "noreply",
    "donotreply"
]

def extract_clean_emails(text: Optional[str]) -> List[str]:
    """Extract valid company / recruitment emails from job descriptions or websites,
    filtering out platform-specific bots and dummy domains."""
    if not text or not isinstance(text, str):
        return []

    email_pattern = r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
    raw_emails = re.findall(email_pattern, text)

    valid_emails: List[str] = []
    for e in raw_emails:
        clean = e.strip().rstrip(".,;:!?)'\"")
        lower = clean.lower()
        if any(b in lower for b in EMAIL_BLACKLIST):
            continue
        if len(clean) > 6 and "." in clean.split("@")[-1]:
            if clean not in valid_emails:
                valid_emails.append(clean)

    return valid_emails

def extract_whatsapp_number(text: Optional[str]) -> Optional[str]:
    """Extract Indonesian WhatsApp or phone number from job posting text."""
    if not text or not isinstance(text, str):
        return None

    # Check for direct wa.me links
    wa_link = re.search(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\d+)", text, re.IGNORECASE)
    if wa_link:
        return wa_link.group(1)

    # Check for text patterns: WA / Hubungi / HP / Contact followed by 08xx or +628xx (with optional dashes/spaces)
    phone_pattern = r"(?:wa|whatsapp|hubungi|contact|telepon|hp|chat)[^0-9\n\r]*?((?:\+62|62|0)8[0-9\-\.\s]{7,15})"
    match = re.search(phone_pattern, text, re.IGNORECASE)
    if match:
        raw = re.sub(r"[\s\-\.\+]", "", match.group(1))
        if 10 <= len(raw) <= 15:
            if raw.startswith("08"):
                return "62" + raw[1:]
            elif raw.startswith("628"):
                return raw

    # Fallback search for any standalone 08xx or +628xx number if word whatsapp is anywhere in text
    if any(k in text.lower() for k in ["wa", "whatsapp"]):
        standalone = re.search(r"((?:\+62|62|0)8[0-9\-\.\s]{7,15})", text)
        if standalone:
            raw = re.sub(r"[\s\-\.\+]", "", standalone.group(1))
            if 10 <= len(raw) <= 15:
                if raw.startswith("08"):
                    return "62" + raw[1:]
                elif raw.startswith("628"):
                    return raw

    return None

def build_whatsapp_outreach_url(phone_number: str, candidate_name: str, job_title: str, company_name: str) -> str:
    """Generate pre-filled, professional WhatsApp greeting URL for instant HR outreach."""
    greeting = (
        f"Halo Tim Rekrutmen {company_name},\n\n"
        f"Perkenalkan, saya {candidate_name}. Saya melihat lowongan untuk posisi *{job_title}* "
        f"dan sangat tertarik untuk mengajukan lamaran kerja / karir di {company_name}.\n\n"
        f"Saya memiliki latar belakang teknis yang relevan dan siap berkontribusi secara langsung. "
        f"Apakah posisi ini masih menerima pelamar?\n\n"
        f"Terima kasih banyak atas waktu dan perhatian Bapak/Ibu."
    )
    encoded = urllib.parse.quote(greeting)
    return f"https://wa.me/{phone_number}?text={encoded}"

def build_linkedin_recruiter_url(company_name: str) -> str:
    """Generate search URL to find recruiters, talent acquisition, and hiring managers on LinkedIn."""
    clean_company = re.sub(r"\b(PT|CV|Inc|LLC|Tbk|Corp)\b", "", company_name, flags=re.IGNORECASE).strip()
    query = f"Recruiter {clean_company}"
    return f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(query)}"
