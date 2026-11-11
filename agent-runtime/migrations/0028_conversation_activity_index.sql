CREATE INDEX events_activity_anchor ON events(
    conversation_id,
    json_extract(payload_json,'$.activity.anchorMessageId'),
    json_extract(payload_json,'$.activity.id'),
    id
) WHERE json_type(payload_json,'$.activity')='object';
