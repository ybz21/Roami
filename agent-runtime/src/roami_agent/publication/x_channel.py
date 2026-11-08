"""Explicitly configured X API transport; the host owns authority and durable attempts."""

import hashlib
import json
import re

import httpx

from roami_agent.protocol.errors import DomainError

API = "https://api.x.com/2"


def numeric(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,29}", value) is not None


class XChannel:
    def __init__(self, client, access_token):
        if (
            not isinstance(access_token, str)
            or not access_token
            or any(c.isspace() for c in access_token)
        ):
            raise DomainError("PUBLICATION_ACCOUNT_UNAVAILABLE", 409)
        self.client, self._access_token = client, access_token

    async def request(self, method, path, *, allow_partial=False, **kwargs):
        try:
            response = await self.client.request(
                method,
                API + path,
                headers={"Authorization": "Bearer " + self._access_token},
                follow_redirects=False,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            code = (
                "PUBLICATION_CHANNEL_READ_FAILED"
                if method == "GET"
                else "PUBLICATION_NETWORK_OUTCOME_UNKNOWN"
            )
            raise DomainError(code, 409) from exc
        if not 200 <= response.status_code < 300:
            # The durable host attempt remains unresolved until an explicit reconciliation.
            code = (
                "PUBLICATION_CHANNEL_READ_FAILED"
                if method == "GET"
                else "PUBLICATION_REMOTE_OUTCOME_UNCONFIRMED"
            )
            raise DomainError(code, 409)
        try:
            value = response.json()
            if (
                not isinstance(value, dict)
                or (value.get("errors") and not allow_partial)
                or not isinstance(value.get("data"), dict)
            ):
                raise ValueError("response")
            return {**value["data"], "_responseHadErrors": bool(value.get("errors"))}
        except (ValueError, TypeError) as exc:
            raise DomainError("PUBLICATION_RECEIPT_UNCONFIRMED", 409) from exc

    async def identity(self, expected):
        if not numeric(expected):
            raise DomainError("INVALID_PUBLICATION_ACCOUNT_ID")
        value = await self.request(
            "GET", "/users/me", params={"user.fields": "id,username,protected"}
        )
        if value.get("id") != expected or value.get("protected") is not False:
            raise DomainError("PUBLICATION_ACCOUNT_SCOPE_CONFLICT", 403)
        return {"id": expected, "public": True}

    async def upload_image(self, account, reference, body):
        await self.identity(account)
        if (
            not isinstance(body, bytes)
            or not body
            or len(body) > 5 * 1024 * 1024
            or hashlib.sha256(body).hexdigest() != reference.get("sha256")
            or len(body) != reference.get("sizeBytes")
            or reference.get("mimeType") not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise DomainError("PUBLICATION_MEDIA_INTEGRITY_FAILED", 409)
        value = await self.request(
            "POST",
            "/media/upload",
            data={"media_category": "tweet_image"},
            files={"media": ("frozen-image", body, reference["mimeType"])},
        )
        media_id, media_key = value.get("id"), value.get("media_key")
        if (
            not numeric(media_id)
            or not isinstance(media_key, str)
            or not re.fullmatch(r"[0-9]+_" + re.escape(media_id), media_key)
        ):
            raise DomainError("PUBLICATION_MEDIA_RECEIPT_UNCONFIRMED", 409)
        processing = value.get("processing_info")
        if processing is not None and (
            not isinstance(processing, dict) or processing.get("state") != "succeeded"
        ):
            raise DomainError("PUBLICATION_MEDIA_PROCESSING", 409)
        return {
            "id": media_id,
            "mediaKey": media_key,
            "sha256": reference["sha256"],
            "accountId": account,
        }

    async def create(self, account, business_key, version_sha, text, media, journal):
        if not callable(journal):
            raise DomainError("PUBLICATION_DURABLE_ATTEMPT_REQUIRED", 409)
        if (
            not isinstance(business_key, str)
            or not business_key
            or not isinstance(version_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", version_sha)
        ):
            raise DomainError("INVALID_PUBLICATION_IDENTITY")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(media, list)
            or len(media) > 4
        ):
            raise DomainError("INVALID_PUBLICATION_CONTENT")
        if any(
            not numeric(item.get("id")) or item.get("accountId") != account for item in media
        ) or len({item["id"] for item in media}) != len(media):
            raise DomainError("PUBLICATION_MEDIA_SCOPE_CONFLICT", 403)
        await self.identity(account)
        payload = {"text": text}
        if media:
            payload["media"] = {"media_ids": [item["id"] for item in media]}
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        common = {
            "businessKey": business_key,
            "versionSha256": version_sha,
            "accountId": account,
            "requestSha256": fingerprint,
            "media": media,
        }
        await journal({**common, "phase": "post_submit"})
        value = await self.request("POST", "/tweets", json=payload, allow_partial=True)
        if not numeric(value.get("id")):
            raise DomainError("PUBLICATION_RECEIPT_UNCONFIRMED", 409)
        receipt = {
            **common,
            "phase": "post_created",
            "platformId": value["id"],
            "responseHadErrors": value["_responseHadErrors"],
            "url": "https://x.com/i/web/status/" + value["id"],
        }
        await journal(receipt)
        return {**receipt, "state": "accepted"}

    async def confirm(self, account, post_id, text, media):
        if not numeric(post_id):
            raise DomainError("INVALID_PUBLICATION_PLATFORM_ID")
        await self.identity(account)
        value = await self.request(
            "GET", "/tweets/" + post_id, params={"tweet.fields": "author_id,attachments,entities"}
        )
        if value.get("id") != post_id or value.get("author_id") != account:
            raise DomainError("PUBLICATION_RECEIPT_SCOPE_CONFLICT", 403)
        observed = value.get("text")
        entities = value.get("entities") or {}
        if not isinstance(observed, str) or not isinstance(entities, dict):
            raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
        for url in entities.get("urls", []):
            if (
                not isinstance(url, dict)
                or not isinstance(url.get("url"), str)
                or not isinstance(url.get("expanded_url"), str)
            ):
                raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
            observed = observed.replace(url["url"], url["expanded_url"])
        actual_media = (value.get("attachments") or {}).get("media_keys", [])
        if observed != text or sorted(actual_media) != sorted(item["mediaKey"] for item in media):
            raise DomainError("PUBLICATION_CONTENT_UNCONFIRMED", 409)
        return {
            "state": "public",
            "platformId": post_id,
            "accountId": account,
            "url": "https://x.com/i/web/status/" + post_id,
        }
