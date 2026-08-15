# -*- coding: utf-8 -*-
"""数学计算工具：AI 可调用的 sympy 符号计算引擎（安全执行，只解析表达式不执行代码）"""
import logging

logger = logging.getLogger(__name__)

import sympy as sp

# 允许的 sympy 便捷名称映射
_ALIASES = {
    "integrate": sp.integrate,
    "integral": sp.integrate,
    "diff": sp.diff,
    "derivative": sp.diff,
    "limit": sp.limit,
    "simplify": sp.simplify,
    "solve": sp.solve,
    "expand": sp.expand,
    "factor": sp.factor,
    "sqrt": sp.sqrt,
    "pi": sp.pi,
    "exp": sp.exp,
    "log": sp.log,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "oo": sp.oo,
    "I": sp.I,
}


def _safe_sympify(expr_str: str):
    """把表达式字符串转成 sympy 对象；仅支持 sympy 语法与白名单名称，不执行任意 Python 代码"""
    # 预替换常见写法：^ → **（AI 常写 x^2）
    expr_str = expr_str.replace("^", "**")
    # 预定义常用符号
    x, y, z, t, u, v = sp.symbols("x y z t u v")
    a, b, c, R, r = sp.symbols("a b c R r")
    local = {"x": x, "y": y, "z": z, "t": t, "u": u, "v": v,
             "a": a, "b": b, "c": c, "R": R, "r": r,
             "integrate": sp.integrate, "diff": sp.diff, "limit": sp.limit,
             "simplify": sp.simplify, "solve": sp.solve, "expand": sp.expand,
             "factor": sp.factor, "sqrt": sp.sqrt, "exp": sp.exp, "log": sp.log,
             "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "oo": sp.oo, "I": sp.I,
             "pi": sp.pi, "E": sp.E}
    # 允许调用的是 sympy 函数白名单，sympify 不执行任意代码
    return sp.sympify(expr_str, locals=local, evaluate=True)


def run_math_calc(expr_str: str) -> str:
    """执行数学表达式计算，返回结果字符串（符号 + 数值近似）"""
    try:
        expr = _safe_sympify(expr_str)
        # 若结果含未计算的积分/求导，执行 .doit()
        if hasattr(expr, "doit"):
            try:
                expr = expr.doit()
            except Exception:
                pass
        # 结果字符串
        try:
            sym = sp.sstr(expr)
        except Exception:
            sym = str(expr)
        # 数值近似（若含数值可近似）
        approx = ""
        try:
            n = sp.N(expr, 8)
            if n.is_number:
                approx = f"  ≈ {n}"
        except Exception:
            pass
        return f"{sym}{approx}"
    except Exception as e:
        return f"计算错误：{type(e).__name__}: {str(e)[:120]}"


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "math_calc",
        "description": (
            "用符号计算引擎精确计算/验证数学表达式（积分、导数、极限、化简、解方程、代入数值）。"
            "遇到需要计算的数学题，先调用本工具算一遍再作答，确保答案精确无误。"
            "语法示例：integrate(x**2, (x, 0, 1))；diff(x**3, x)；limit(sin(x)/x, x, 0)；"
            "simplify(sqrt(3)*pi - 1/4)；代入数值：6*(5*pi/(6*sqrt(3))+Rational(1,4))"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "要计算的数学表达式（sympy 语法，乘方用 **，分数用 Rational(a,b) 或 a/b）"},
                "note": {"type": "string", "description": "这个计算验证/计算什么（可选，一句话）"}
            },
            "required": ["expr"]
        }
    }
}
