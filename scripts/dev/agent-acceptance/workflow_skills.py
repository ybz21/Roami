"""Isolated domain workflows with per-instance receipts to prove Skill use."""

import secrets


def install_workflow_skills(root):
    location = root / "workflow-skills"
    markers = {
        name: name.upper().replace("-", "_") + "_" + secrets.token_hex(4)
        for name in ["service-review", "report-writing"]
    }
    descriptions = {
        "service-review": "Review service proposals, SLA batch data and effective price corrections using source evidence.",
        "report-writing": "Turn verified research or service assessments into a saved, read-back-checked report with source links and evidence limits.",
    }
    instructions = {
        "service-review": "仅审查用户要求的项目，沿索引的实际链接读取，不猜测未提供的文件名。核对原说明及适用日期，更正公告覆盖旧价格。仅在用户提供批次数据并要求核算时，SLA按总成功次数/总请求次数加权核算，不平均各批次百分比。分别标记事实、推断、待核实。输出审查结论和来源给写作流程。",
        "report-writing": "读取上一步审查和实际引用资料后再成稿。正文包含资料来源、核验边界、交付校验。保存到用户目录后必须通过read读回检查，回复实际存在的文件链接。来源不足明确写局限。不要改动用户目录外的文件。",
    }
    for name, marker in markers.items():
        folder = location / name
        folder.mkdir(parents=True, mode=0o700)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {descriptions[name]}\n---\n\n# {name}\n\n{instructions[name]}\n\n本次流程凭证为 `{marker}`，交给后续流程并保留在最终文档的交付校验段，便于核对实际加载和结果传递。\n"
        )
    return location, markers
