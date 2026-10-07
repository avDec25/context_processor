-- Remove the Outlook email summary feature from existing installations.
BEGIN;

DROP TABLE IF EXISTS email_summaries;
DELETE FROM prompts WHERE key IN ('email_summary', 'email_interval_summary');

COMMIT;
