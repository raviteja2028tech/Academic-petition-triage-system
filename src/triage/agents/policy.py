"""Corpus-derived policy constants. Every entry is traceable to docs/corpus_verification.md.

Only attendance petitions are supported: the verified passages (25OB10.0(4),(5),(7), Table 25OB23.0.1) cover
attendance shortage. Everything else is explicitly unsupported until its provisions are verified in the corpus.
"""
import re

SUPPORTED_TYPES = {"attendance"}

UNSUPPORTED_NOTES = {
    "re-evaluation": "Revaluation regulations are listed in the contents but are NOT in the supplied corpus (NOT VERIFIED).",
    "re-registration": "Re-registration rules are not verified in the corpus beyond the DX/summer mention; unsupported.",
    "medical-leave": "Medical leave / pause provisions are not verified in the corpus; unsupported.",
    "grade-grievance": "Grade-grievance provisions are not verified in the corpus; unsupported.",
    "other": "Petition type is outside the supported set.",
}

# Wording in a retrieved passage that reserves the decision to an authority. A route of "grant-under-provision"
# is not allowed to rest on such a passage (see 25OB10.0(5): "may be condoned by the Vice-Chancellor").
RESERVED_AUTHORITY = re.compile(
    r"may be condoned by|at the discretion of|decision of the Vice-Chancellor|final and binding|"
    r"recommendation of the|based on the specific recommendations", re.I)

# The system recommends; it must never phrase a final university decision.
FINAL_DECISION = re.compile(
    r"\b(hereby|is|are|stand[s]?)\s+(approved|granted|rejected|condoned)\b|final decision|"
    r"\bwe (approve|grant|reject)\b|\bthe university (approves|grants|rejects)\b", re.I)

DISCLAIMER = "Recommendation only. An examination officer decides every petition."


# Interpretations that docs/corpus_verification.md lists as UNRESOLVED. They are attached verbatim to every attendance
# result that rests on clause 25OB10.0 so that no output presents them as settled fact. Nothing here is a university rule.
OPEN_QUESTIONS = [
    {"id": "OQ1", "topic": "meaning of '10 %'",
     "text": "Clause 25OB10.0(5) allows 'a shortage up to a maximum of 10 %'. Whether that means 10 percentage points "
             "(down to 75 %) or 10 % of 85 % is NOT stated. Table 25OB23.0.1 (DX below 75 %) is consistent with "
             "percentage points, but this is an unconfirmed reading."},
    {"id": "OQ2", "topic": "decision maker",
     "text": "The text reserves condonation to the Vice-Chancellor on the recommendation of the Dean/Principal/Chairperson/"
             "Programme Coordinator. Mapping this to the 'refer-to-committee' route is an unconfirmed interpretation."},
    {"id": "OQ3", "topic": "medical documentation",
     "text": "The clause requires 'valid documentary evidence' but does not say what a medical certificate must contain or "
             "that a certificate by itself qualifies a student. This system cannot judge a certificate's validity."},
    {"id": "OQ4", "topic": "corpus completeness",
     "text": "The examination bye-laws are NOT in the corpus; the official source URL and licence of the regulations PDF are "
             "NOT verified; autonomous colleges' own rules are NOT verified."},
]

HUMAN_REVIEW_CHECKLIST = [
    "Confirm the attendance figure against the official attendance record for the course.",
    "Examine the medical certificate / hospital record yourself (authenticity, dates, coverage of the absence).",
    "Check that the recommendation of the Dean/Principal/Chairperson/Programme Coordinator exists and is timely.",
    "Resolve the open interpretation questions (OQ1-OQ4) with the competent authority before relying on any figure.",
    "Record your own decision separately; this system's output is a recommendation only.",
]


# Numeric anchors read from the verified clauses (docs/corpus_verification.md V2, V3, V5):
#   base rule 25OB10.0(4): minimum 85 %;  25OB10.0(5): shortage "up to a maximum of 10 %" may be condoned by the
#   Vice-Chancellor;  Table 25OB23.0.1: DX below 75 %.
# Reading "10 %" as percentage points (OQ1, UNCONFIRMED) gives a floor of 75 %; reading it as 10 % of 85 gives 76.5 %.
# Below 75 % the petition is outside the band under EVERY reading; from 75 % to below 85 % it is inside, or possibly
# inside, the band that the regulation reserves to the Vice-Chancellor, so the AI may not reject it.
ATTENDANCE_BASE_PCT = 85.0
CONDONABLE_FLOOR_PP_PCT = 75.0
