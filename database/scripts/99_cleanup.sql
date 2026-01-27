-- Panama Papers PoC - Cleanup Script
-- Run as ADMIN to completely remove the schema

WHENEVER SQLERROR CONTINUE

-- Drop the user and all objects
DROP USER panama_papers CASCADE;

-- Verify
SELECT COUNT(*) AS remaining_objects
FROM dba_objects
WHERE owner = 'PANAMA_PAPERS';

COMMIT;
