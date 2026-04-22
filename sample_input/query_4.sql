-- Customer Churn Risk Assessment
WITH customer_metrics AS (
    SELECT 
        c.customer_id,
        c.customer_name,
        c.customer_email,
        COUNT(DISTINCT o.order_id) as lifetime_orders,
        SUM(o.total_amount) as lifetime_value,
        DATEDIFF(DAY, MAX(o.order_date), NOW()) as days_since_last_order,
        AVG(DATEDIFF(DAY, LAG(o.order_date) OVER (PARTITION BY c.customer_id ORDER BY o.order_date), o.order_date)) as avg_days_between_orders
    FROM customers c
    LEFT JOIN orders o ON c.customer_id = o.customer_id
    WHERE o.order_date IS NULL OR o.order_date >= DATE_SUB(NOW(), INTERVAL 2 YEAR)
    GROUP BY c.customer_id, c.customer_name, c.customer_email
)
SELECT 
    customer_id,
    customer_name,
    customer_email,
    lifetime_orders,
    lifetime_value,
    days_since_last_order,
    CASE 
        WHEN days_since_last_order > avg_days_between_orders * 2 THEN 'HIGH'
        WHEN days_since_last_order > avg_days_between_orders * 1.5 THEN 'MEDIUM'
        ELSE 'LOW'
    END as churn_risk
FROM customer_metrics
WHERE lifetime_orders > 0
ORDER BY churn_risk DESC, days_since_last_order DESC;
