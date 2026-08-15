# -*- coding: utf-8 -*-
from app.services import sm2
from app.services.taxonomy_service import normalize_error_type, normalize_question_payload, normalize_subject


def test_sm2_success_increases_interval():
    repetition, interval, ease = sm2.sm2_update(5, 0, 0, 2.5)
    assert repetition == 1
    assert interval >= 1
    assert ease >= 1.3


def test_sm2_failure_resets_repetition():
    repetition, interval, _ = sm2.sm2_update(1, 3, 10, 2.5)
    assert repetition == 0
    assert interval == 1


def test_error_aliases_are_normalized_without_losing_detail():
    label, detail = normalize_error_type("基础概念不清")
    assert label == "概念不清"
    assert detail == "基础概念不清"
    assert normalize_error_type("粗心大意")[0] == "粗心"
    assert normalize_error_type("未知的情况")[0] == "其他"


def test_payload_uses_controlled_taxonomy():
    payload = normalize_question_payload({"subject": "高等数学", "error_type": "对函数概念理解不清"})
    assert payload["subject"] == "数学"
    assert payload["error_type"] == "概念不清"
    assert payload["error_detail"] == "对函数概念理解不清"
    assert normalize_subject("无效学科") == "其他"
