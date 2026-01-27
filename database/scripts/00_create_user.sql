-- Panama Papers PoC - Create Schema User
-- Run as ADMIN on Autonomous Database

WHENEVER SQLERROR EXIT SQL.SQLCODE

-- Create user
CREATE USER panama_papers IDENTIFIED BY "PanamaPapers2024!";

-- Grant privileges
GRANT CREATE SESSION TO panama_papers;
GRANT CREATE TABLE TO panama_papers;
GRANT CREATE VIEW TO panama_papers;
GRANT CREATE SEQUENCE TO panama_papers;
GRANT CREATE PROCEDURE TO panama_papers;
GRANT CREATE TYPE TO panama_papers;
GRANT CREATE TRIGGER TO panama_papers;

-- Unlimited tablespace
GRANT UNLIMITED TABLESPACE TO panama_papers;

-- Graph privileges (Oracle 23ai)
GRANT CREATE PROPERTY GRAPH TO panama_papers;
GRANT GRAPH_DEVELOPER TO panama_papers;

-- Text privileges
GRANT CTXAPP TO panama_papers;
GRANT EXECUTE ON CTXSYS.CTX_DDL TO panama_papers;

COMMIT;

-- Verify
SELECT username, account_status, created
FROM dba_users
WHERE username = 'PANAMA_PAPERS';
