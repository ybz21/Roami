# 仅Main开启图片时的视觉交接原题对照

## 产品设计与用户故事

视频v138已交付视频和连续清单，原生0.625仍未到1.0。Main图片开启、Worker关闭，实际只使用非视觉工具做匹配，Main没有收到像素。用户需要沿保存配置完成真实画面判断；不能将图片不可用的角色或检索分数冒充直接看图。

## 技术设计与实验

只在通用context/image_role_instructions.py追加由角色配置决定的说明：当只有Main可读图片时，先由Main解决依赖画面的判断，再交给Worker做后续执行。不增加领域工具、不转移图片权限、不覆盖模型/能力配置。包在运行前冻结，两个新原题运行使用同一套原任务、原判定器与1.0门槛，继承节点模型/参数/能力/重试。v167为当前203文件Python核心控制组，v168仅改变该说明；两组136可信文件、14迁移、7条退役路径检查一致。保留相同离线CLIP资源与v138的两个可选视频包，不向Actor提供查询规格、选片编号或参考答案。

两组镜像在同一v137媒体依赖底座上覆盖当前Python源；Actor内嵌Go程序未更新。因此这是固定媒体环境下的配对实验，不宣称与正式镜像或历史v138具备完整同条件可比性，也不将一次对照当作稳定性证明。

## 实际结果

| 运行 | 组别 | Main调用 | Main图片载荷出现次数 | 原生分数 / 门槛 | Case状态 | 网关请求 | Token | 消费（元） |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| v167 | 当前核心 | 5 | 0 | 0.25 / 1.0 | failed | 71 | 3,664,219 | 0.6642310 |
| v168 | 协调规则实验 | 2 | 0 | 0.0 / 1.0 | failed | 53 | 1,850,753 | 0.3645661 |

**实验没有达到预期：规则没有触发Main接收图片；修正规则组原生分数未达到1.0。** 通用说明补充已撤回，差异与两个冻结源清单在节点私有证据中保留；本次PR仅记录结果，不将失败规则合入。实际Case状态和原生分数按上表保留，执行完成与整题通过分别看，不能靠机制测试代替质量成绩。

本批124笔请求、5,514,972 Token、1.0287971元，全部按UUID匹配本地Go网关已知HTTP200。配置、原套件、模型、参数、能力和重试哈希保持；Go处理每日准入，没有Python Token/请求/费用上限。旧正式60题历史、人工参考及真实观察保持。主/后台仍为保存的deepseek-4.1-flash，Worker图片关闭；是否在模型页保存开启已提供具体提案，未获选择前不应用。

修正规则源的既有图片读取/角色隔离回归63项通过；这仅是机制回归，真实运行说明它不足以证明协调行为改变。未重跑Runtime全套、未准备或部署新应用候选、未安装节点Skill、未启用日程。最初测试文件名错误及只读资源探测漏临时目录均为验收脚本错误，0模型调用；分别保留并修正，未计为产品修复。

证据入口：节点main-visual-first-evidence-20261101，包含预登记plan与planned-native-comparison、两组镜像/源码清单、原始运行回执、native-comparison-summary、网关核账、63项回归和rejected-core-instruction.patch。音频质量、视频后续质量、股票内容评分、独立评分配置、人工参考、正式全套及真实完整日观察等仍未验收，#443/#445/#446保持开放。

<details>
<summary>已撤回的核心说明差异（仅文档留存）</summary>

```diff
diff --git a/agent-runtime/src/roami_agent/context/image_role_instructions.py b/agent-runtime/src/roami_agent/context/image_role_instructions.py
index 0eae0a75..5732ff34 100644
--- a/agent-runtime/src/roami_agent/context/image_role_instructions.py
+++ b/agent-runtime/src/roami_agent/context/image_role_instructions.py
@@ -6,10 +6,20 @@ def image_role_instructions(settings, instructions, role):
         name: "enabled" if settings.route(name).capabilities.get("images") is True else "disabled"
         for name in ("main", "worker")
     }
-    return instructions + (
-        "\nImage input availability (saved runtime configuration): "
-        f"Main={availability['main']}; Worker={availability['worker']}. Current role: {role}. "
-        "A handoff does not transfer image capability. When visual evidence is needed, use an "
-        "enabled role's read within authorized roots or report the limitation. File metadata "
-        "and programmatic measurements do not establish direct visual inspection."
+    visual_handoff = (
+        " Resolve image-dependent decisions in Main before handing off execution when only Main "
+        "has image input. Worker can do nonvisual work; its measurements do not replace that review."
+        if role == "main" and availability == {"main": "enabled", "worker": "disabled"}
+        else ""
+    )
+    return (
+        instructions
+        + (
+            "\nImage input availability (saved runtime configuration): "
+            f"Main={availability['main']}; Worker={availability['worker']}. Current role: {role}. "
+            "A handoff does not transfer image capability. When visual evidence is needed, use an "
+            "enabled role's read within authorized roots or report the limitation. File metadata "
+            "and programmatic measurements do not establish direct visual inspection."
+        )
+        + visual_handoff
     )
```

</details>
