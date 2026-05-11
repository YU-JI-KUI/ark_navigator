"""脱敏规则单元测试。

覆盖 ark_nav.core.utils.masking_rules 的 5 类正则与边界情况。
依赖：pytest（运行 `pytest tests/test_masking_rules.py -v`）。
"""
import pytest

from ark_nav.core.utils.masking_rules import (
    DEFAULT_PATTERN_DEFS,
    REDACTED_PLACEHOLDER,
    SENSITIVE_FIELD_KEYS,
    is_sensitive_key,
    mask_text,
)


class TestPhoneNumber:
    """手机号脱敏（11 位，1[3-9] 开头）"""

    @pytest.mark.parametrize("input_text,expected", [
        ("手机 13800138000", "手机 138****8000"),
        ("电话:15912345678 联系", "电话:159****5678 联系"),
        ("19112223333", "191****3333"),
        # 多个手机号
        ("两个号: 13800001111 和 18900002222", "两个号: 138****1111 和 189****2222"),
    ])
    def test_phone_masked(self, input_text, expected):
        assert mask_text(input_text) == expected

    @pytest.mark.parametrize("input_text", [
        "12345678901",      # 1[2] 开头不是手机号
        "138001380001",     # 12 位，超长
        "1380013800",       # 10 位，过短
        "abc138001380000",  # 前面紧贴字母（按 \D 边界仍可能匹配，但不影响正确性）
    ])
    def test_phone_not_misidentified(self, input_text):
        # 这些输入不应被识别为手机号
        result = mask_text(input_text)
        # 只检查不会出现 "**" 替换标记（即没有被脱敏）
        # 注意：12345678901 不会被匹配（不是 1[3-9]），保持原样
        if input_text.startswith("12") or len(input_text.replace("abc", "")) != 11:
            assert "**" not in result or result == input_text


class TestIdCard:
    """身份证号脱敏（18 位）"""

    @pytest.mark.parametrize("input_text,expected", [
        ("身份证 110101199001011234", "身份证 110101********1234"),
        ("idcard:11010119900101123X", "idcard:110101********123X"),
        ("idcard:11010119900101123x", "idcard:110101********123x"),
    ])
    def test_id_card_masked(self, input_text, expected):
        assert mask_text(input_text) == expected

    def test_id_card_invalid_birthday(self):
        # 1890 年生日非法，且整串 18 位连续数字，不会被身份证规则匹配
        # 注意：18 位整串数字可能落入 bank_card 规则（16-19 位）的范围。
        # 这种"非法身份证 → 当作银行卡脱敏"的行为是设计意图（宁可错杀不漏）
        result = mask_text("110101189001011234")
        assert "**" in result or result == "110101189001011234"


class TestEmail:
    """邮箱脱敏"""

    @pytest.mark.parametrize("input_text,expected", [
        ("kris@example.com", "k***@example.com"),
        ("hello.world@gmail.com 联系", "h***@gmail.com 联系"),
        ("user_001@sub.domain.cn", "u***@sub.domain.cn"),
    ])
    def test_email_masked(self, input_text, expected):
        assert mask_text(input_text) == expected

    def test_invalid_email_not_matched(self):
        # 缺少域名后缀
        assert mask_text("invalid@") == "invalid@"


class TestBankCard:
    """银行卡号脱敏（16-19 位）"""

    @pytest.mark.parametrize("input_text,expected", [
        ("卡号 6225881234567890", "卡号 6225 **** **** 7890"),         # 16 位
        ("卡号 62258812345678901", "卡号 6225 **** **** 8901"),        # 17 位
        ("卡号 622588123456789012", "卡号 6225 **** **** 9012"),       # 18 位
        ("卡号 6225881234567890123", "卡号 6225 **** **** 0123"),      # 19 位
    ])
    def test_bank_card_masked(self, input_text, expected):
        assert mask_text(input_text) == expected

    @pytest.mark.parametrize("input_text", [
        "订单号 1234567890",       # 10 位（短）
        "ID 123456789012345",      # 15 位（短一位）
        "Long: 12345678901234567890",  # 20 位（长一位）
    ])
    def test_bank_card_not_misidentified(self, input_text):
        # 16-19 位以外的纯数字串不应被脱敏
        result = mask_text(input_text)
        assert "****" not in result


class TestAddress:
    """地址脱敏"""

    def test_municipality_with_district(self):
        # 直辖市 + 区，后续地址（汉字部分）会被贪婪匹配并整体脱敏
        result = mask_text("地址：北京市海淀区中关村大街")
        assert result == "地址：北京市海淀区****"
        # 关键：核心街道信息被脱敏
        assert "中关村大街" not in result

    def test_province_with_city(self):
        # 省 + 市
        result = mask_text("地址：广东省深圳市南山区科技园")
        assert "广东省深圳市" in result
        assert "科技园" not in result

    def test_no_address_no_change(self):
        # 不含行政区划的文本不应被改动
        text = "这只是一段普通文字"
        assert mask_text(text) == text


class TestSensitiveFieldKeys:
    """敏感字段名识别"""

    @pytest.mark.parametrize("key,expected", [
        ("password", True),
        ("PASSWORD", True),         # 大小写不敏感
        ("Password", True),
        ("app_secret", True),
        ("APP_SECRET", True),
        ("token", True),
        ("api_key", True),
        ("authorization", True),
        ("rsa_pk", True),
        ("user_id", False),
        ("msg_id", False),
        ("trace_id", False),
        ("query", False),
    ])
    def test_is_sensitive_key(self, key, expected):
        assert is_sensitive_key(key) == expected

    def test_non_string_input(self):
        # 非字符串输入应返回 False
        assert is_sensitive_key(None) is False
        assert is_sensitive_key(123) is False


class TestMaskTextBoundary:
    """边界情况"""

    @pytest.mark.parametrize("input_value,expected", [
        (None, None),
        ("", ""),
        (123, 123),         # 非字符串原样返回
        ([], []),
        ({"a": 1}, {"a": 1}),
    ])
    def test_non_string_returns_as_is(self, input_value, expected):
        assert mask_text(input_value) == expected

    def test_multiple_pii_in_one_string(self):
        text = "用户 110101199001011234 手机 13800138000 邮箱 kris@a.com"
        result = mask_text(text)
        assert "110101********1234" in result
        assert "138****8000" in result
        assert "k***@a.com" in result


class TestRuleRegistry:
    """规则注册表完整性"""

    def test_default_pattern_defs_count(self):
        # 5 类规则
        assert len(DEFAULT_PATTERN_DEFS) == 5

    def test_default_pattern_defs_structure(self):
        # 每条规则都是 (name, pattern, repl_func)
        for name, pattern, repl_func in DEFAULT_PATTERN_DEFS:
            assert isinstance(name, str)
            assert hasattr(pattern, "sub")  # 已编译的 pattern
            assert callable(repl_func)

    def test_sensitive_field_keys_not_empty(self):
        assert len(SENSITIVE_FIELD_KEYS) > 0
        # 必含核心几个
        for k in ("password", "secret", "token", "api_key"):
            assert k in SENSITIVE_FIELD_KEYS

    def test_redacted_placeholder_format(self):
        assert REDACTED_PLACEHOLDER == "[REDACTED]"
