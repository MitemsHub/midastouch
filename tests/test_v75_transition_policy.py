from scripts.v75_transition_policy import VETO_STATES, allowed, apply_policy


def test_unstable_transition_states_are_vetoed() -> None:
    for state in VETO_STATES:
        assert allowed(state) is False
    assert allowed("TRANSITION_FAILED_MOVE_UP") is True
    assert allowed("STABLE_BEAR") is True


def test_policy_does_not_create_direction() -> None:
    result = apply_policy({"results": [{"state": "TRANSITION_EXPANSION_UP", "direction": 1}]})
    assert result["results"][0]["transition_policy"] == "VETO"
    assert result["results"][0]["direction"] == 1
