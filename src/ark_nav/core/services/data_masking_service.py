"""敏感信息脱敏服务

设计原则：
1. 同步精简版：日志 Filter 中调用，不能阻塞、不能用线程池
2. 预编译 regex，O(1) 复用
3. 覆盖：身份证、手机号、邮箱、银行卡、密码/密钥/token/secret 等 key-value 模式
"""
import re
from typing import List, Pattern, Tuple, Callable


_MaskFn = Callable[[re.Match], str]


def _compile_patterns() -> List[Tuple[str, Pattern, _MaskFn]]:
    """返回 (name, compiled_pattern, replacement_fn) 列表"""
    return [
        # 身份证号：保留前 6 位 + 后 4 位
        (
            "chinese_id_card",
            re.compile(r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"),
            lambda m: m.group()[:6] + "********" + m.group()[-4:],
        ),
        # 手机号：保留前 3 位 + 后 4 位
        (
            "phone_number",
            re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
            lambda m: m.group()[:3] + "****" + m.group()[-4:],
        ),
        # 邮箱：local 部分只保留首字母
        (
            "email",
            re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{2,})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.])"),
            lambda m: f"{m.group(1)[0]}***@{m.group(2)}",
        ),
        # 银行卡号：16-19 位连续数字，保留前 4 + 后 4
        (
            "bank_card",
            re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)"),
            lambda m: f"{m.group(1)}********{m.group(2)}",
        ),
        # 密码 / 密钥 / token / secret 等 key-value 模式（大小写不敏感）
        # 匹配 key=value、key: value、"key": "value" 三种格式
        (
            "credential_kv",
            re.compile(
                r"(?P<key>(?:password|passwd|pwd|secret|app_secret|api_secret|token|access_token|"
                r"refresh_token|api_key|apikey|app_key|authorization|auth)\s*[\"']?\s*[:=]\s*[\"']?)"
                r"(?P<val>[^\s,;\"'}\)]{1,200})",
                re.IGNORECASE,
            ),
            lambda m: f"{m.group('key')}****",
        ),
        # Bearer / Basic 鉴权头
        (
            "bearer_token",
            re.compile(r"(?P<scheme>(?:Bearer|Basic)\s+)(?P<val>[A-Za-z0-9._\-+/=]{8,})", re.IGNORECASE),
            lambda m: f"{m.group('scheme')}****",
        ),
    ]


_PATTERNS: List[Tuple[str, Pattern, _MaskFn]] = _compile_patterns()


def mask_text(text: str) -> str:
    """对单段文本做脱敏。

    设计为同步函数，可在日志 Filter / 中间件等同步上下文中安全调用。
    """
    if not isinstance(text, str) or not text:
        return text

    masked = text
    for _, pattern, repl in _PATTERNS:
        try:
            masked = pattern.sub(repl, masked)
        except Exception:
            # 脱敏失败绝不能影响业务流程，吞掉异常即可
            continue
    return masked


class DataMaskingService:
    """兼容旧接口：保留 async mask_sensitive_info / find_sensitive_info"""

    async def mask_sensitive_info(self, text: str, mask_char: str = "*") -> str:
        return mask_text(text)

    async def find_sensitive_info(self, text: str) -> List[dict]:
        if not text:
            return []
        findings = []
        for name, pattern, _ in _PATTERNS:
            for m in pattern.finditer(text):
                findings.append({"type": name, "value": m.group(), "start": m.start(), "end": m.end()})
        return findings
