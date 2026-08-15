# -*- coding: utf-8 -*-
"""SM-2 间隔重复算法（Anki 经典版）

维护三个状态：repetition（连续答对次数）、interval（间隔天数）、ease（难度系数）。
quality（0-5）由批改映射：答对→5，答错→1（可细化）。
掌握状态：repetition >= 3 视为已掌握（mastery_level 分级）。
"""


def sm2_update(quality: int, repetition: int, interval: int, ease: float):
    """
    返回新的 (repetition, interval, ease)。
    规则：quality>=3 为“记得”，否则“忘记”重置。
    """
    if quality < 0:
        quality = 0
    if quality > 5:
        quality = 5

    ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))

    if quality >= 3:
        if repetition == 0:
            interval = 1
        elif repetition == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        repetition += 1
    else:
        repetition = 0
        interval = 1
    return repetition, interval, ease


def mastery_from_repetition(repetition: int) -> int:
    """repetition -> 掌握等级 0-5（0 未复习，1-2 学习中，3+ 已掌握分级）"""
    if repetition <= 0:
        return 0
    if repetition == 1:
        return 1
    if repetition == 2:
        return 2
    if repetition >= 3:
        return min(5, 2 + repetition - 2)
    return 0
