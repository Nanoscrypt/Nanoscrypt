"""Conservative policy for promoting and isolating generated tools."""

from collections.abc import Sequence


def decide_lifecycle_state(
    current_state: str,
    outcomes: Sequence[tuple[str, str]],
) -> tuple[str, str]:
    """Return a lifecycle state and reason from (task_key, contribution) evidence.

    A tool must help several distinct task families before it becomes shared.
    Runtime success is deliberately not used as task-outcome evidence.
    """
    if current_state in {"retired", "quarantined"}:
        return current_state, "State requires explicit review to change"

    if not outcomes:
        return current_state, "Awaiting task-outcome evidence"

    latest = outcomes[-5:]
    distinct_keys = {key for key, _ in outcomes if key.strip()}
    helpful = sum(1 for _, result in outcomes if result == "helpful")
    harmful = sum(1 for _, result in outcomes if result == "harmful")
    observed_rate = helpful / len(outcomes)
    recent_harmful = sum(1 for _, result in latest if result == "harmful")

    if current_state == "shared" and recent_harmful >= 3:
        return "quarantined", "Three harmful outcomes in the latest five reviews"
    if current_state == "shared" and recent_harmful >= 2:
        return "needs_improvement", "Repeated harmful outcomes require review"

    if current_state in {"candidate", "needs_improvement"}:
        if harmful >= 3 and len(distinct_keys) >= 2:
            return "quarantined", "Repeated harmful outcomes across task families"
        if len(outcomes) >= 5 and len(distinct_keys) >= 3 and observed_rate >= 0.8:
            return "shared", "Repeated helpful outcomes across distinct task families"
        return current_state, "More independent task-outcome evidence is needed"

    return current_state, "No lifecycle transition applies"
