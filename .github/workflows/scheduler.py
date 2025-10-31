"""
scheduler.py
1. Allocate interview slots (start time, gap)
2. Generate .ics meeting invites for each candidate
"""

from datetime import datetime, timedelta
import uuid
from dateutil import tz

from recruito_agent.auth import get_timezone


def _utc_fmt(dt_aware):
    return dt_aware.astimezone(tz.UTC).strftime("%Y%m%dT%H%M%SZ")


def make_ics_invite(
    organizer_name: str,
    sender_email: str,
    candidate_name: str,
    candidate_email: str,
    role_prompt: str,
    start_dt,
    duration_min=45,
    location="Google Meet",
    meet_link=None,
):
    """
    Return an ICS calendar event as text (METHOD:REQUEST).
    Recruiter can attach this when emailing the candidate.
    """
    uid = f"{uuid.uuid4().hex}@hiring-agent"
    end_dt = start_dt + timedelta(minutes=duration_min)
    if not meet_link:
        meet_link = "https://meet.google.com/lookup/" + uuid.uuid4().hex[:10]

    return f"""BEGIN:VCALENDAR
PRODID:-//RecruitoAgent//EN
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:REQUEST
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{_utc_fmt(datetime.now(get_timezone()))}
DTSTART:{_utc_fmt(start_dt)}
DTEND:{_utc_fmt(end_dt)}
SUMMARY:Interview: {role_prompt} — {candidate_name}
DESCRIPTION:Interview for {role_prompt}\\nJoin: {meet_link}
LOCATION:{location}
ORGANIZER;CN={organizer_name}:mailto:{sender_email}
ATTENDEE;CN={candidate_name};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{candidate_email}
SEQUENCE:0
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR""".strip()


def build_day_schedule(
    shortlist,
    interview_date_str: str,
    day_start_hhmm: str = "10:00",
    slot_min: int = 45,
    gap_min: int = 15,
    max_per_day: int = 8,
):
    """
    Turn shortlist -> list of slots with candidate name/email + datetime start.
    Currently assumes a single day (interview_date_str = 'YYYY-MM-DD').
    """

    tzinfo = get_timezone()
    y, m, d = [int(x) for x in interview_date_str.split("-")]
    hh, mm = [int(x) for x in day_start_hhmm.split(":")]

    base = datetime(y, m, d, hh, mm, tzinfo=tzinfo)

    slots = []
    for i, cand in enumerate(shortlist[:max_per_day]):
        start = base + timedelta(minutes=i*(slot_min + gap_min))
        slots.append({
            "candidate_name": cand["name"],
            "candidate_email": cand["email"],
            "start": start,
        })
    return slots
