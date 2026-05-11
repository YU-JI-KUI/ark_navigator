"""敏感信息脱敏规则（同步版）。

整改时间：2026-05

设计目标：
- 单一来源（Single Source of Truth）：业务数据脱敏 (DataMaskingService) 和
  日志脱敏 (nav_logger 的 _mask_sensitive_processor) 共用同一份正则
- 同步、轻量：模块加载时 pre-compile，业务调用 / 日志输出零线程池切换
- 可灰度：通过 LOG_MASK_ENABLED 环境变量在 logger processor 层控制启停

包含 5 类脱敏规则：
1. 中国身份证号（18 位，最后一位可为 X）
2. 中国大陆手机号（11 位，1[3-9] 开头）
3. 邮箱（保留首字母 + 域名）
4. 银行卡号（16-19 位连续数字）
5. 中国行政区划地址（省 + 市/自治区/州）

以及"敏感字段名 key 黑名单"集合（password / secret / token 等），
由 logger processor 用于结构化字段层 [REDACTED] 替换。
"""
import re
from typing import Callable, List, Pattern, Tuple

# ============================================================================
# 第 1 类：中国身份证号
# ============================================================================
# 规则：6 位地区码 + 8 位生日（1800-2099）+ 3 位顺序 + 1 位校验位（数字或 X/x）
# 边界：前后不能是其他数字（避免误匹配长串数字的中段）
ID_CARD_PATTERN = re.compile(
    r'(?<!\d)'
    r'[1-9]\d{5}'
    r'(?:18|19|20)\d{2}'
    r'(?:0[1-9]|1[0-2])'
    r'(?:0[1-9]|[12]\d|3[01])'
    r'\d{3}[\dXx]'
    r'(?!\d)'
)


def _mask_id_card(m: re.Match) -> str:
    """身份证：保留前 6（行政区划）+ 后 4，中间 8 位星号。"""
    return m.group()[:6] + '********' + m.group()[-4:]


# ============================================================================
# 第 2 类：中国大陆手机号
# ============================================================================
# 规则：11 位，1[3-9] 开头，前后不能是数字
PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')


def _mask_phone(m: re.Match) -> str:
    """手机号：保留前 3（运营商号段）+ 后 4。"""
    return m.group()[:3] + '****' + m.group()[-4:]


# ============================================================================
# 第 3 类：邮箱
# ============================================================================
# 规则：本地部分 2+ 字符，标准邮箱格式
EMAIL_PATTERN = re.compile(
    r'\b([A-Za-z0-9._%+-]{1,})'
    r'@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b'
)


def _mask_email(m: re.Match) -> str:
    """邮箱：保留首字母 + 域名。例：kris@example.com → k***@example.com"""
    local, domain = m.group(1), m.group(2)
    return f"{local[0]}***@{domain}"


# ============================================================================
# 第 4 类：银行卡号
# ============================================================================
# 规则：16-19 位连续数字，前后不能是其他数字
BANK_CARD_PATTERN = re.compile(r'(?<!\d)\d{16,19}(?!\d)')


def _mask_bank_card(m: re.Match) -> str:
    """银行卡：保留前 4（发卡行 BIN）+ 后 4。"""
    s = m.group()
    return f"{s[:4]} **** **** {s[-4:]}"


# ============================================================================
# 第 5 类：中国行政区划地址
# ============================================================================
# 规则：（省级 + 市/区/县/自治区...）+ 后续详细地址（吃掉 2-30 个汉字）
# 行政级别支持：省/直辖市/自治区 → 地级市/州/盟/地区/区/县/旗 → 详细
# 第二级用 [市州盟区县旗] 兼容直辖市下的"区"（如北京市海淀区）
ADDRESS_PATTERN = re.compile(
    r'(北京市|上海市|天津市|重庆市|[一-龥]{2,10}(?:省|自治区))'
    r'([一-龥]{2,10}(?:市|州|盟|地区|区|县|旗))'
    r'([一-龥]{2,30})'
)


def _mask_address(m: re.Match) -> str:
    """地址：保留省级 + 地级，详细地址打码。

    例：北京市海淀区中关村大街1号 → 北京市海淀区****
    """
    return m.group(1) + m.group(2) + '****'


# ============================================================================
# 规则注册表（业务版 DataMaskingService 和 logger processor 共用）
# ============================================================================
# 格式：(rule_name, compiled_pattern, replacement_func)
DEFAULT_PATTERN_DEFS: List[Tuple[str, Pattern, Callable[[re.Match], str]]] = [
    ("chinese_id_card", ID_CARD_PATTERN, _mask_id_card),
    ("phone_number", PHONE_PATTERN, _mask_phone),
    ("email", EMAIL_PATTERN, _mask_email),
    ("bank_card", BANK_CARD_PATTERN, _mask_bank_card),
    ("address", ADDRESS_PATTERN, _mask_address),
]


# ============================================================================
# 敏感字段名黑名单（key 匹配，整体 [REDACTED]）
# ============================================================================
# 用于结构化日志的字段名层匹配，例如：
#   logger.info("auth", app_secret="real_value", user_id=123)
# → app_secret 字段会被整体替换为 [REDACTED]，user_id 不变
SENSITIVE_FIELD_KEYS = frozenset({
    'password',
    'passwd',
    'secret',
    'app_secret',
    'token',
    'access_token',
    'refresh_token',
    'api_key',
    'apikey',
    'authorization',
    'auth_token',
    'rsa_pk',           # 项目里的 RSA 私钥配置
    'gpt_signature',    # GPT 平台签名
    'open_ai_signature',
    'client_secret',
    'app_sec',          # 项目里的简写
})

REDACTED_PLACEHOLDER = '[REDACTED]'


def mask_text(text: str) -> str:
    """对一段文本应用所有脱敏规则（同步、零线程池切换）。

    Args:
        text: 原始文本

    Returns:
        脱敏后的文本。如果输入不是 str（例如 None），原样返回。
    """
    if not isinstance(text, str) or not text:
        return text
    masked = text
    for _, pattern, repl_func in DEFAULT_PATTERN_DEFS:
        masked = pattern.sub(repl_func, masked)
    return masked


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否属于敏感字段（应整体 REDACTED）。

    匹配是大小写不敏感的。
    """
    return isinstance(key, str) and key.lower() in SENSITIVE_FIELD_KEYS
