WITH
anchor AS (
    SELECT MAX(order_date) AS today
    FROM   orders
),
valid_orders AS (
    SELECT o.id, o.customer_id, o.order_date
    FROM   orders o
    CROSS JOIN anchor a
    WHERE  o.status IN ('paid', 'shipped', 'completed')
      AND  o.order_date >= DATE_SUB(a.today, INTERVAL 24 MONTH)
),
refund_by_item AS (
    SELECT r.order_item_id,
           SUM(r.amount) AS refund_amount
    FROM   refunds r
    WHERE  r.status = 'approved'
    GROUP  BY r.order_item_id
),
line_base AS (
    SELECT
        vo.id                                   AS order_id,
        vo.customer_id,
        vo.order_date,
        oi.id                                   AS order_item_id,
        oi.product_id,
        cat.id                                  AS category_id,
        cat.name                                AS category_name,
        oi.quantity,
        oi.unit_price,
        COALESCE(oi.discount_amount, 0)         AS discount_amount,
        oi.quantity * oi.unit_price
            - COALESCE(oi.discount_amount, 0)   AS gross_amount,
        COALESCE(rf.refund_amount, 0)           AS refund_amount
    FROM       valid_orders vo
    INNER JOIN order_items  oi  ON oi.order_id  = vo.id
    INNER JOIN products     p   ON p.id         = oi.product_id
    INNER JOIN categories   cat ON cat.id       = p.category_id
    LEFT  JOIN refund_by_item rf ON rf.order_item_id = oi.id
),
cust_cat AS (
    SELECT
        customer_id,
        category_id,
        category_name,
        COUNT(DISTINCT order_id)                     AS order_cnt,
        SUM(quantity)                                AS units,
        SUM(gross_amount)                            AS gross_amount,
        SUM(refund_amount)                           AS refund_amount,
        SUM(gross_amount) - SUM(refund_amount)       AS net_amount,
        MAX(order_date)                              AS last_buy_date
    FROM  line_base
    GROUP BY customer_id, category_id, category_name
),
cust_cat_win AS (
    SELECT
        cc.*,
        RANK() OVER (
            PARTITION BY cc.category_id
            ORDER BY cc.net_amount DESC
        )                                                        AS rk_in_category,
        SUM(cc.net_amount) OVER (PARTITION BY cc.category_id)     AS cat_net_total,
        SUM(cc.net_amount) OVER (PARTITION BY cc.customer_id)     AS cust_net_total,
        ROUND(100 * cc.net_amount
              / NULLIF(SUM(cc.net_amount) OVER (PARTITION BY cc.category_id), 0), 2)
                                                                 AS pct_of_category,
        ROUND(100 * cc.net_amount
              / NULLIF(SUM(cc.net_amount) OVER (PARTITION BY cc.customer_id), 0), 2)
                                                                 AS pct_of_customer
    FROM cust_cat cc
),
cust_rfm AS (
    SELECT
        cc.customer_id,
        MAX(cc.last_buy_date)                                        AS last_buy_date,
        DATEDIFF((SELECT today FROM anchor), MAX(cc.last_buy_date))  AS recency_days,
        SUM(cc.net_amount)                                           AS monetary,
        COUNT(DISTINCT cc.category_id)                               AS category_cnt
    FROM  cust_cat cc
    GROUP BY cc.customer_id
),
order_freq AS (
    SELECT customer_id, COUNT(*) AS order_cnt
    FROM   valid_orders
    GROUP  BY customer_id
),
rfm_scored AS (
    SELECT
        r.customer_id,
        r.last_buy_date,
        r.recency_days,
        r.monetary,
        r.category_cnt,
        f.order_cnt,
        NTILE(5) OVER (ORDER BY r.recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY f.order_cnt   ASC )  AS f_score,
        NTILE(5) OVER (ORDER BY r.monetary    ASC )  AS m_score
    FROM      cust_rfm  r
    INNER JOIN order_freq f ON f.customer_id = r.customer_id
),
cust_seg AS (
    SELECT
        s.*,
        CASE
            WHEN s.r_score >= 4 AND s.f_score >= 4 AND s.m_score >= 4 THEN 'A-核心VIP'
            WHEN s.r_score >= 3 AND s.m_score >= 4                    THEN 'B-高价值活跃'
            WHEN s.r_score <= 2 AND s.m_score >= 4                    THEN 'C-高价值流失预警'
            WHEN s.r_score >= 4 AND s.f_score <= 2                    THEN 'D-新客潜力'
            WHEN s.r_score <= 2 AND s.f_score <= 2                    THEN 'E-沉睡客户'
            ELSE 'F-一般客户'
        END AS segment
    FROM rfm_scored s
),
cat_top3 AS (
    SELECT *
    FROM   cust_cat_win
    WHERE  rk_in_category <= 3
)
SELECT
    IF(GROUPING(t.category_name) = 1,
       '=== 全站合计 ===',
       t.category_name)                                        AS category_name,
    GROUPING(t.category_name)                                  AS is_rollup,
    COUNT(DISTINCT t.customer_id)                              AS top3_customer_cnt,
    SUM(t.order_cnt)                                           AS top3_order_lines,
    ROUND(SUM(t.gross_amount), 2)                              AS gross_amount,
    ROUND(SUM(t.refund_amount), 2)                             AS refund_amount,
    ROUND(SUM(t.net_amount), 2)                                AS net_amount,
    ROUND(100 * SUM(t.refund_amount)
          / NULLIF(SUM(t.gross_amount), 0), 2)                 AS refund_rate_pct,
    ROUND(AVG(t.pct_of_category), 2)                           AS avg_top3_share_pct,
    JSON_ARRAYAGG(
        JSON_OBJECT(
            'customer_id', t.customer_id,
            'customer',    cu.name,
            'segment',     seg.segment,
            'net_amount',  ROUND(t.net_amount, 2),
            'rank',        t.rk_in_category,
            'last_buy',    DATE_FORMAT(t.last_buy_date, '%Y-%m-%d'),
            'rfm',         CONCAT(seg.r_score, '-', seg.f_score, '-', seg.m_score)
        )
    )                                                          AS top3_detail_json
FROM       cat_top3   t
INNER JOIN customers  cu  ON cu.id  = t.customer_id
INNER JOIN cust_seg   seg ON seg.customer_id = t.customer_id
GROUP BY t.category_name WITH ROLLUP
HAVING GROUPING(t.category_name) = 1
    OR SUM(t.net_amount) > 0
ORDER BY GROUPING(t.category_name) ASC,
         SUM(t.net_amount) DESC;
