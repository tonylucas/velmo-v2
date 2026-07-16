from velmo.mlops.cases import guardrail_cases, memory_cases, quality_cases


def test_case_counts():
    assert len(memory_cases()) == 12
    assert len(guardrail_cases()) == 35
    assert len(quality_cases()) == 8


def test_memory_cases_have_an_evaluation_field():
    for case in memory_cases():
        ev = case["evaluation"]
        assert "expected_substring" in ev or "forbidden_substring" in ev
