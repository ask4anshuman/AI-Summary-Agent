-- Sales Performance Analysis
SELECT 
    DATE_TRUNC(o.order_date, MONTH) as order_month,
    p.product_category,
    COUNT(DISTINCT o.order_id) as total_orders,
    SUM(o.total_amount) as revenue,
    AVG(o.total_amount) as avg_order_value,
    COUNT(DISTINCT c.customer_id) as unique_customers
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN products p ON oi.product_id = p.product_id
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'completed'
    AND o.order_date >= '2024-01-01'
GROUP BY order_month, p.product_category
ORDER BY order_month DESC, revenue DESC;
