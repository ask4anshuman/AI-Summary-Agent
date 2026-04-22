-- User Registration and Activity Report
SELECT 
    u.user_id,
    u.username,
    u.email,
    COUNT(a.activity_id) as total_activities,
    MAX(a.activity_date) as last_activity_date,
    AVG(a.duration_minutes) as avg_activity_duration
FROM users u
LEFT JOIN activities a ON u.user_id = a.user_id
WHERE u.created_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY u.user_id, u.username, u.email
HAVING COUNT(a.activity_id) > 0
ORDER BY total_activities DESC
LIMIT 100;
