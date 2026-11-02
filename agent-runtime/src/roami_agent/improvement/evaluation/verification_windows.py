"""Existing verifier windows plus the bounded Docker operations around them."""

DOCKER_OPERATION_SECONDS = 30
SLIDE_COMPARISON_SECONDS = 180
MEDIA_VERIFICATION_SECONDS = 330
# Image lookup, creation, identity inspection and removal each have this existing deadline.
SANDBOX_CONTROL_SECONDS = 4 * DOCKER_OPERATION_SECONDS
