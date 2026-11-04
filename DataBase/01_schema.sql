-- eCamp Database Schema
-- Users table for authentication

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster lookups
DROP INDEX IF EXISTS idx_users_email ON users;
CREATE INDEX idx_users_email ON users(email);
DROP INDEX IF EXISTS idx_users_username ON users;
CREATE INDEX idx_users_username ON users(username);
