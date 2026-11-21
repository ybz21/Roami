ALTER TABLE swarm_members ADD COLUMN retired_ms INTEGER;
CREATE INDEX swarm_retired_members ON swarm_members(id) WHERE retired_ms IS NOT NULL;
