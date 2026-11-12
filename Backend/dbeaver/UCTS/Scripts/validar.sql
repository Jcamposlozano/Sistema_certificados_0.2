SELECT current_database(), current_user, version();

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

SELECT p.email, e.title, e.date, e.hours, a.available
FROM attendances a
JOIN participants p ON p.id = a.participant_id
JOIN events e ON e.id = a.event_id
ORDER BY e.date DESC;
