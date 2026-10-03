"""Business constants and the workflow rules. This file is the single source of truth for the state machine."""

ROLES = ("client", "operator", "admin")
STAFF = ("operator", "admin")
QUALITIES = ("good", "usable", "bad")
ASSIGNABLE_QUALITIES = ("good", "usable")
STATUSES = ("submitted", "in_progress", "delivered", "accepted", "rejected")

# (from_status, to_status) -> roles allowed to perform the step.
TRANSITIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("submitted", "in_progress"): ("operator", "admin"),
    ("in_progress", "delivered"): ("operator", "admin"),
    ("delivered", "accepted"): ("client",),
    ("delivered", "rejected"): ("client",),
    ("rejected", "in_progress"): ("operator", "admin"),  # rework
}


def allowed_next(status: str, role: str) -> list[str]:
    return [to for (frm, to), roles in TRANSITIONS.items() if frm == status and role in roles]
