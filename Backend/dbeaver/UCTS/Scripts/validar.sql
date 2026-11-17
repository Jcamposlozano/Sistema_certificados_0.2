SELECT current_database(), current_user, version();

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

SELECT status, count(*)
FROM certificates
GROUP BY status
ORDER BY status;

SELECT sheet, count(*)
FROM certificate_sources
GROUP BY sheet
ORDER BY sheet;
