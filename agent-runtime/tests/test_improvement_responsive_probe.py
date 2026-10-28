"""Run the frozen browser probe against visible behavior, including hidden DOM cards."""

import json
import os

import pytest

from roami_agent.improvement.evaluation.authored_grading import RESPONSIVE_PROBE
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.server.configuration import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy,passed",
    [
        ("hidden", True),
        ("removed", True),
        ("ignored", False),
        ("wrong", False),
        ("incomplete", False),
        ("empty", False),
    ],
)
async def test_responsive_probe_checks_visible_filtered_cards(tmp_path, strategy, passed):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE to a frozen evaluation image with Chromium")
    content = """<!doctype html><meta charset="utf-8">
<input data-testid="draft" style="min-height:44px"><input data-testid="filter">
<div id="cards"></div><script>
const strategy=STRATEGY;
const input=document.querySelector('[data-testid="filter"]');
const draft=document.querySelector('[data-testid="draft"]');
input.value=localStorage.getItem('filter')||'';
draft.value=localStorage.getItem('draft')||'';
function render(){
 const root=document.querySelector('#cards');root.textContent='';
 for(let n=0;n<5;n++){
  if(strategy==='incomplete'&&n!==1)continue;
  const title='Card '+n,match=title.includes(input.value);
  if(input.value&&strategy==='removed'&&!match)continue;
  const card=document.createElement('div');card.dataset.testid='board-card';card.textContent=title;
  if(input.value&&strategy==='hidden'&&!match)card.hidden=true;
  if(input.value&&strategy==='wrong'&&n!==2)card.hidden=true;
  if(input.value&&strategy==='empty')card.hidden=true;
  root.appendChild(card);
 }
}
input.addEventListener('input',()=>{localStorage.setItem('filter',input.value);render()});
draft.addEventListener('input',()=>localStorage.setItem('draft',draft.value));render();
</script>""".replace("STRATEGY", json.dumps(strategy))
    (tmp_path / "index.html").write_text(content)
    executor = ContainerExecutor(Settings(), image=image)
    output = await executor.sandbox(tmp_path, RESPONSIVE_PROBE, timeout=60)
    checks = json.loads(output.decode().splitlines()[-1])
    assert all(checks.values()) is passed, checks
    assert checks["responsive"] and checks["touch"] and checks["draft"] and checks["filter"]
