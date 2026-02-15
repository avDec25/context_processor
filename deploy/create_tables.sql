CREATE TABLE pull_requests (
    pr_id TEXT PRIMARY KEY,
    created_on TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Tokyo'),
    ai_responses JSONB
);


CREATE TABLE confluence (
    confluence_id TEXT PRIMARY KEY,
    created_on TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'Asia/Tokyo'),
    ai_responses JSONB
);
