"""Centralized signal rules for classifying Bluebeam activity feed rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class ActivitySignalRule:
    """Ordered rule describing how to classify one activity message."""

    name: str
    category: str
    pattern: Pattern[str]
    requires_document: bool = False
    is_markup_activity: bool = False
    is_attendance_activity: bool = False


ACTIVITY_SIGNAL_RULES: tuple[ActivitySignalRule, ...] = (
    ActivitySignalRule(
        name="attendee.joined_session",
        category="attendee",
        pattern=re.compile(r"^Joined Session$", re.IGNORECASE),
        is_attendance_activity=True,
    ),
    ActivitySignalRule(
        name="attendee.left_session",
        category="attendee",
        pattern=re.compile(r"^Left Session$", re.IGNORECASE),
        is_attendance_activity=True,
    ),
    ActivitySignalRule(
        name="attendee.disconnected",
        category="attendee",
        pattern=re.compile(r"^(?:Reconnected|Disconnected)$", re.IGNORECASE),
        is_attendance_activity=True,
    ),
    ActivitySignalRule(
        name="document.file_added",
        category="document",
        pattern=re.compile(r"^Added\s+'.+'$", re.IGNORECASE),
        requires_document=True,
    ),
    ActivitySignalRule(
        name="markup.add",
        category="markup",
        pattern=re.compile(r"^(?:Add|Added)\s+", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.edit",
        category="markup",
        pattern=re.compile(r"^(?:Edit|Edited)\s+", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.move",
        category="markup",
        pattern=re.compile(r"^(?:Move|Moved)\s+", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.paste",
        category="markup",
        pattern=re.compile(r"^(?:Paste|Pasted)(?:\s+|$)", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.delete",
        category="markup",
        pattern=re.compile(r"^(?:Delete|Deleted)\s+", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.undo",
        category="markup",
        pattern=re.compile(r"^Undo\b", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="markup.autosize",
        category="markup",
        pattern=re.compile(r"^Autosize\b", re.IGNORECASE),
        requires_document=True,
        is_markup_activity=True,
    ),
    ActivitySignalRule(
        name="chat.message",
        category="chat",
        pattern=re.compile(r"^(?:Chat|Message|Sent Message)\b", re.IGNORECASE),
    ),
    ActivitySignalRule(
        name="alert.generic",
        category="alert",
        pattern=re.compile(r"^(?:Alert|Warning|Error|Failed|Resolved)\b", re.IGNORECASE),
    ),
)


def classify_activity(message: str, document_id: int | None) -> dict[str, object]:
    """Classify one activity row using the central signal registry."""
    normalized_message = (message or "").strip()
    has_document = document_id not in (None, -1)

    for rule in ACTIVITY_SIGNAL_RULES:
        if rule.requires_document and not has_document:
            continue
        if rule.pattern.match(normalized_message):
            return {
                "activity_signal": rule.name,
                "activity_category": rule.category,
                "signal_rule": rule.pattern.pattern,
                "is_markup_activity": rule.is_markup_activity,
                "is_attendance_activity": rule.is_attendance_activity,
            }

    return {
        "activity_signal": "unclassified",
        "activity_category": "other",
        "signal_rule": "",
        "is_markup_activity": False,
        "is_attendance_activity": False,
    }