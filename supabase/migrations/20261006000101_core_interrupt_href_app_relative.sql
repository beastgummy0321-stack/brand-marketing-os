-- Stored in-app links use router paths; the SPA owns its mount prefix.
UPDATE interrupt SET action_url = substr(action_url, 5) WHERE action_url LIKE '/app/%';
