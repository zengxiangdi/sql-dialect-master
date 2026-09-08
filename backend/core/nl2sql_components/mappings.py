#!/usr/bin/env python3
"""Language mappings for NL2SQL.

Contains Chinese-English keyword mappings for tables, columns, and SQL operations.
"""
from typing import Dict


# Chinese-English keyword mappings
KEYWORDS: Dict[str, str] = {
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
TABLE_PATTERNS: Dict[str, str] = {
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
    "分类": "categories", "categories": "categories",
    "标签": "tags", "tag": "tags", "tags": "tags",
    # Messages
    "消息": "messages", "message": "messages", "messages": "messages",
    "通知": "notifications", "notification": "notifications",
    "评论": "comments", "comment": "comments", "comments": "comments",
}

# Column patterns (expanded)
COLUMN_PATTERNS: Dict[str, str] = {
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
    # Categorization
    "分类": "category", "category": "category",
    # Metrics
    "得分": "score", "score": "score", "分数": "score",
    "评分": "rating", "rating": "rating",
    "浏览量": "views", "views": "views", "view_count": "view_count",
    "点击量": "clicks", "clicks": "clicks",
    "下载量": "downloads", "downloads": "downloads",
}
