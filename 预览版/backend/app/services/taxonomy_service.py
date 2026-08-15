# -*- coding: utf-8 -*-
"""受控学科/错因词表与历史数据归一化。

AI 的输出和历史人工编辑可能出现近义词。本模块确保写库、筛选和统计始终使用
稳定的枚举；无法安全归类的详细说法会保留在 ``error_detail`` 中而不是污染统计。
"""
from __future__ import annotations

import re
from typing import Any

from app.models.models import SUBJECTS, ERROR_TYPES, DIFFICULTIES

_SUBJECT_ALIASES = {
    "语数英": "其他",
    "高等数学": "数学",
    "数一": "数学",
    "数二": "数学",
    "数三": "数学",
    "大学数学": "数学",
    "英文": "英语",
    "英语语言": "英语",
    "物理学": "物理",
    "化学学科": "化学",
    "生物学": "生物",
    "思政": "政治",
    "思想政治": "政治",
    "地理学": "地理",
}

# 先处理高置信完全匹配，再处理明确语义的关键词；不要猜测“知识不牢”等模糊内容。
_ERROR_ALIASES = {
    "概念理解错误": "概念不清",
    "概念理解": "概念不清",
    "基础概念不清": "概念不清",
    "概念不清晰": "概念不清",
    "概念模糊": "概念不清",
    "知识点不清": "概念不清",
    "审题不清": "审题失误",
    "审题错误": "审题失误",
    "读题错误": "审题失误",
    "粗心大意": "粗心",
    "马虎": "粗心",
    "计算失误": "计算错误",
    "运算错误": "计算错误",
    "方法错误": "方法不当",
    "方法选择不当": "方法不当",
    "不会做": "方法不当",
    "无": "其他",
    "未提供": "其他",
    "": "其他",
}


def _clean(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def normalize_subject(value: object) -> str:
    """返回可用于存储和筛选的标准学科。"""
    text = _clean(value)
    if text in SUBJECTS:
        return text
    if text in _SUBJECT_ALIASES:
        return _SUBJECT_ALIASES[text]
    # 只对包含某一个已知学科的长描述归类，避免“数学和物理”误归类。
    matches = [subject for subject in SUBJECTS if subject != "其他" and subject in text]
    return matches[0] if len(matches) == 1 else "其他"


def normalize_difficulty(value: object) -> str:
    """返回受控难度，避免外部输入破坏筛选和排序。"""
    text = _clean(value)
    aliases = {"简单": "易", "容易": "易", "一般": "中", "普通": "中", "困难": "难", "较难": "难"}
    return text if text in DIFFICULTIES else aliases.get(text, "中")


def normalize_error_type(value: object) -> tuple[str, str]:
    """返回 ``(标准错因, 原始详情)``。

    原文等于规范名称时不重复保存详情；长描述命中受控类别时保留它，方便用户
    仍能了解具体薄弱点。
    """
    raw = str(value or "").strip()
    text = _clean(raw)
    if text in ERROR_TYPES:
        return text, ""
    if text in _ERROR_ALIASES:
        normalized = _ERROR_ALIASES[text]
        return normalized, raw if raw and raw != normalized else ""

    checks = (
        ("概念", "概念不清"),
        ("定义", "概念不清"),
        ("审题", "审题失误"),
        ("题意", "审题失误"),
        ("粗心", "粗心"),
        ("马虎", "粗心"),
        ("计算", "计算错误"),
        ("运算", "计算错误"),
        ("方法", "方法不当"),
        ("思路", "方法不当"),
        ("超纲", "超纲"),
    )
    for keyword, normalized in checks:
        if keyword in text:
            return normalized, raw
    return "其他", raw if raw and text != "其他" else ""


def normalize_question_payload(payload: dict[str, Any], *, preserve_detail: bool = True) -> dict[str, Any]:
    """复制并规范化一条题目的分类字段，不修改调用方对象。"""
    result = dict(payload)
    if "subject" in result:
        result["subject"] = normalize_subject(result.get("subject"))
    if "error_type" in result:
        normalized, detail = normalize_error_type(result.get("error_type"))
        result["error_type"] = normalized
        if preserve_detail and detail and not result.get("error_detail"):
            result["error_detail"] = detail[:256]
    if "difficulty" in result:
        result["difficulty"] = normalize_difficulty(result.get("difficulty"))
    return result
