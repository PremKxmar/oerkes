"""The shared output every workflow returns. See contract/*.schema.json."""


def result(correlation_id, status, risk="LOW", evidence=None, action_type="NONE", **action):
    return {
        "status": status,
        "recommendedAction": {"type": action_type, **action},
        "risk": risk,
        "evidence": evidence or [],
        "correlationId": correlation_id,
    }
