import re
from typing import List, Tuple, Callable
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ark_nav.core.utils.nav_logger import get_logger

# 设置最大线程数
MAX_WORKERS = 4


class DataMaskingService:
    """支持异步调用的敏感信息过滤器"""

    def __init__(self, custom_patterns: List[Tuple[str, str, Callable]] = None):
        self.patterns = self._get_default_patterns()
        if custom_patterns:
            self.patterns.extend(custom_patterns)

        self.logger = get_logger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    def _get_default_patterns(self):
        """获取默认正则模式。

        2026-05 整改：原 email/bank_card/address 正则字符类未闭合，运行时会抛
        re.error 被 try/except 吞掉静默失效，本次一并修复。

        规则与 ark_nav.core.utils.masking_rules 中的同步版本保持一致，
        共用同一份正则文本，避免双份维护。
        """
        # 从 masking_rules 模块复用规则定义（避免双份维护）
        from ark_nav.core.utils.masking_rules import DEFAULT_PATTERN_DEFS

        return [
            # 转换格式: (name, pattern, repl_func, context_words)
            (name, pattern, repl_func, None)
            for name, pattern, repl_func in DEFAULT_PATTERN_DEFS
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
