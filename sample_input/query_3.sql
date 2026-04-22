-- Inventory and Stock Movement
SELECT 
    w.warehouse_id,
    w.location,
    p.product_id,
    p.product_name,
    i.current_stock,
    i.min_stock_level,
    i.reorder_quantity,
    SUM(sm.quantity) as total_moved_last_week
FROM warehouses w
INNER JOIN inventory i ON w.warehouse_id = i.warehouse_id
INNER JOIN products p ON i.product_id = p.product_id
LEFT JOIN stock_movements sm ON i.inventory_id = sm.inventory_id
    AND sm.movement_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
WHERE i.current_stock <= i.min_stock_level * 1.5
GROUP BY w.warehouse_id, w.location, p.product_id, p.product_name, 
         i.current_stock, i.min_stock_level, i.reorder_quantity
ORDER BY w.warehouse_id, i.current_stock ASC;
