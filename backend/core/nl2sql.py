#!/usr/bin/env python3
"""NL2SQL Generator - Convert natural language to SQL queries.

Provides natural language to SQL conversion with:
- Chinese and English support (with optional jieba tokenization)
- 12 database dialects
- Template-based pattern matching with priority scoring
- Confidence scoring with syntax validation
- Query suggestions and explanations
"""
import re
import logging
import sqlglot
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any, Callable
from functools import lru_cache

from .config import SUPPORTED_DIALECTS, settings

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


@dataclass
class NL2SQLResult:
    """Result of NL2SQL generation."""
    success: bool = False
    input_text: str = ""
    sql: Optional[str] = None
    dialect: str = ""
    explanation: str = ""
    confidence: float = 0.0
    suggestions: list = field(default_factory=list)
    parsed_elements: dict = field(default_factory=dict)


@dataclass
class QueryTemplate:
    """Template for pattern-based SQL generation with priority."""
    name: str
    pattern: str  # Regex pattern
    sql_template: str  # SQL template with placeholders
    priority: int = 50  # Higher = matched first
    extractor: Optional[Callable] = None  # Custom extraction function
    _compiled_pattern: re.Pattern = field(init=False, repr=False, default=None)
    
    def __post_init__(self):
        """Pre-compile regex pattern for better performance."""
        try:
            self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning(f"Failed to compile pattern for template {self.name}: {e}")
            self._compiled_pattern = None
    
    def match(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to match this template against input text."""
        if self._compiled_pattern is None:
            # Fallback to non-compiled if compilation failed
            match = re.search(self.pattern, text, re.IGNORECASE)
        else:
            match = self._compiled_pattern.search(text)
        
        if match:
            return match.groupdict() if match.groupdict() else {"match": match.group(0)}
        return None


class Tokenizer:
    """Smart tokenizer with Chinese and English support."""
    
    # Chinese punctuation to remove
    CN_PUNCTUATION = r'[，。！？、；：""''（）【】《》]'
    
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
        # Clean punctuation
        text = re.sub(Tokenizer.CN_PUNCTUATION, ' ', text)
        text = re.sub(r'[,\.!?;:\'"()\[\]{}]', ' ', text)
        
        # Check if text contains Chinese characters
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        
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
            elif re.match(r'[\u4e00-\u9fff]', char):
                # Single Chinese character
                tokens.append(char)
                i += 1
            elif re.match(r'[a-zA-Z]', char):
                # English word - collect until non-letter
                word_start = i
                while i < text_len and re.match(r'[a-zA-Z0-9]', text[i]):
                    i += 1
                tokens.append(text[word_start:i].lower())
            elif re.match(r'\d', char):
                # Number - collect until non-digit
                num_start = i
                while i < text_len and re.match(r'[\d\.]', text[i]):
                    i += 1
                tokens.append(text[num_start:i])
            else:
                i += 1
        
        return tokens
    
    @staticmethod
    def extract_numbers(text: str) -> List[str]:
        """Extract all numbers from text."""
        return re.findall(r'\d+\.?\d*', text)
    
    @staticmethod
    def extract_quoted_strings(text: str) -> List[str]:
        """Extract quoted strings from text."""
        return re.findall(r'["\']([^"\']+)["\']', text)
    
    @staticmethod
    def is_chinese(text: str) -> bool:
        """Check if text contains Chinese characters."""
        return bool(re.search(r'[\u4e00-\u9fff]', text))


class NL2SQLGenerator:
    """Natural Language to SQL Generator with multi-dialect support."""
    
    # Chinese-English keyword mappings
    KEYWORDS = {
        # Query operations
        "查询": "SELECT", "获取": "SELECT", "查找": "SELECT", "显示": "SELECT", "列出": "SELECT",
        "select": "SELECT", "get": "SELECT", "find": "SELECT", "show": "SELECT", "list": "SELECT", "fetch": "SELECT",
        # Insert operations
        "插入": "INSERT", "添加": "INSERT", "新增": "INSERT", "创建": "INSERT",
        "insert": "INSERT", "add": "INSERT", "create": "INSERT",
        # Update operations
        "更新": "UPDATE", "修改": "UPDATE", "改变": "UPDATE", "设置": "UPDATE",
        "update": "UPDATE", "modify": "UPDATE", "change": "UPDATE", "set": "UPDATE",
        # Delete operations
        "删除": "DELETE", "移除": "DELETE", "清除": "DELETE",
        "delete": "DELETE", "remove": "DELETE", "drop": "DELETE",
        # Aggregations
        "统计": "COUNT", "计数": "COUNT", "数量": "COUNT", "多少": "COUNT", "几个": "COUNT",
        "count": "COUNT", "total": "COUNT", "how many": "COUNT",
        "求和": "SUM", "总和": "SUM", "合计": "SUM", "总计": "SUM",
        "sum": "SUM", "total of": "SUM",
        "平均": "AVG", "均值": "AVG", "平均值": "AVG",
        "average": "AVG", "avg": "AVG", "mean": "AVG",
        "最大": "MAX", "最高": "MAX", "最多": "MAX",
        "max": "MAX", "maximum": "MAX", "highest": "MAX", "largest": "MAX",
        "最小": "MIN", "最低": "MIN", "最少": "MIN",
        "min": "MIN", "minimum": "MIN", "lowest": "MIN", "smallest": "MIN",
        # Conditions
        "大于": ">", "超过": ">", "高于": ">", "多于": ">",
        "greater": ">", "more than": ">", "above": ">", "over": ">",
        "小于": "<", "低于": "<", "少于": "<", "不足": "<",
        "less": "<", "less than": "<", "below": "<", "under": "<",
        "等于": "=", "是": "=", "为": "=",
        "equals": "=", "equal": "=", "is": "=",
        "不等于": "!=", "不是": "!=", "不为": "!=",
        "not equal": "!=", "not": "!=", "isn't": "!=",
        "包含": "LIKE", "含有": "LIKE", "像": "LIKE",
        "contains": "LIKE", "like": "LIKE", "includes": "LIKE",
        "开头": "LIKE_START", "以...开头": "LIKE_START",
        "starts with": "LIKE_START", "beginning with": "LIKE_START",
        "结尾": "LIKE_END", "以...结尾": "LIKE_END",
        "ends with": "LIKE_END", "ending with": "LIKE_END",
        "之间": "BETWEEN", "范围": "BETWEEN",
        "between": "BETWEEN", "range": "BETWEEN",
        "为空": "IS NULL", "空值": "IS NULL",
        "is null": "IS NULL", "null": "IS NULL", "empty": "IS NULL",
        "非空": "IS NOT NULL", "不为空": "IS NOT NULL",
        "is not null": "IS NOT NULL", "not null": "IS NOT NULL", "not empty": "IS NOT NULL",
        # Sorting
        "排序": "ORDER BY", "按": "ORDER BY", "排列": "ORDER BY",
        "sort": "ORDER BY", "order": "ORDER BY", "sorted": "ORDER BY",
        "升序": "ASC", "从小到大": "ASC", "递增": "ASC",
        "ascending": "ASC", "asc": "ASC", "increasing": "ASC",
        "降序": "DESC", "从大到小": "DESC", "递减": "DESC",
        "descending": "DESC", "desc": "DESC", "decreasing": "DESC",
        # Grouping
        "分组": "GROUP BY", "按...分组": "GROUP BY", "汇总": "GROUP BY",
        "group": "GROUP BY", "group by": "GROUP BY", "grouped": "GROUP BY",
        # Limiting
        "前": "LIMIT", "限制": "LIMIT", "只要": "LIMIT", "仅": "LIMIT",
        "top": "LIMIT", "limit": "LIMIT", "first": "LIMIT", "only": "LIMIT",
        # Joins
        "关联": "JOIN", "连接": "JOIN", "合并": "JOIN", "联合": "JOIN",
        "join": "JOIN", "combine": "JOIN", "merge": "JOIN",
        "左连接": "LEFT JOIN", "left join": "LEFT JOIN",
        "右连接": "RIGHT JOIN", "right join": "RIGHT JOIN",
        "内连接": "INNER JOIN", "inner join": "INNER JOIN",
        # Time
        "今天": "CURRENT_DATE", "today": "CURRENT_DATE",
        "昨天": "DATE_SUB(CURRENT_DATE, 1)", "yesterday": "DATE_SUB(CURRENT_DATE, 1)",
        "前天": "DATE_SUB(CURRENT_DATE, 2)", "day before yesterday": "DATE_SUB(CURRENT_DATE, 2)",
        "本周": "WEEK", "this week": "WEEK",
        "本月": "MONTH", "this month": "MONTH",
        "本年": "YEAR", "this year": "YEAR",
        "最近": ">=", "recent": ">=", "last": ">=", "past": ">=",
        # Distinct
        "去重": "DISTINCT", "唯一": "DISTINCT", "不重复": "DISTINCT",
        "distinct": "DISTINCT", "unique": "DISTINCT",
    }
    
    # Common table patterns (expanded)
    TABLE_PATTERNS = {
        # Users
        "用户": "users", "user": "users", "users": "users", "会员": "users", "member": "users",
        "账户": "accounts", "account": "accounts", "accounts": "accounts",
        # Orders
        "订单": "orders", "order": "orders", "orders": "orders", "购买": "orders",
        "销售": "sales", "sale": "sales", "sales": "sales",
        # Products
        "产品": "products", "product": "products", "products": "products",
        "商品": "items", "item": "items", "items": "items", "货物": "items",
        "库存": "inventory", "inventory": "inventory", "stock": "inventory",
        # Logs
        "日志": "logs", "log": "logs", "logs": "logs", "记录": "logs",
        "操作日志": "operation_logs", "审计": "audit_logs", "audit": "audit_logs",
        # HR
        "员工": "employees", "employee": "employees", "employees": "employees", "职员": "employees",
        "部门": "departments", "department": "departments", "departments": "departments",
        "薪资": "salaries", "salary": "salaries", "工资": "salaries",
        # Customers
        "客户": "customers", "customer": "customers", "customers": "customers",
        "供应商": "suppliers", "supplier": "suppliers", "vendors": "suppliers",
        # Finance
        "交易": "transactions", "transaction": "transactions", "transactions": "transactions",
        "支付": "payments", "payment": "payments", "payments": "payments",
        "发票": "invoices", "invoice": "invoices", "invoices": "invoices",
        # Events
        "事件": "events", "event": "events", "events": "events",
        "活动": "activities", "activity": "activities",
        # Data
        "数据": "data", "data": "data", "表": "table", "table": "table",
        "配置": "configs", "config": "configs", "settings": "configs",
        # Categories
        "分类": "categories", "category": "categories", "categories": "categories",
        "标签": "tags", "tag": "tags", "tags": "tags",
        # Messages
        "消息": "messages", "message": "messages", "messages": "messages",
        "通知": "notifications", "notification": "notifications",
        "评论": "comments", "comment": "comments", "comments": "comments",
    }
    
    # Column patterns (expanded)
    COLUMN_PATTERNS = {
        # Identity
        "id": "id", "编号": "id", "标识": "id", "主键": "id",
        "uuid": "uuid", "guid": "guid",
        # Personal info
        "姓名": "name", "名字": "name", "name": "name", "名称": "name",
        "用户名": "username", "username": "username", "账号": "username",
        "邮箱": "email", "email": "email", "电子邮件": "email",
        "电话": "phone", "phone": "phone", "手机": "mobile", "mobile": "mobile",
        "地址": "address", "address": "address", "住址": "address",
        "年龄": "age", "age": "age",
        "性别": "gender", "gender": "gender", "sex": "gender",
        "生日": "birthday", "birthday": "birthday", "出生日期": "birth_date",
        # Financial
        "金额": "amount", "amount": "amount", "总额": "total_amount",
        "价格": "price", "price": "price", "单价": "unit_price",
        "数量": "quantity", "quantity": "quantity", "qty": "quantity",
        "成本": "cost", "cost": "cost",
        "利润": "profit", "profit": "profit",
        "折扣": "discount", "discount": "discount",
        "税": "tax", "tax": "tax",
        "余额": "balance", "balance": "balance",
        "薪水": "salary", "salary": "salary", "工资": "salary",
        # Time
        "日期": "date", "date": "date",
        "时间": "time", "time": "time",
        "创建时间": "created_at", "created_at": "created_at", "create_time": "created_at",
        "更新时间": "updated_at", "updated_at": "updated_at", "update_time": "updated_at",
        "开始时间": "start_time", "start_time": "start_time", "start_date": "start_date",
        "结束时间": "end_time", "end_time": "end_time", "end_date": "end_date",
        "过期时间": "expire_time", "expire_at": "expire_at",
        # Status
        "状态": "status", "status": "status",
        "类型": "type", "type": "type", "种类": "type",
        "级别": "level", "level": "level", "等级": "level",
        "优先级": "priority", "priority": "priority",
        "是否": "is_", "是否有效": "is_valid", "是否删除": "is_deleted",
        # Content
        "标题": "title", "title": "title",
        "内容": "content", "content": "content",
        "描述": "description", "description": "description", "desc": "description",
        "备注": "remark", "remark": "remark", "note": "note", "notes": "notes",
        # Relations
        "用户id": "user_id", "user_id": "user_id",
        "订单id": "order_id", "order_id": "order_id",
        "产品id": "product_id", "product_id": "product_id",
        "部门id": "dept_id", "dept_id": "dept_id", "department_id": "department_id",
        "父级": "parent_id", "parent_id": "parent_id",
        # Metrics
        "得分": "score", "score": "score", "分数": "score",
        "评分": "rating", "rating": "rating",
        "浏览量": "views", "views": "views", "view_count": "view_count",
        "点击量": "clicks", "clicks": "clicks",
        "下载量": "downloads", "downloads": "downloads",
    }
    
    # Query pattern templates (legacy - kept for backward compatibility)
    QUERY_PATTERNS = [
        # Pattern: "查询所有用户" -> SELECT * FROM users
        (r"(查询|获取|显示|列出)(所有|全部)?(.+)", "select_all"),
        # Pattern: "统计用户数量" -> SELECT COUNT(*) FROM users
        (r"(统计|计数|数量|多少)(.+)", "count"),
        # Pattern: "用户的平均年龄" -> SELECT AVG(age) FROM users
        (r"(.+)的(平均|总和|最大|最小)(.+)", "aggregate"),
        # Pattern: "按部门分组统计" -> GROUP BY
        (r"按(.+)(分组|汇总)(统计)?(.+)?", "group_by"),
        # Pattern: "前10个用户" -> LIMIT 10
        (r"(前|top)\s*(\d+)\s*(个|条)?(.+)?", "limit"),
        # Pattern: "年龄大于30的用户" -> WHERE age > 30
        (r"(.+)(大于|小于|等于|超过|低于)(\d+)的?(.+)?", "condition"),
        # Pattern: "最近7天的订单" -> WHERE date >= DATE_SUB(CURRENT_DATE, 7)
        (r"(最近|过去)(\d+)(天|周|月|年)的?(.+)?", "time_range"),
        # Pattern: "用户和订单关联" -> JOIN
        (r"(.+)(和|与|关联|连接)(.+)", "join"),
    ]
    
    def __init__(self, default_dialect: str = "hive"):
        """Initialize generator with default dialect and template system."""
        self.default_dialect = default_dialect
        self.tokenizer = Tokenizer()
        self._init_query_templates()
    
    def _init_query_templates(self) -> None:
        """Initialize prioritized query templates for pattern matching."""
        self.query_templates: List[QueryTemplate] = [
            # High priority: Specific patterns with clear structure
            QueryTemplate(
                name="top_n_query",
                pattern=r"(?:查询|获取|显示|get|show|find)?\s*(?:前|top)\s*(\d+)\s*(?:个|条|名)?\s*(.+?)(?:按|by)?\s*(.+?)?\s*(?:排序|排列|order)?",
                sql_template="SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT {n}",
                priority=90
            ),
            QueryTemplate(
                name="count_by_group",
                pattern=r"(?:统计|计算|count)\s*(?:每个|各个|each)?\s*(.+?)\s*(?:的|的数量|数量|有多少)",
                sql_template="SELECT {group_col}, COUNT(*) AS count FROM {table} GROUP BY {group_col}",
                priority=85
            ),
            QueryTemplate(
                name="time_range_query",
                pattern=r"(?:查询|获取|get|find)?\s*(?:最近|过去|last|past)\s*(\d+)\s*(天|周|月|年|days?|weeks?|months?|years?)\s*(?:的|内的)?\s*(.+)",
                sql_template="SELECT * FROM {table} WHERE {date_col} >= DATE_SUB(CURRENT_DATE, {interval})",
                priority=85
            ),
            QueryTemplate(
                name="aggregate_query",
                pattern=r"(?:计算|求|get)?\s*(.+?)\s*(?:的)?\s*(平均|总和|最大|最小|average|sum|max|min)\s*(.+)",
                sql_template="SELECT {agg_func}({col}) FROM {table}",
                priority=80
            ),
            QueryTemplate(
                name="condition_query",
                pattern=r"(?:查询|获取|find|get)?\s*(.+?)\s*(大于|小于|等于|超过|不等于|greater|less|equal|>|<|=)\s*(\d+\.?\d*)\s*(?:的)?\s*(.+)?",
                sql_template="SELECT * FROM {table} WHERE {col} {op} {value}",
                priority=75
            ),
            QueryTemplate(
                name="join_query",
                pattern=r"(?:查询|获取)?\s*(.+?)\s*(?:和|与|关联|连接|join)\s*(.+?)(?:的|数据)?",
                sql_template="SELECT * FROM {table1} JOIN {table2} ON {join_condition}",
                priority=70
            ),
            # Medium priority: General patterns
            QueryTemplate(
                name="select_with_columns",
                pattern=r"(?:查询|获取|显示|select|get|show)\s*(.+?)\s*(?:的|from)?\s*(.+?)(?:表|table)?$",
                sql_template="SELECT {columns} FROM {table}",
                priority=60
            ),
            # Low priority: Catch-all patterns
            QueryTemplate(
                name="simple_select",
                pattern=r"(?:查询|获取|显示|列出|select|get|show|list|find)\s*(?:所有|全部|all)?\s*(.+)",
                sql_template="SELECT * FROM {table}",
                priority=40
            ),
        ]
        # Sort by priority (highest first)
        self.query_templates.sort(key=lambda t: t.priority, reverse=True)
    
    def _match_templates(self, text: str) -> Tuple[Optional[QueryTemplate], Optional[Dict]]:
        """Try to match input text against query templates.
        
        Returns:
            Tuple of (matched_template, extracted_groups) or (None, None)
        """
        for template in self.query_templates:
            match_result = template.match(text)
            if match_result:
                logger.debug(f"Matched template '{template.name}' with priority {template.priority}")
                return template, match_result
        return None, None
    
    def _tokenize_and_analyze(self, text: str) -> Dict[str, Any]:
        """Tokenize text and perform semantic analysis.
        
        Returns:
            Dictionary with tokens, detected entities, and semantic info
        """
        tokens = self.tokenizer.tokenize(text)
        numbers = self.tokenizer.extract_numbers(text)
        quoted = self.tokenizer.extract_quoted_strings(text)
        
        # Detect tables from tokens
        detected_tables = []
        for token in tokens:
            if token in self.TABLE_PATTERNS:
                detected_tables.append(self.TABLE_PATTERNS[token])
        
        # Detect columns from tokens
        detected_columns = []
        for token in tokens:
            if token in self.COLUMN_PATTERNS:
                detected_columns.append(self.COLUMN_PATTERNS[token])
        
        # Detect operation keywords
        detected_ops = []
        for token in tokens:
            if token in self.KEYWORDS:
                detected_ops.append(self.KEYWORDS[token])
        
        return {
            "tokens": tokens,
            "numbers": numbers,
            "quoted_strings": quoted,
            "tables": list(set(detected_tables)),
            "columns": list(set(detected_columns)),
            "operations": list(set(detected_ops)),
            "is_chinese": self.tokenizer.is_chinese(text),
            "token_count": len(tokens)
        }
    
    def _generate_from_template(
        self,
        template: QueryTemplate,
        match_groups: Dict[str, Any],
        analysis: Dict[str, Any],
        dialect: str,
        table_hint: Optional[str],
        column_hints: Optional[List[str]]
    ) -> NL2SQLResult:
        """Generate SQL from a matched template.
        
        Args:
            template: The matched QueryTemplate
            match_groups: Regex match groups from the template
            analysis: Token analysis results
            dialect: Target SQL dialect
            table_hint: Optional table name override
            column_hints: Optional column names override
            
        Returns:
            NL2SQLResult with generated SQL
        """
        confidence = 0.7  # Base confidence for template match
        explanation_parts = []
        
        # Extract table from analysis or use hint
        table = table_hint or (analysis["tables"][0] if analysis["tables"] else "table_name")
        if table != "table_name":
            confidence += 0.1
        
        # Extract columns
        columns = column_hints or analysis["columns"] or ["*"]
        
        # Extract numbers for conditions/limits
        numbers = analysis["numbers"]
        
        try:
            if template.name == "top_n_query":
                n = numbers[0] if numbers else "10"
                order_col = analysis["columns"][0] if analysis["columns"] else "id"
                sql = f"SELECT *\nFROM {table}\nORDER BY {order_col} DESC\nLIMIT {n}"
                explanation_parts.append(f"查询前{n}条记录")
                confidence += 0.1
                
            elif template.name == "count_by_group":
                group_col = analysis["columns"][0] if analysis["columns"] else "category"
                sql = f"SELECT {group_col}, COUNT(*) AS count\nFROM {table}\nGROUP BY {group_col}"
                explanation_parts.append(f"按{group_col}分组统计")
                confidence += 0.1
                
            elif template.name == "time_range_query":
                n = numbers[0] if numbers else "7"
                date_col = "created_at" if "created_at" in str(analysis["columns"]) else "date"
                sql = f"SELECT *\nFROM {table}\nWHERE {date_col} >= DATE_SUB(CURRENT_DATE, {n})"
                explanation_parts.append(f"查询最近{n}天数据")
                confidence += 0.1
                
            elif template.name == "aggregate_query":
                # Detect aggregation type
                agg_func = "COUNT"
                for token in analysis["tokens"]:
                    if token in ["平均", "average", "avg"]:
                        agg_func = "AVG"
                    elif token in ["总和", "sum", "合计"]:
                        agg_func = "SUM"
                    elif token in ["最大", "max", "maximum"]:
                        agg_func = "MAX"
                    elif token in ["最小", "min", "minimum"]:
                        agg_func = "MIN"
                
                col = analysis["columns"][0] if analysis["columns"] else "*"
                sql = f"SELECT {agg_func}({col}) AS result\nFROM {table}"
                explanation_parts.append(f"计算{agg_func}({col})")
                confidence += 0.1
                
            elif template.name == "condition_query":
                col = analysis["columns"][0] if analysis["columns"] else "column"
                value = numbers[0] if numbers else "0"
                
                # Detect operator
                op = "="
                for token in analysis["tokens"]:
                    if token in ["大于", "超过", "greater", ">"]:
                        op = ">"
                    elif token in ["小于", "低于", "less", "<"]:
                        op = "<"
                    elif token in ["不等于", "!="]:
                        op = "!="
                    elif token in ["大于等于", ">="]:
                        op = ">="
                    elif token in ["小于等于", "<="]:
                        op = "<="
                
                sql = f"SELECT *\nFROM {table}\nWHERE {col} {op} {value}"
                explanation_parts.append(f"条件: {col} {op} {value}")
                confidence += 0.1
                
            elif template.name == "join_query":
                tables = analysis["tables"]
                if len(tables) >= 2:
                    t1, t2 = tables[0], tables[1]
                    join_key = self._guess_join_key(t1, t2)
                    sql = f"SELECT *\nFROM {t1}\nJOIN {t2} ON {join_key}"
                    explanation_parts.append(f"关联: {t1} ⟷ {t2}")
                    confidence += 0.15
                else:
                    sql = f"SELECT *\nFROM {table}\nJOIN table2 ON {table}.id = table2.{table.rstrip('s')}_id"
                    explanation_parts.append("关联查询 (请指定第二个表)")
                    confidence -= 0.1
                    
            elif template.name == "select_with_columns":
                cols = ", ".join(columns) if columns != ["*"] else "*"
                sql = f"SELECT {cols}\nFROM {table}"
                explanation_parts.append(f"查询: {cols}")
                
            else:  # simple_select
                sql = f"SELECT *\nFROM {table}"
                explanation_parts.append(f"查询表: {table}")
            
            # Add dialect comment
            sql = f"-- Generated for {dialect.upper()}\n{sql}"
            
            # Apply dialect-specific adjustments
            sql = self._apply_dialect_adjustments(sql, dialect)
            
            # Validate syntax
            validation_bonus = self._validate_generated_sql(sql, dialect)
            confidence += validation_bonus
            
            # Generate suggestions
            suggestions = self._generate_suggestions_for_template(template, table, columns, dialect)
            
            return NL2SQLResult(
                success=True,
                input_text=match_groups.get("match", ""),
                sql=sql,
                dialect=dialect,
                explanation=" | ".join(explanation_parts),
                confidence=min(max(confidence, 0.0), 1.0),
                suggestions=suggestions,
                parsed_elements=analysis
            )
            
        except Exception as e:
            logger.warning(f"Template generation failed: {e}")
            return NL2SQLResult(
                success=False,
                input_text=str(match_groups),
                dialect=dialect,
                explanation=f"Template error: {str(e)}",
                confidence=0.0
            )
    
    def _generate_suggestions_for_template(
        self,
        template: QueryTemplate,
        table: str,
        columns: List[str],
        dialect: str
    ) -> List[str]:
        """Generate suggestions specific to template-based generation."""
        suggestions = []
        
        if table == "table_name":
            suggestions.append("💡 请指定具体的表名，如：用户表、订单表、员工表")
        
        if columns == ["*"]:
            suggestions.append("💡 建议指定具体列名以提高查询性能")
        
        if template.name == "join_query":
            suggestions.append("💡 请确认关联条件是否正确")
        
        if template.name == "time_range_query" and dialect == "oracle":
            suggestions.append("💡 Oracle 日期函数语法可能需要调整")
        
        return suggestions
    
    def generate(self, text: str, dialect: str = None, table_hint: str = None, 
                 column_hints: List[str] = None) -> NL2SQLResult:
        """Generate SQL from natural language text.
        
        Uses a multi-stage approach:
        1. Tokenize and analyze input text
        2. Try template-based matching (high confidence)
        3. Fall back to keyword-based extraction (lower confidence)
        4. Validate generated SQL syntax
        5. Apply dialect-specific adjustments
        """
        dialect = dialect or self.default_dialect
        text_lower = text.lower()
        original_text = text
        
        logger.info(f"NL2SQL: Processing '{text[:50]}...' for dialect {dialect}")
        
        # Stage 1: Tokenize and analyze
        analysis = self._tokenize_and_analyze(text)
        logger.debug(f"Token analysis: {len(analysis['tokens'])} tokens, "
                    f"{len(analysis['tables'])} tables, {len(analysis['columns'])} columns")
        
        # Stage 2: Try template-based matching first (higher confidence)
        template, match_groups = self._match_templates(text_lower)
        if template:
            result = self._generate_from_template(
                template, match_groups, analysis, dialect, table_hint, column_hints
            )
            if result.success:
                logger.info(f"NL2SQL: Template '{template.name}' matched with confidence {result.confidence:.2f}")
                return result
        
        # Stage 3: Fall back to keyword-based extraction
        logger.debug("NL2SQL: Falling back to keyword-based extraction")
        
        # Parse elements from text (legacy method)
        parsed = self._parse_text(text_lower, original_text)
        parsed.update(analysis)  # Merge with token analysis
        
        # Detect operation type
        operation = self._detect_operation(text_lower)
        
        # Extract table name (with hint override)
        table = table_hint or self._extract_table(text_lower)
        
        # Extract columns (with hints)
        columns = column_hints if column_hints else self._extract_columns(text_lower)
        
        # Extract conditions (enhanced)
        conditions = self._extract_conditions_enhanced(text_lower, original_text)
        
        # Extract aggregations
        aggregations = self._extract_aggregations(text_lower)
        
        # Extract grouping
        group_by = self._extract_group_by(text_lower)
        
        # Extract ordering
        ordering = self._extract_ordering(text_lower)
        
        # Extract limit
        limit = self._extract_limit(text_lower)
        
        # Extract joins
        joins = self._extract_joins(text_lower)
        
        # Check for DISTINCT
        distinct = self._check_distinct(text_lower)
        
        # Build SQL
        sql, explanation, confidence = self._build_sql_enhanced(
            operation, table, columns, conditions, aggregations, 
            group_by, ordering, limit, joins, distinct, dialect
        )
        
        # Generate suggestions
        suggestions = self._generate_suggestions(text, sql, dialect)
        
        return NL2SQLResult(
            success=sql is not None,
            input_text=text,
            sql=sql,
            dialect=dialect,
            explanation=explanation,
            confidence=confidence,
            suggestions=suggestions,
            parsed_elements=parsed
        )
    
    def _parse_text(self, text_lower: str, original: str) -> dict:
        """Parse and extract all elements from text."""
        parsed = {
            "tables": [],
            "columns": [],
            "conditions": [],
            "aggregations": [],
            "time_range": None,
            "limit": None,
            "order": None,
            "joins": []
        }
        
        # Extract tables
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text_lower:
                if table not in parsed["tables"]:
                    parsed["tables"].append(table)
        
        # Extract columns
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text_lower:
                if column not in parsed["columns"]:
                    parsed["columns"].append(column)
        
        # Extract numbers for conditions
        numbers = re.findall(r'\d+', original)
        if numbers:
            parsed["numbers"] = numbers
        
        return parsed
    
    def _detect_operation(self, text: str) -> str:
        """Detect SQL operation type from text."""
        for keyword, op in self.KEYWORDS.items():
            if keyword in text and op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                return op
        return "SELECT"  # Default to SELECT
    
    def _extract_table(self, text: str) -> str:
        """Extract table name from text."""
        tables_found = []
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text:
                # Find position for priority
                pos = text.find(pattern)
                tables_found.append((pos, table, len(pattern)))
        
        if tables_found:
            # Return the longest match (most specific)
            tables_found.sort(key=lambda x: (-x[2], x[0]))
            return tables_found[0][1]
        return "table_name"  # Default placeholder
    
    def _extract_columns(self, text: str) -> list:
        """Extract column names from text."""
        columns = []
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text and column not in columns:
                columns.append(column)
        return columns if columns else ["*"]
    
    def _extract_conditions_enhanced(self, text: str, original: str) -> list:
        """Extract WHERE conditions with enhanced parsing."""
        conditions = []
        numbers = re.findall(r'\d+\.?\d*', original)
        
        # Find column context for conditions
        condition_column = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                condition_column = column
                break
        
        # Comparison conditions
        comparisons = [
            (["大于", "超过", "高于", "多于", "greater", "more than", "above", "over", ">"], ">"),
            (["小于", "低于", "少于", "不足", "less", "less than", "below", "under", "<"], "<"),
            (["等于", "是", "为", "equals", "equal", "="], "="),
            (["不等于", "不是", "不为", "not equal", "!="], "!="),
            (["大于等于", "不小于", "至少", ">=", "at least"], ">="),
            (["小于等于", "不大于", "最多", "<=", "at most"], "<="),
        ]
        
        for keywords, op in comparisons:
            if any(k in text for k in keywords) and numbers:
                col = condition_column or "column"
                conditions.append(f"{col} {op} {numbers[0]}")
                break
        
        # BETWEEN condition
        if any(k in text for k in ["之间", "范围", "between", "from...to"]):
            if len(numbers) >= 2:
                col = condition_column or "column"
                conditions.append(f"{col} BETWEEN {numbers[0]} AND {numbers[1]}")
        
        # LIKE conditions
        if any(k in text for k in ["包含", "含有", "contains", "like", "includes"]):
            # Try to extract the search term
            match = re.search(r'["\']([^"\']+)["\']', original)
            if match:
                col = condition_column or "column"
                conditions.append(f"{col} LIKE '%{match.group(1)}%'")
        
        # NULL conditions
        if any(k in text for k in ["为空", "空值", "is null", "null", "empty"]):
            col = condition_column or "column"
            conditions.append(f"{col} IS NULL")
        if any(k in text for k in ["非空", "不为空", "is not null", "not null", "not empty"]):
            col = condition_column or "column"
            conditions.append(f"{col} IS NOT NULL")
        
        # Date conditions (enhanced)
        date_col = "created_at" if "created_at" in text else "date"
        if "今天" in text or "today" in text:
            conditions.append(f"{date_col} = CURRENT_DATE")
        elif "昨天" in text or "yesterday" in text:
            conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 1)")
        elif "前天" in text or "day before" in text:
            conditions.append(f"{date_col} = DATE_SUB(CURRENT_DATE, 2)")
        
        # Time range conditions
        time_patterns = [
            (r"(最近|过去|last|past)\s*(\d+)\s*(天|day)", "DAY"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(周|week)", "WEEK"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(月|month)", "MONTH"),
            (r"(最近|过去|last|past)\s*(\d+)\s*(年|year)", "YEAR"),
        ]
        for pattern, unit in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                n = match.group(2)
                if unit == "DAY":
                    conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {n})")
                elif unit == "WEEK":
                    conditions.append(f"{date_col} >= DATE_SUB(CURRENT_DATE, {int(n)*7})")
                elif unit == "MONTH":
                    conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{n})")
                elif unit == "YEAR":
                    conditions.append(f"{date_col} >= ADD_MONTHS(CURRENT_DATE, -{int(n)*12})")
                break
        
        # This week/month/year
        if "本周" in text or "this week" in text:
            conditions.append(f"WEEKOFYEAR({date_col}) = WEEKOFYEAR(CURRENT_DATE)")
        if "本月" in text or "this month" in text:
            conditions.append(f"MONTH({date_col}) = MONTH(CURRENT_DATE) AND YEAR({date_col}) = YEAR(CURRENT_DATE)")
        if "本年" in text or "this year" in text:
            conditions.append(f"YEAR({date_col}) = YEAR(CURRENT_DATE)")
        
        # Status conditions
        status_patterns = [
            (["有效", "active", "enabled", "valid"], "status = 'active'"),
            (["无效", "inactive", "disabled", "invalid"], "status = 'inactive'"),
            (["已删除", "deleted", "removed"], "is_deleted = 1"),
            (["未删除", "not deleted"], "is_deleted = 0"),
            (["已完成", "completed", "done", "finished"], "status = 'completed'"),
            (["未完成", "pending", "incomplete"], "status = 'pending'"),
            (["已支付", "paid"], "status = 'paid'"),
            (["未支付", "unpaid"], "status = 'unpaid'"),
        ]
        for keywords, condition in status_patterns:
            if any(k in text for k in keywords):
                conditions.append(condition)
                break
        
        return conditions
    
    def _extract_aggregations(self, text: str) -> list:
        """Extract aggregation functions from text."""
        aggs = []
        
        # Find column context for aggregations
        agg_column = None
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                agg_column = column
                break
        
        col = agg_column or "amount"
        
        if any(k in text for k in ["统计", "计数", "数量", "多少", "几个", "count", "total", "how many"]):
            aggs.append("COUNT(*)")
        if any(k in text for k in ["求和", "总和", "合计", "总计", "sum", "total of"]):
            aggs.append(f"SUM({col})")
        if any(k in text for k in ["平均", "均值", "平均值", "average", "avg", "mean"]):
            aggs.append(f"AVG({col})")
        if any(k in text for k in ["最大", "最高", "最多", "max", "maximum", "highest", "largest"]):
            aggs.append(f"MAX({col})")
        if any(k in text for k in ["最小", "最低", "最少", "min", "minimum", "lowest", "smallest"]):
            aggs.append(f"MIN({col})")
        
        return aggs
    
    def _extract_group_by(self, text: str) -> list:
        """Extract GROUP BY columns from text."""
        group_cols = []
        
        # Pattern: "按部门分组" -> GROUP BY department
        patterns = [
            r'按(.+?)(分组|汇总|统计)',
            r'group\s*by\s*(\w+)',
            r'grouped\s*by\s*(\w+)',
            r'per\s+(\w+)',
            r'each\s+(\w+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                group_text = match.group(1).strip()
                # Try to map to column name
                for kw, col in self.COLUMN_PATTERNS.items():
                    if kw in group_text:
                        group_cols.append(col)
                        break
                else:
                    # Try table patterns for grouping
                    for kw, tbl in self.TABLE_PATTERNS.items():
                        if kw in group_text:
                            # Common grouping columns
                            if "部门" in group_text or "department" in group_text:
                                group_cols.append("department")
                            elif "用户" in group_text or "user" in group_text:
                                group_cols.append("user_id")
                            elif "日期" in group_text or "date" in group_text:
                                group_cols.append("date")
                            elif "月" in group_text or "month" in group_text:
                                group_cols.append("MONTH(date)")
                            elif "年" in group_text or "year" in group_text:
                                group_cols.append("YEAR(date)")
                            break
        
        return group_cols
    
    def _extract_ordering(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract ORDER BY clause from text."""
        order_col = None
        direction = "ASC"
        
        # Find column to order by
        for pattern, column in self.COLUMN_PATTERNS.items():
            if pattern in text:
                order_col = column
                break
        
        # Check for ordering keywords
        if any(k in text for k in ["排序", "排列", "sort", "order", "sorted"]):
            if any(k in text for k in ["降序", "从大到小", "递减", "desc", "descending", "decreasing"]):
                direction = "DESC"
            else:
                direction = "ASC"
            return (order_col or "id", direction)
        
        # Implicit ordering for aggregations
        if any(k in text for k in ["最大", "最高", "最多", "max", "highest", "top"]):
            return (order_col or "amount", "DESC")
        if any(k in text for k in ["最小", "最低", "最少", "min", "lowest"]):
            return (order_col or "amount", "ASC")
        
        return None
    
    def _extract_limit(self, text: str) -> Optional[int]:
        """Extract LIMIT value from text."""
        patterns = [
            r'前\s*(\d+)', r'top\s*(\d+)', r'limit\s*(\d+)',
            r'first\s*(\d+)', r'(\d+)\s*条', r'(\d+)\s*个',
            r'(\d+)\s*行', r'(\d+)\s*rows?', r'only\s*(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None
    
    def _extract_joins(self, text: str) -> list:
        """Extract JOIN information from text."""
        joins = []
        
        # Find multiple tables
        tables_found = []
        for pattern, table in self.TABLE_PATTERNS.items():
            if pattern in text and table not in tables_found:
                tables_found.append(table)
        
        if len(tables_found) >= 2:
            # Determine join type
            join_type = "JOIN"
            if any(k in text for k in ["左连接", "left join", "左关联"]):
                join_type = "LEFT JOIN"
            elif any(k in text for k in ["右连接", "right join", "右关联"]):
                join_type = "RIGHT JOIN"
            elif any(k in text for k in ["内连接", "inner join"]):
                join_type = "INNER JOIN"
            
            # Create join for second table onwards
            main_table = tables_found[0]
            for other_table in tables_found[1:]:
                # Guess join condition
                join_key = self._guess_join_key(main_table, other_table)
                joins.append({
                    "type": join_type,
                    "table": other_table,
                    "condition": join_key
                })
        
        return joins
    
    def _guess_join_key(self, table1: str, table2: str) -> str:
        """Guess the join key between two tables."""
        # Common patterns
        join_patterns = {
            ("users", "orders"): "users.id = orders.user_id",
            ("orders", "users"): "orders.user_id = users.id",
            ("users", "transactions"): "users.id = transactions.user_id",
            ("orders", "products"): "orders.product_id = products.id",
            ("products", "orders"): "products.id = orders.product_id",
            ("employees", "departments"): "employees.dept_id = departments.id",
            ("departments", "employees"): "departments.id = employees.dept_id",
            ("orders", "payments"): "orders.id = payments.order_id",
            ("customers", "orders"): "customers.id = orders.customer_id",
        }
        
        key = (table1, table2)
        if key in join_patterns:
            return join_patterns[key]
        
        # Default: assume table2 has table1_id
        singular = table1.rstrip('s')
        return f"{table1}.id = {table2}.{singular}_id"
    
    def _check_distinct(self, text: str) -> bool:
        """Check if DISTINCT is needed."""
        return any(k in text for k in ["去重", "唯一", "不重复", "distinct", "unique"])
    
    def _build_sql_enhanced(self, operation, table, columns, conditions, aggregations, 
                             group_by, ordering, limit, joins, distinct, dialect) -> tuple:
        """Build SQL statement from extracted components (enhanced version)."""
        explanation_parts = []
        confidence = 0.5  # Base confidence
        
        if operation == "SELECT":
            # Build SELECT clause
            distinct_kw = "DISTINCT " if distinct else ""
            
            if aggregations:
                # Include group by columns in select if grouping
                if group_by:
                    select_parts = group_by + aggregations
                    select_clause = ", ".join(select_parts)
                else:
                    select_clause = ", ".join(aggregations)
                explanation_parts.append(f"聚合: {', '.join(aggregations)}")
                confidence += 0.15
            else:
                select_clause = ", ".join(columns)
                if columns != ["*"]:
                    explanation_parts.append(f"列: {', '.join(columns)}")
                    confidence += 0.1
            
            sql = f"SELECT {distinct_kw}{select_clause}\nFROM {table}"
            explanation_parts.append(f"表: {table}")
            
            if table != "table_name":
                confidence += 0.2
            
            # Add JOINs
            for join in joins:
                sql += f"\n{join['type']} {join['table']} ON {join['condition']}"
                explanation_parts.append(f"关联: {join['table']}")
                confidence += 0.1
            
            # Add WHERE clause
            if conditions:
                sql += f"\nWHERE {' AND '.join(conditions)}"
                explanation_parts.append(f"条件: {len(conditions)}个")
                confidence += 0.1
            
            # Add GROUP BY
            if group_by:
                sql += f"\nGROUP BY {', '.join(group_by)}"
                explanation_parts.append(f"分组: {', '.join(group_by)}")
                confidence += 0.1
            elif aggregations and columns != ["*"]:
                # Auto group by non-aggregated columns
                group_cols = [c for c in columns if c != "*"]
                if group_cols:
                    sql += f"\nGROUP BY {', '.join(group_cols)}"
            
            # Add ORDER BY
            if ordering:
                sql += f"\nORDER BY {ordering[0]} {ordering[1]}"
                explanation_parts.append(f"排序: {ordering[0]} {ordering[1]}")
            
            # Add LIMIT (dialect-specific)
            if limit:
                sql = self._add_limit(sql, limit, dialect)
                explanation_parts.append(f"限制: {limit}条")
                confidence += 0.1
        
        elif operation == "INSERT":
            cols = columns if columns != ["*"] else ["col1", "col2"]
            placeholders = ", ".join(["?" for _ in cols])
            sql = f"INSERT INTO {table} ({', '.join(cols)})\nVALUES ({placeholders})"
            explanation_parts.append(f"插入到: {table}")
        
        elif operation == "UPDATE":
            set_clause = ", ".join([f"{c} = ?" for c in (columns if columns != ["*"] else ["column"])])
            sql = f"UPDATE {table}\nSET {set_clause}"
            if conditions:
                sql += f"\nWHERE {' AND '.join(conditions)}"
            else:
                sql += "\nWHERE id = ?"
            explanation_parts.append(f"更新: {table}")
        
        elif operation == "DELETE":
            sql = f"DELETE FROM {table}"
            if conditions:
                sql += f"\nWHERE {' AND '.join(conditions)}"
            else:
                sql += "\nWHERE id = ?"
            explanation_parts.append(f"删除: {table}")
        
        else:
            sql = f"-- 无法解析: {operation}"
            confidence = 0.0
        
        # Add dialect comment
        sql = f"-- Generated for {dialect.upper()}\n{sql}"
        
        # Apply dialect-specific adjustments
        sql = self._apply_dialect_adjustments(sql, dialect)
        
        # Validate generated SQL syntax and adjust confidence
        validation_bonus = self._validate_generated_sql(sql, dialect)
        confidence += validation_bonus
        
        explanation = " | ".join(explanation_parts)
        return sql, explanation, min(max(confidence, 0.0), 1.0)
    
    def _validate_generated_sql(self, sql: str, dialect: str) -> float:
        """Validate generated SQL syntax and return confidence adjustment.
        
        Args:
            sql: Generated SQL to validate
            dialect: Target dialect
            
        Returns:
            Confidence adjustment: positive if valid, negative if invalid
        """
        try:
            import sqlglot
            # Remove comment line for validation
            sql_to_validate = "\n".join(
                line for line in sql.split("\n") 
                if not line.strip().startswith("--")
            )
            if sql_to_validate.strip():
                sqlglot.parse_one(sql_to_validate, read=dialect)
                return 0.15  # Syntax valid - boost confidence
        except Exception:
            return -0.2  # Syntax error - reduce confidence
        return 0.0
    
    def _add_limit(self, sql: str, limit: int, dialect: str) -> str:
        """Add LIMIT clause with dialect-specific syntax."""
        if dialect == "oracle":
            sql += f"\nFETCH FIRST {limit} ROWS ONLY"
        elif dialect == "tsql":
            sql = sql.replace("SELECT", f"SELECT TOP {limit}", 1)
        else:
            sql += f"\nLIMIT {limit}"
        return sql
    
    def _apply_dialect_adjustments(self, sql: str, dialect: str) -> str:
        """Apply dialect-specific syntax adjustments."""
        if dialect == "hive":
            # Hive uses backticks for reserved words
            sql = sql.replace("DATE_SUB(CURRENT_DATE,", "DATE_SUB(CURRENT_DATE,")
        elif dialect == "oracle":
            # Oracle uses SYSDATE
            sql = sql.replace("CURRENT_DATE", "TRUNC(SYSDATE)")
            sql = sql.replace("DATE_SUB(TRUNC(SYSDATE), ", "TRUNC(SYSDATE) - ")
            sql = sql.replace(")", "")  # Fix extra paren
        elif dialect == "tsql":
            # SQL Server uses GETDATE()
            sql = sql.replace("CURRENT_DATE", "CAST(GETDATE() AS DATE)")
            sql = sql.replace("DATE_SUB(", "DATEADD(DAY, -")
        elif dialect == "mysql":
            # MySQL DATE_SUB syntax
            pass  # Already compatible
        elif dialect == "postgres":
            # PostgreSQL interval syntax
            sql = re.sub(r"DATE_SUB\(CURRENT_DATE,\s*(\d+)\)", 
                        r"CURRENT_DATE - INTERVAL '\1 days'", sql)
        return sql
    
    def _generate_suggestions(self, text: str, sql: str, dialect: str) -> list:
        """Generate improvement suggestions."""
        suggestions = []
        
        if "table_name" in sql:
            suggestions.append("💡 请指定具体的表名，如：用户表、订单表")
        if "column >" in sql or "column <" in sql or "column =" in sql:
            suggestions.append("💡 请指定具体的列名用于条件判断，如：年龄大于30")
        if dialect == "hive" and "SELECT *" in sql:
            suggestions.append("💡 Hive 建议指定具体列名以提高性能")
        if "JOIN" not in sql and any(k in text for k in ["关联", "连接", "join", "和", "与"]):
            suggestions.append("💡 检测到关联需求，请明确指定两个表名")
        if "?" in sql:
            suggestions.append("💡 请替换 ? 占位符为实际值")
        if "GROUP BY" in sql and "HAVING" not in sql:
            suggestions.append("💡 可以添加 HAVING 子句过滤分组结果")
        if dialect == "hive" and "ORDER BY" in sql and "LIMIT" not in sql:
            suggestions.append("💡 Hive 中 ORDER BY 建议配合 LIMIT 使用")
        if "DELETE" in sql and "WHERE" not in sql:
            suggestions.append("⚠️ DELETE 没有 WHERE 条件将删除所有数据！")
        if "UPDATE" in sql and "WHERE" not in sql:
            suggestions.append("⚠️ UPDATE 没有 WHERE 条件将更新所有数据！")
        
        return suggestions
    
    # Legacy method for backward compatibility
    def _extract_conditions(self, text: str) -> list:
        """Legacy method - redirects to enhanced version."""
        return self._extract_conditions_enhanced(text, text)
    
    def _build_sql(self, operation, table, columns, conditions, aggregations, ordering, limit, dialect) -> tuple:
        """Legacy method - redirects to enhanced version."""
        return self._build_sql_enhanced(
            operation, table, columns, conditions, aggregations,
            [], ordering, limit, [], False, dialect
        )
