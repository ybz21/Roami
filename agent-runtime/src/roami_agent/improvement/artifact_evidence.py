"""Render pending deliverables outside the agent; reviewers receive immutable evidence only."""

import base64
import hashlib
import json

from roami_agent.improvement.contracts import digest, relative_file, require
from roami_agent.improvement.executors import private_json

FILES = {
    "DOC-03": ["source.pptx", "updated.pptx", "changes.md"],
    "DOC-05": ["previous-plan.json", "plan.md", "architecture.svg", "result.json"],
    "DEMO-01": ["index.html", "README.md"],
    "DEMO-02": ["index.html", "README.md"],
    "DEMO-05": ["index.html", "README.md"],
    "the-agent-company:hr-make-slides-introduce-leadership": ["leadership_intro.pptx"],
    "the-agent-company:ds-stock-analysis-slides": [
        "stock_analysis.pptx",
        "stock_analysis_script.md",
    ],
}

PROGRAM = r"""import base64,io,json,os,pathlib,socket,subprocess,sys,tempfile,time,urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright
spec=json.loads(sys.stdin.read());root=pathlib.Path('/workspace');images=[];texts=[]
def add(name,raw):
 image=Image.open(io.BytesIO(raw)).convert('RGB');image.thumbnail((1440,1000));out=io.BytesIO();image.save(out,format='JPEG',quality=78)
 data=out.getvalue()
 if len(data)>240000:raise ValueError('render image too large')
 images.append({'label':name,'mime':'image/jpeg','data':base64.b64encode(data).decode(),'width':image.width,'height':image.height})
with tempfile.TemporaryDirectory() as td:
 tmp=pathlib.Path(td);os.environ['HOME']=str(tmp);os.environ['TMPDIR']=str(tmp)
 for name in spec['files']:
  path=root/name
  if path.suffix=='.pptx':
   out=tmp/path.stem;out.mkdir();subprocess.run(['soffice','-env:UserInstallation=file://'+str(out/'profile'),'--headless','--convert-to','pdf','--outdir',str(out),str(path)],check=True,capture_output=True,timeout=60)
   pdf=out/(path.stem+'.pdf');subprocess.run(['pdftoppm','-scale-to','1440','-jpeg','-jpegopt','quality=78',str(pdf),str(out/'page')],check=True,capture_output=True,timeout=45)
   pages=sorted(out.glob('page-*.jpg'))
   if not 1<=len(pages)<=8:raise ValueError('unexpected page count')
   for i,page in enumerate(pages):add(name+' page '+str(i+1),page.read_bytes())
   result=subprocess.run(['pdftotext',str(pdf),'-'],check=True,capture_output=True,timeout=15);text=result.stdout.decode();texts.append({'label':name,'text':text[:12000],'truncated':len(text)>12000})
  elif path.suffix in {'.md','.json','.svg'}:
   text=path.read_text();texts.append({'label':name,'text':text[:14000],'truncated':len(text)>14000})
 if spec['web'] or 'architecture.svg' in spec['files']:
  proc=None;origin=None
  try:
   if spec['id']=='DEMO-02':
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();origin='http://127.0.0.1:'+str(port)
    proc=subprocess.Popen([sys.executable,'server.py'],env={**os.environ,'PORT':str(port)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(80):
     try:urllib.request.urlopen(origin+'/stats',timeout=.2);break
     except OSError:time.sleep(.1)
    else:raise ValueError('fixture server unavailable')
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking']);context=browser.new_context()
    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(('file:///workspace/','data:')+((origin+'/',) if origin else ())) else route.abort())
    page=context.new_page();page.set_default_timeout(5000)
    for width in ([390,1280] if spec['web'] else [1280]):
     page.set_viewport_size({'width':width,'height':900});name='index.html' if spec['web'] else 'architecture.svg';page.goto(origin+'/' if origin else 'file:///workspace/'+name,wait_until='load');page.wait_for_timeout(200);add(name+' width '+str(width),page.screenshot(full_page=False))
     if spec['web']:texts.append({'label':'rendered text '+str(width),'text':page.locator('body').inner_text()[:10000],'truncated':len(page.locator('body').inner_text())>10000})
    if spec['id']=='DEMO-02':
     file=page.get_by_test_id('csv-input');button=page.get_by_test_id('import')
     def submit():
      with page.expect_response(lambda response: response.request.method=='POST' and response.url==origin+'/import') as response:button.click()
      response.value.finished()
     def capture(label):
      page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
      add(label,page.screenshot());texts.append({'label':label,'text':page.locator('body').inner_text(),'truncated':False})
     file.set_input_files(str(root/'valid.csv'));submit();capture('valid result')
     file.set_input_files(str(root/'invalid.csv'))
     page.wait_for_function("() => !document.querySelector('[data-testid=import]').disabled || Boolean(document.querySelector('[data-testid=error]').textContent.trim())")
     if button.is_enabled():button.click()
     page.wait_for_function("() => Boolean(document.querySelector('[data-testid=error]').textContent.trim())")
     capture('missing column')
     file.set_input_files(str(root/'valid.csv'));submit()
     page.wait_for_function("() => Boolean(document.querySelector('[data-testid=error]').textContent.trim())")
     if not file.evaluate('e=>e.files.length===1'):raise ValueError('retry input unavailable')
     capture('retry with preserved input');submit();capture('recovered result')
    browser.close()
  finally:
   if proc is not None:proc.terminate();proc.wait(timeout=5)
print(json.dumps({'images':images,'texts':texts}))"""


async def collect_artifact_evidence(case, grade, root, executor):
    require(case["id"] in FILES, "RSI_ARTIFACT_REVIEW_UNSUPPORTED")
    workspace = root / ("stock-remote" if case["judge"]["kind"] == "company_stock" else "workspace")
    hashes = []
    for name in FILES[case["id"]]:
        path = relative_file(workspace, name)
        require(path.is_file() and path.stat().st_size <= 16_000_000, "RSI_ARTIFACT_UNAVAILABLE")
        hashes.append({"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    require(
        all(
            not e.get("path")
            or next((h["sha256"] for h in hashes if h["file"] == e["path"]), e.get("sha256"))
            == e.get("sha256")
            for e in grade.get("evidence", [])
        ),
        "RSI_ARTIFACT_EVIDENCE_CHANGED",
    )
    pack = json.loads(
        await executor.sandbox(
            workspace,
            PROGRAM,
            input=json.dumps(
                {
                    "files": FILES[case["id"]],
                    "web": case["id"].startswith("DEMO-"),
                    "id": case["id"],
                }
            ).encode(),
            timeout=180,
        )
    )
    require(isinstance(pack["images"], list) and 1 <= len(pack["images"]) <= 16)
    require(not any(t.get("truncated") for t in pack["texts"]), "RSI_ARTIFACT_EVIDENCE_TRUNCATED")
    require(
        all(
            hashlib.sha256(relative_file(workspace, h["file"]).read_bytes()).hexdigest()
            == h["sha256"]
            for h in hashes
        ),
        "RSI_ARTIFACT_EVIDENCE_CHANGED",
    )
    require(len(json.dumps(pack).encode()) <= 3_000_000, "RSI_ARTIFACT_EVIDENCE_TOO_LARGE")
    for item in pack["images"]:
        raw = base64.b64decode(item["data"], validate=True)
        item["sha256"] = hashlib.sha256(raw).hexdigest()
    grounding = {"hard_checks": grade["checks"]}
    if case["judge"]["kind"] == "company":
        state = json.loads((root / "company-snapshot.json").read_text())
        grounding["profiles"] = [
            {key: user.get(key) for key in ("name", "bio")} for user in state["final"]["users"]
        ]
    elif case["judge"]["kind"] == "company_stock":
        grounding["data_summary"] = json.loads(
            await executor.sandbox(
                workspace,
                "import io,base64,json,sys,pandas as pd;d=pd.read_csv(io.BytesIO(base64.b64decode(json.loads(sys.stdin.read())['golden'])));v=d.drop(columns=['Unnamed: 0','Date']);v['Return']=d.Close.pct_change();print(json.dumps({'rows':len(d),'start':d.Date.iloc[0],'end':d.Date.iloc[-1],'first_close':float(d.Close.iloc[0]),'last_close':float(d.Close.iloc[-1]),'statistics':v.describe().to_dict(),'correlation':v.corr().to_dict()},allow_nan=False))",
                input=json.dumps({"golden": case["judge"]["golden"]}).encode(),
            )
        )
    result = {
        "schema_version": 1,
        "renderer_image": executor.image_id,
        "instruction": case["prompt"],
        "artifacts": hashes,
        "grounding": grounding,
        **pack,
    }
    result["content_hash"] = digest(result)
    private_json(root / "artifact-evidence.json", result)
    return result
