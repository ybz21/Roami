"""Expose saved image permissions before choosing an execution role."""


def image_role_instructions(settings, instructions, role):
    availability = {
        name: "enabled" if settings.route(name).capabilities.get("images") is True else "disabled"
        for name in ("main", "worker")
    }
    return instructions + (
        "\nImage input availability (saved runtime configuration): "
        f"Main={availability['main']}; Worker={availability['worker']}. Current role: {role}. "
        "A handoff does not transfer image capability. When visual evidence is needed, use an "
        "enabled role's read within authorized roots or report the limitation. File metadata "
        "and programmatic measurements do not establish direct visual inspection."
    )
