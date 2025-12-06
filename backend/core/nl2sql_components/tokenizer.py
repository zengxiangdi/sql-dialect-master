#!/usr/bin/env python3
"""Tokenizer module for NL2SQL.

Provides smart tokenization with Chinese and English support,
optimized for natural language SQL generation.
"""
import re
import logging
from typing import List

# Configure module logger
logger = logging.getLogger(__name__)

# Try to import jieba for better Chinese tokenization
try:
    import jieba
    jieba.setLogLevel(logging.WARNING)  # Suppress jieba logs
    JIEBA_AVAILABLE = True
    logger.info("jieba tokenizer available for Chinese NL2SQL")
except ImportError:
    JIEBA_AVAILABLE = False
    logger.debug("jieba not installed, using basic tokenization for Chinese")


class Tokenizer:
    """Smart tokenizer with Chinese and English support.
    
    Performance: All static regex patterns are pre-compiled at class level.
    """
    
    # Chinese punctuation to remove
    CN_PUNCTUATION = r'[，。！？、；：""''（）【】《》]'
    
    # Pre-compiled regex patterns for performance
    _RE_CN_PUNCT = re.compile(CN_PUNCTUATION)
    _RE_EN_PUNCT = re.compile(r'[,\.!?;:\'\"()\[\]{}]')
    _RE_CHINESE_CHARS = re.compile(r'[\u4e00-\u9fff]')
    _RE_LETTER = re.compile(r'[a-zA-Z]')
    _RE_ALNUM = re.compile(r'[a-zA-Z0-9]')
    _RE_DIGIT = re.compile(r'\d')
    _RE_DIGIT_DOT = re.compile(r'[\d\.]')
    _RE_NUMBERS = re.compile(r'\d+\.?\d*')
    _RE_QUOTED = re.compile(r'["\']([^"\']+)["\']')
    
    # Common Chinese compound words that should not be split
    # These are keywords important for NL2SQL
    CHINESE_COMPOUNDS = [
        # Comparison operators
        "大于", "小于", "等于", "不等于", "大于等于", "小于等于", "超过", "低于",
        # Aggregations
        "平均", "总和", "最大", "最小", "合计", "统计", "计数", "数量",
        # Time
        "最近", "过去", "今天", "昨天", "前天", "本周", "本月", "本年",
        # Operations
        "查询", "获取", "显示", "列出", "插入", "添加", "更新", "修改", "删除", "移除",
        # Grouping/Sorting
        "分组", "汇总", "排序", "排列", "升序", "降序", "去重",
        # Tables
        "用户", "订单", "产品", "商品", "员工", "部门", "客户", "日志",
        # Columns
        "姓名", "名字", "邮箱", "电话", "地址", "年龄", "性别", "金额", "价格", "数量",
        "状态", "类型", "时间", "日期", "创建时间", "更新时间",
        # Joins
        "关联", "连接", "左连接", "右连接", "内连接",
        # Misc
        "所有", "全部", "每个", "各个",
    ]
    
    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenize text into words/tokens.
        
        Uses jieba for Chinese if available, otherwise falls back to
        compound-word aware splitting for Chinese and word-based for English.
        """
        # Clean punctuation using pre-compiled patterns
        text = Tokenizer._RE_CN_PUNCT.sub(' ', text)
        text = Tokenizer._RE_EN_PUNCT.sub(' ', text)
        
        # Check if text contains Chinese characters
        has_chinese = bool(Tokenizer._RE_CHINESE_CHARS.search(text))
        
        if has_chinese and JIEBA_AVAILABLE:
            # Use jieba for Chinese tokenization
            tokens = list(jieba.cut(text, cut_all=False))
        elif has_chinese:
            # Fallback: compound-word aware tokenization
            tokens = Tokenizer._tokenize_chinese_fallback(text)
        else:
            # English: simple word tokenization
            tokens = text.lower().split()
        
        # Filter empty tokens
        return [t.strip() for t in tokens if t.strip()]
    
    @staticmethod
    def _tokenize_chinese_fallback(text: str) -> List[str]:
        """Fallback Chinese tokenization that preserves compound words.
        
        Uses a greedy longest-match approach for known compound words.
        """
        tokens = []
        i = 0
        text_len = len(text)
        
        while i < text_len:
            char = text[i]
            
            # Skip whitespace
            if char.isspace():
                i += 1
                continue
            
            # Check if this is the start of a known compound word
            matched_compound = None
            for compound in sorted(Tokenizer.CHINESE_COMPOUNDS, key=len, reverse=True):
                if text[i:].startswith(compound):
                    matched_compound = compound
                    break
            
            if matched_compound:
                tokens.append(matched_compound)
                i += len(matched_compound)
            elif Tokenizer._RE_CHINESE_CHARS.match(char):
                # Single Chinese character
                tokens.append(char)
                i += 1
            elif Tokenizer._RE_LETTER.match(char):
                # English word - collect until non-letter
                word_start = i
                while i < text_len and Tokenizer._RE_ALNUM.match(text[i]):
                    i += 1
                tokens.append(text[word_start:i].lower())
            elif Tokenizer._RE_DIGIT.match(char):
                # Number - collect until non-digit
                num_start = i
                while i < text_len and Tokenizer._RE_DIGIT_DOT.match(text[i]):
                    i += 1
                tokens.append(text[num_start:i])
            else:
                i += 1
        
        return tokens
    
    @staticmethod
    def extract_numbers(text: str) -> List[str]:
        """Extract all numbers from text."""
        return Tokenizer._RE_NUMBERS.findall(text)
    
    @staticmethod
    def extract_quoted_strings(text: str) -> List[str]:
        """Extract quoted strings from text."""
        return Tokenizer._RE_QUOTED.findall(text)
    
    @staticmethod
    def is_chinese(text: str) -> bool:
        """Check if text contains Chinese characters."""
        return bool(Tokenizer._RE_CHINESE_CHARS.search(text))
