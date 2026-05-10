import re
from typing import List, Tuple, Callable
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 设置最大线程数
MAX_WORKERS = 4


class DataMaskingService:
    """支持异步调用的敏感信息过滤器"""

    def __init__(self, custom_patterns: List[Tuple[str, str, Callable]] = None):
        self.patterns = self._get_default_patterns()
        if custom_patterns:
            self.patterns.extend(custom_patterns)

        self.logger = logging.getLogger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    def _get_default_patterns(self):
        """获取默认正则模式"""
        return [
            # (pattern_name, pattern, replacement_function)

            # 身份证号
            ("chinese_id_card",
             r'(?:^|(?<=[^\d]))[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?=\d|$)',
             lambda m: m.group()[:6] + '********' + m.group()[-4:], None),

            # 手机号
            ("phone_number",
             r'(?:^|(?<=[^\d]))1[3-9]\d{9}(?=\D|$)',
             lambda m: m.group()[:3] + '****' + m.group()[-4:],
             None),

            # # 中文姓名
            # ("chinese_name",
            #  r'(?<![\\u4e00-\\u9fa5])([\\u4e00-\\u9fa5]{2,4})(?=[。！？\s]|$)',
            #  lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),

            # 邮箱
            ("email",
             r'(?:^|(?<=[^\w@|[一-龥]))[A-Za-z0-9._%+-]{2,}@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?=[^\w@|$)',
             lambda m: f"{m.group(1)[0]}***@{m.group(2)}", None),

            # 银行卡号
            ("bank_card",
             r'(?:^|(?<=[^\d]))(\d{4})(\d{4})(\d{4})(\d{4})(\d{0,3})(?=\D|$) ',
             lambda m: f"{m.group(1)} **** **** {m.group(4)}",
             None),

            # 地址（示例）
            ("address",
             r'(北京市|上海市|天津市|重庆市|[一-龥]{2,10}省)?([一-龥]{2,10}(?:市|自治区|州|地区|盟))([一-龥]',
             lambda m: (m.group(1) or '') + m.group(2) + (m.group(3) or '') + '****', None),
        ]

    def _has_context(self, match, context_words: List[str], window_size: int = 15) -> bool:
        """检查匹配项前后指定范围内是否包含上下文关键词"""
        if not context_words:
            return True  # 如果没有配置上下文词，默认直接通过

        full_text = match.string
        start, end = match.start(), match.end()

        # 截取前后窗口文本
        window_start = max(0, start - window_size)
        window_end = min(len(full_text), end + window_size)
        context_window = full_text[window_start:window_end]

        # 只要窗口内出现了任意一个关键词，就返回 True
        return any(word in context_window for word in context_words)

    async def _async_sub(self, pattern: str, repl_func: Callable, text: str, context_words: List[str], mask_char: str):
        """使用线程池执行 re.sub 操作"""
        loop = asyncio.get_event_loop()
        compiled_pattern = re.compile(pattern)

        def context_aware_repl(m):
            # 只有满足上下文条件，才执行替换；否则返回原字符串
            if self._has_context(m, context_words):
                return repl_func(m).replace("*", mask_char)
            return m.group()

        result = await loop.run_in_executor(
            self.executor,
            lambda: compiled_pattern.sub(context_aware_repl, text)
        )

        return result

    async def _async_finditer(self, pattern: str, text: str, context_words: List[str]) -> List[dict]:
        """使用线程池执行 re.finditer 操作"""
        loop = asyncio.get_event_loop()
        compiled_pattern = re.compile(pattern)

        def find_with_context():
            # 过滤出符合上下文条件的 match 对象
            return [m for m in compiled_pattern.finditer(text) if self._has_context(m, context_words)]

        matches = await loop.run_in_executor(
            self.executor,
            find_with_context
        )

        return matches

    async def mask_sensitive_info(self, text: str, mask_char: str = '*') -> str:
        """异步掩码敏感信息"""
        if not text:
            return text

        masked_text = text

        for name, pattern, repl_func, context_words in self.patterns:
            try:
                masked_text = await self._async_sub(pattern, repl_func, masked_text, context_words, mask_char)
            except Exception as e:
                self.logger.warning(f"Pattern {name} error: {e}")

        return masked_text

    async def find_sensitive_info(self, text: str) -> List[dict]:
        """异步查找敏感信息"""
        findings = []

        for name, pattern, _, context_words in self.patterns:
            try:
                matches = await self._async_finditer(pattern, text, context_words)
                for match in matches:
                    findings.append({
                        'type': name,
                        'value': match.group(),
                        'start': match.start(),
                        'end': match.end()
                    })
            except Exception as e:
                self.logger.warning(f"Pattern {name} error: {e}")

        return findings
