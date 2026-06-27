-- Create a dedicated SQL login + the Evavo database, then map the login as owner.
-- Run in SQL Server Management Studio (SSMS) connected as 'sa' or a sysadmin.
-- Change the password before running, and keep it in sync with backend\.env.

-- 1) Server-level login
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'evavo_app')
BEGIN
    CREATE LOGIN [evavo_app] WITH PASSWORD = N'CHANGE_ME_strong_password',
        CHECK_POLICY = ON;
END
GO

-- 2) Database (manage.py init-db also creates this; either is fine)
IF DB_ID(N'evavo') IS NULL
    CREATE DATABASE [evavo];
GO

-- 3) Map the login into the database as a user and grant ownership
USE [evavo];
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'evavo_app')
BEGIN
    CREATE USER [evavo_app] FOR LOGIN [evavo_app];
    ALTER ROLE [db_owner] ADD MEMBER [evavo_app];
END
GO

-- Ensure SQL Server allows SQL logins (Mixed Mode authentication). If logins fail
-- with "Login failed", enable Mixed Mode: SSMS > Server > Properties > Security >
-- "SQL Server and Windows Authentication mode", then restart the SQL Server service.
