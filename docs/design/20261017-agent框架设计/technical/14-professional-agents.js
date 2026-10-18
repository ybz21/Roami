
const copy={probe:'检测 CLI 版本、登录状态与支持能力；展示来源及时间，失败保留错误原因。此原型未发起检测。',task:'打开任务创建入口，预选此智能体；先选已有项目、散任务或新项目，提交后才创建。此原型未创建会话。',usage:'进入用量详情：实际 tokens、套餐额度和费用分区展示；缺失显示未知。此原型未读取账号。'};document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('preview-result').textContent=b.dataset.agent+'：'+copy[b.dataset.action]}));
