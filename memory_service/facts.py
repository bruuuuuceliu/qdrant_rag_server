"""Deterministic, rule-based fact extraction from user self-disclosures.

``extract_facts`` turns first-person statements ("my name is Bruce", "I like
gluten-free pasta") into structured ``{"fact_type", "subject", "text"}`` dicts
that the domain handler stores as versioned, user-scoped ``UserFact`` rows
(FR-4). Extraction is purely lexical: no models, no external calls, fully
deterministic and unit-testable. Only user-turn content should be passed in
(the caller filters by message role).

The extractor is intentionally conservative and best-effort:

* every trigger is first-person ("i", "my", "call me") and word-boundary
  guarded, so third-party statements ("my friend's name is X") do not match;
* questions ("do I like X?") and question-word-prefixed sentences are skipped;
* captured values are normalized (whitespace collapsed, trailing punctuation
  stripped) and truncated to ``_VALUE_CAP`` characters;
* at most one fact is emitted per ``(fact_type, subject)`` per message, so a
  repeated disclosure in a single turn is deduplicated (FR-4.5 supersession is
  handled by the caller across messages).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Cap on extracted value length; longer disclosures are deterministically
# truncated rather than dropped so stored facts stay bounded (mirrors the
# §7.2.2 message.record content cap philosophy).
_VALUE_CAP = 200

# ---------------------------------------------------------------------------
# name plausibility
# ---------------------------------------------------------------------------

# Character set a captured name is allowed to use: letters, spaces, apostrophes
# (O'Brien), periods (initials "J. R.") and hyphens.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z' .-]*$")

# Words that never appear inside a person's name; a captured value containing
# one is truncated at the first occurrence (and rejected if it is the head).
# Deliberately excludes common given names ("will", "may", "bill") to avoid
# false negatives for "my name is Will".
_NAME_BAD_RE = re.compile(
    r"\b(?:i\b|i'?m|i'?ll|i'?d|i'?ve|you|your|yours|my|mine|me|we|us|our|"
    r"they|them|their|he|him|she|her|it|its|the|a|an|and|or|but|if|then|"
    r"than|so|because|while|when|where|why|how|what|who|whom|whose|which|"
    r"not|no|never|is|are|was|were|be|been|being|am|do|does|did|have|has|"
    r"had|would|can|could|should|shall|to|of|for|with|at|on|in|from|by|"
    r"about|into|over|under|up|down|off|out|this|that|these|those|there|"
    r"here|call|calls|called|please|thanks|ok|okay|hey|hi|hello|later|soon|"
    r"now|today|tomorrow|tonight|yesterday|back|again|maybe|perhaps|sure|yes|"
    r"yeah|dude|bro|guys|everyone|anyone|someone|something|anything|help|"
    r"helping)\b",
    re.IGNORECASE,
)


def _truncate_at_bad_word(value: str) -> str:
    """Cut a captured name at the first non-name word ("bruce when you...").

    This lets "call me Bruce when you're free" yield the name "Bruce" instead of
    discarding the whole disclosure because a trailing clause snuck into the
    capture.
    """
    match = _NAME_BAD_RE.search(value)
    if match:
        value = value[: match.start()]
    return value.strip(" .,;:!?-'\"()")


def _valid_name(value: str) -> bool:
    if not value:
        return False
    words = value.split()
    if not 1 <= len(words) <= 4:
        return False
    if not _NAME_RE.match(value):
        return False
    for word in words:
        lowered = word.lower().strip(".'\"")
        if not any(ch.isalpha() for ch in lowered):
            return False
        if lowered in _NAME_BAD_WORDS:
            return False
    return True


_NAME_BAD_WORDS = frozenset(
    w
    for w in (
        "i", "i'm", "i'll", "i'd", "i've", "you", "your", "yours", "my", "mine",
        "me", "we", "us", "our", "they", "them", "their", "he", "him", "she",
        "her", "it", "its", "the", "a", "an", "and", "or", "but", "if", "then",
        "than", "so", "because", "while", "when", "where", "why", "how", "what",
        "who", "whom", "whose", "which", "not", "no", "never", "is", "are",
        "was", "were", "be", "been", "being", "am", "do", "does", "did", "have",
        "has", "had", "would", "can", "could", "should", "shall", "to", "of",
        "for", "with", "at", "on", "in", "from", "by", "about", "into", "over",
        "under", "up", "down", "off", "out", "this", "that", "these", "those",
        "there", "here", "call", "calls", "called", "please", "thanks", "ok",
        "okay", "hey", "hi", "hello", "later", "soon", "now", "today",
        "tomorrow", "tonight", "yesterday", "back", "again", "maybe", "perhaps",
        "sure", "yes", "yeah", "dude", "bro", "guys", "everyone", "anyone",
        "someone", "something", "anything", "help", "helping",
    )
)

# ---------------------------------------------------------------------------
# preference polarity + clause-boundary refinement
# ---------------------------------------------------------------------------

# A captured object is cut at contrastive/conjunctive clause boundaries so
# "i like pasta, i don't like cheese" yields the object "pasta" (not the whole
# trailing clause) and "i prefer tea over coffee" yields "tea". We deliberately
# do NOT cut at a bare "and" because list objects ("pizza and pasta") are a
# single preference object.
_OBJECT_BOUNDARY = re.compile(
    r"\s*(?:"
    r",\s*(?:i'?m|i|my|you|we|they|he|she|it|this|that|these|those|"
    r"do|does|did|would|can|could|should|will|won't|wouldn't|can't|"
    r"don't|doesn't|didn't|isn't|aren't|am|is|are|was|were)\b"
    r"|\s(?:but|though|although|because|since|over)\b"
    r"|\s+and\s+(?:my|i'?m|i|you|we|work|live|study)\b"
    r")",
    re.IGNORECASE,
)


def _truncate_object(value: str) -> str:
    match = _OBJECT_BOUNDARY.search(value)
    if match:
        value = value[: match.start()]
    return value


# Occupation keyword suffixes for "i'm a/an <role>" extraction. The role regex
# requires the captured text to END with one of these, so "i'm a big fan of
# pizza" is not captured while "i'm a software engineer" is.
_OCCUPATION_SUFFIXES = (
    "engineer",
    "developer",
    "programmer",
    "designer",
    "scientist",
    "researcher",
    "analyst",
    "consultant",
    "manager",
    "teacher",
    "doctor",
    "lawyer",
    "writer",
    "author",
    "artist",
    "founder",
    "student",
    "nurse",
    "accountant",
    "architect",
    "marketer",
    "recruiter",
    "chef",
    "pilot",
    "dentist",
    "therapist",
    "photographer",
    "journalist",
    "editor",
    "director",
    "producer",
    "mechanic",
    "electrician",
    "plumber",
    "carpenter",
    "barista",
    "waiter",
    "bartender",
    "salesperson",
    "receptionist",
    "technician",
    "economist",
    "pharmacist",
    "veterinarian",
)
# The head is optional and lazy so a single-word role whose whole word is a
# suffix ("i'm a doctor") still matches: the capture must END in a suffix, but
# there need not be a prefix before it.
_OCCUPATION_ROLE = r"[a-z -]*?(?:" + "|".join(_OCCUPATION_SUFFIXES) + r")"

# Bare pronoun preference objects ("i like this") carry no durable signal.
# "you"/"me"/"us" are included so "i like you" is not stored as a preference
# fact about a pronoun.
_BARE_OBJECTS = frozenset(
    {"this", "that", "it", "them", "these", "those", "you", "me", "us"}
)


def _preference_valid(subject: str) -> bool:
    return subject.lower() not in _BARE_OBJECTS


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Rule:
    """One lexical trigger: a fact type, a regex, and capture semantics.

    ``subject`` is either a static slot (``"name"``, ``"location"``,
    ``"email"``, ...), derived from a match group (``subject_group``), or the
    cleaned captured value itself (``subject_from_value`` — used for
    preferences, where the object is the topic being superseded).
    """

    fact_type: str
    pattern: re.Pattern[str]
    subject: str = ""
    value_group: int = 1
    subject_group: int | None = None
    subject_from_value: bool = False
    transform: Callable[[str], str] | None = None
    valid: Callable[[str], bool] | None = None


# Rule order matters for intra-message dedupe: a negated preference is listed
# before its positive counterpart so "i don't like pizza" wins the
# (preference, "pizza") slot when a message states both polarities.
_RULES: tuple[_Rule, ...] = (
    # --- name ----------------------------------------------------------------
    # The name capture allows embedded periods so abbreviations and initials
    # ("Mr. Smith", "J. R.") survive; the sentence splitter already isolates a
    # real sentence boundary, and _truncate_at_bad_word / _valid_name reject
    # anything that is not actually a name.
    _Rule("name", re.compile(r"\bmy name is ([^!?\n]+)", re.IGNORECASE), subject="name", transform=_truncate_at_bad_word, valid=_valid_name),
    _Rule("name", re.compile(r"\b(?:you )?can call me ([^!?\n]+)", re.IGNORECASE), subject="name", transform=_truncate_at_bad_word, valid=_valid_name),
    _Rule("name", re.compile(r"\bcall me ([^!?\n]+)", re.IGNORECASE), subject="name", transform=_truncate_at_bad_word, valid=_valid_name),
    _Rule("name", re.compile(r"\bi(?:'m| am) called ([^!?\n]+)", re.IGNORECASE), subject="name", transform=_truncate_at_bad_word, valid=_valid_name),
    # --- preference (negated first) -------------------------------------------
    _Rule(
        "preference",
        re.compile(r"\bi (?:don't|do not|dont)\s+like ([^.!?\n]+)", re.IGNORECASE),
        subject_from_value=True,
        transform=lambda value: f"does not like {value}",
        valid=_preference_valid,
    ),
    _Rule(
        "preference",
        re.compile(
            r"\bi (?:really |very |kind of |sort of )?(?:like|love|enjoy|prefer|adore|am into)\b ([^.!?\n]+)",
            re.IGNORECASE,
        ),
        subject_from_value=True,
        valid=_preference_valid,
    ),
    _Rule(
        "preference",
        re.compile(
            r"\bmy (?:favorite|favourite) ([a-z][a-z -]{0,40}?) is ([^.!?\n]+)",
            re.IGNORECASE,
        ),
        subject_group=1,
        value_group=2,
    ),
    # --- location --------------------------------------------------------------
    _Rule("location", re.compile(r"\bi live in ([^.!?\n]+)", re.IGNORECASE), subject="location"),
    _Rule("location", re.compile(r"\bi(?:'m| am) based in ([^.!?\n]+)", re.IGNORECASE), subject="location"),
    _Rule("location", re.compile(r"\bi(?:'m| am) from ([^.!?\n]+)", re.IGNORECASE), subject="location"),
    _Rule("location", re.compile(r"\bmy city is ([^.!?\n]+)", re.IGNORECASE), subject="location"),
    # --- occupation -------------------------------------------------------------
    _Rule("occupation", re.compile(r"\bi work as (?:an? )?([^.!?\n]+)", re.IGNORECASE), subject="role"),
    _Rule("occupation", re.compile(r"\bi work (?:at|for) ([^.!?\n]+)", re.IGNORECASE), subject="employer"),
    _Rule(
        "occupation",
        re.compile(r"\bi(?:'m| am) an? (" + _OCCUPATION_ROLE + r")(?![a-z])", re.IGNORECASE),
        subject="role",
    ),
    # --- contact -----------------------------------------------------------------
    _Rule(
        "contact",
        re.compile(r"\bmy email(?: address)? is ([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE),
        subject="email",
    ),
    _Rule(
        "contact",
        re.compile(r"\bmy (?:phone|mobile|cell)(?: number)? is ([\+(]?\d[\d\s().-]{4,19})", re.IGNORECASE),
        subject="phone",
    ),
)

# ---------------------------------------------------------------------------
# question guard
# ---------------------------------------------------------------------------

_QUESTION_START = re.compile(
    r"^(?:do|does|did|am|is|are|was|were|will|would|can|could|should|"
    r"may|might|must|have|has|had|what|why|how|where|when|who|whom|"
    r"whose|which)\b",
    re.IGNORECASE,
)


# Common abbreviations whose trailing period must not start a new "sentence",
# else "my name is Mr. Smith" would be split into "Mr." + "Smith" and capture
# only "Mr". (``re`` needs fixed-width lookbehinds, so the abbreviation is
# checked on the already-split piece instead.)
_ABBREVIATION_END = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|Sr|Jr|vs|etc|e\.g|i\.e)\.$", re.IGNORECASE
)


def _split_sentences(content: str) -> list[str]:
    sentences: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", content.strip()):
        if not part.strip():
            continue
        if sentences and _ABBREVIATION_END.search(sentences[-1]):
            # The previous piece ended in an abbreviation ("Mr."), so this piece
            # continues the same sentence; merge to keep "Mr. Smith" together.
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def _is_question(sentence: str) -> bool:
    stripped = sentence.strip()
    if stripped.endswith("?"):
        return True
    lead = re.sub(r"^[\"'(\[{]+", "", stripped)
    return _QUESTION_START.match(lead) is not None


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[.,;:!?]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value[:_VALUE_CAP]


def _normalize_value(raw: str) -> str:
    value = _clean(raw)
    value = _truncate_object(value)
    return _clean(value)


def extract_facts(content: str) -> list[dict[str, str]]:
    """Extract first-person self-disclosure facts from ``content``.

    Returns a list of ``{"fact_type", "subject", "text"}`` mappings — at most
    one per ``(fact_type, subject)`` for the message. Deterministic and
    exception-free for any input: unparseable/empty content yields ``[]``.

    Fact types emitted: ``name``, ``preference``, ``location``, ``occupation``,
    ``contact``.
    """
    if not content or not content.strip():
        return []
    seen: set[tuple[str, str]] = set()
    facts: list[dict[str, str]] = []
    for sentence in _split_sentences(content):
        if _is_question(sentence):
            continue
        for rule in _RULES:
            for match in rule.pattern.finditer(sentence):
                value = _normalize_value(match.group(rule.value_group))
                if rule.subject_from_value:
                    subject = value
                elif rule.subject_group is not None:
                    subject = _clean(match.group(rule.subject_group))
                else:
                    subject = rule.subject
                if rule.transform is not None:
                    value = _clean(rule.transform(value))
                if not subject or not value:
                    continue
                if rule.valid is not None and not rule.valid(subject if rule.subject_from_value else value):
                    continue
                key = (rule.fact_type, subject)
                if key in seen:
                    continue
                seen.add(key)
                facts.append({"fact_type": rule.fact_type, "subject": subject, "text": value})
    return facts
