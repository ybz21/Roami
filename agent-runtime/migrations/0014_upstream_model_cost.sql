ALTER TABLE model_proxy_calls ADD COLUMN cost_amount TEXT;
ALTER TABLE model_proxy_calls ADD COLUMN cost_currency TEXT;
ALTER TABLE model_proxy_calls ADD COLUMN cost_source TEXT NOT NULL DEFAULT 'unknown'
    CHECK(cost_source IN ('unknown','upstream','estimate','not_sent'));
UPDATE model_proxy_calls SET cost_source='estimate',cost_currency='CNY'
    WHERE cost_nano IS NOT NULL;
