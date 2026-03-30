-- 数据迁移后主键唯一性检查
SELECT id, COUNT(*) AS duplicate_count
FROM users
GROUP BY id
HAVING COUNT(*) > 1;

-- 订单金额是否存在负值
SELECT order_id, total_amount
FROM orders
WHERE total_amount < 0;

-- 关联字段是否存在孤儿数据
SELECT oi.order_id
FROM order_items oi
LEFT JOIN orders o ON o.order_id = oi.order_id
WHERE o.order_id IS NULL;

-- 迁移前后数据量对账
SELECT 'source_users' AS dataset, COUNT(*) AS total_count FROM source_users
UNION ALL
SELECT 'target_users' AS dataset, COUNT(*) AS total_count FROM users;
