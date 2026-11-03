// This standalone concept uses fixtures only; no task or model calls.
const root = document.documentElement;
const stage = document.querySelector('#stage');
const ui = {
  phase: 'running', selected: 'main', motion: true, autoplay: false, lastPhase: 0,
};
const members = [
  { id: 'main', name: 'Roami Main', role: '主 Agent', topic: '计划、协调、验收', x: 0, z: 0,
    detail: '复用你正在对话的 Roami Main，拆解目标、协调成员并汇总经过验收的结果。' },
  { id: 'frontend', name: '前端', executor: 'Codex', topic: '实现页面与交互', x: -4.1, z: 0.6,
    detail: '用 Codex 实现界面。追加要求回到原任务、原工作区和原供应商对话；完成回报还需要验收。' },
  { id: 'research', name: '研究', executor: 'Claude', topic: '梳理方案与约束', x: 3.9, z: 0.4,
    detail: '用 Claude 研究方案和约束。产物以任务版本关联，供下游读取，不把终端静止当成工作完成。' },
  { id: 'organize', name: '整理', executor: 'Roami', topic: '整理交付与材料', x: 0, z: 4.1,
    detail: '使用现有 Roami native Worker 与节点保存的模型配置，在自身能力范围内整理材料和交付物。' },
  { id: 'check', name: '验证', executor: 'Codex', topic: '等待验收标准', x: 0, z: -4.0,
    detail: '演示一个等待输入的成员。阻塞时停止工作动作；真实产品会显示缺少的输入和可以采取的下一步。' },
];
const phases = {
  dispatch: ['派发中', '蓝色光点从 Main 发往成员；只有确认开始执行后才进入运行状态。'],
  running: ['执行中', '角色敲击键盘，显示器轻微变化；运行状态来自当前任务。'],
  review: ['待验收', '结果回到 Main，角色停止敲击；成员回报成功之后仍然需要验收。'],
  done: ['已验收', '检查通过后短暂亮起绿色闭环，角色回到静止；结果和文件排在执行记录之前。'],
};
function status(member) {
  if (member.id === 'main') return { text: ui.phase === 'review' ? '验收中' : ui.phase === 'done' ? '已汇总' : '协调中', token: ui.phase === 'done' ? '--ok' : '--accent' };
  if (member.id === 'check' && ui.phase !== 'done') return { text: '等待输入', token: '--warn' };
  return {
    dispatch: { text: '待接收', token: '--accent' }, running: { text: '执行中', token: '--ok' },
    review: { text: '待验收', token: '--warn' }, done: { text: '已验收', token: '--ok' },
  }[ui.phase];
}
for (const member of members) {
  const row = document.createElement('button');
  row.type = 'button'; row.className = 'member'; row.dataset.member = member.id;
  const dot = document.createElement('i'); dot.className = 'status-dot'; dot.setAttribute('aria-hidden', 'true');
  const identity = document.createElement('span');
  const title = document.createElement('strong'); title.textContent = member.name;
  const subtitle = document.createElement('small'); subtitle.textContent = `${member.executor || '主 Agent'} · ${member.topic}`;
  const state = document.createElement('span'); state.className = 'state';
  identity.append(title, subtitle); row.append(dot, identity, state);
  row.addEventListener('click', () => select(member.id));
  document.querySelector('#members').append(row);
  const label = document.createElement('button');
  label.type = 'button'; label.className = 'workstation-label'; label.dataset.member = member.id;
  label.setAttribute('aria-label', `选择${member.name}工位`);
  const indicator = dot.cloneNode();
  label.append(indicator, document.createTextNode(member.executor ? `${member.executor} / ${member.name}` : member.name));
  label.addEventListener('click', () => select(member.id));
  document.querySelector('#labels').append(label);
  member.label = label;
}
function select(id) {
  ui.selected = id;
  const member = members.find(item => item.id === id);
  document.querySelector('#selection-role').textContent = member.role || `${member.executor} 成员`;
  document.querySelector('#selection-name').textContent = member.name;
  document.querySelector('#selection-detail').textContent = member.detail;
  syncDom(); window.dispatchEvent(new Event('studio-change'));
}
function syncDom() {
  document.querySelector('#phase-name').textContent = phases[ui.phase][0];
  document.querySelector('#phase-description').textContent = phases[ui.phase][1];
  document.querySelectorAll('[data-phase]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.phase === ui.phase)));
  for (const member of members) {
    const st = status(member);
    document.querySelectorAll(`[data-member="${member.id}"]`).forEach(node => {
      node.setAttribute('aria-pressed', String(member.id === ui.selected));
      node.style.setProperty('--status', `var(${st.token})`);
      node.querySelector('.state')?.replaceChildren(document.createTextNode(st.text));
    });
  }
}
function setPhase(phase) {
  ui.phase = phase; ui.lastPhase = performance.now(); syncDom();
  window.dispatchEvent(new Event('studio-change'));
}
document.querySelectorAll('[data-phase]').forEach(button => button.addEventListener('click', () => setPhase(button.dataset.phase)));
document.querySelector('#motion').addEventListener('click', event => {
  ui.motion = !ui.motion; event.currentTarget.setAttribute('aria-pressed', String(ui.motion));
  event.currentTarget.textContent = ui.motion ? '动画开' : '动画关';
  window.dispatchEvent(new Event('studio-change'));
});
document.querySelector('#autoplay').addEventListener('click', event => {
  ui.autoplay = !ui.autoplay; ui.lastPhase = performance.now();
  event.currentTarget.setAttribute('aria-pressed', String(ui.autoplay));
});
document.querySelector('#device').addEventListener('click', event => {
  const phone = root.dataset.size !== 'compact'; root.dataset.size = phone ? 'compact' : 'large';
  event.currentTarget.setAttribute('aria-pressed', String(phone));
});
document.querySelector('#theme').addEventListener('click', event => {
  const light = root.dataset.theme !== 'light'; root.dataset.theme = light ? 'light' : 'dark';
  event.currentTarget.setAttribute('aria-pressed', String(light));
  event.currentTarget.textContent = light ? '深色' : '浅色';
  window.dispatchEvent(new Event('studio-theme'));
});
document.addEventListener('pointerdown', event => { root.dataset.pointer = event.pointerType === 'touch' ? 'coarse' : 'fine'; });
if (new URLSearchParams(location.search).get('view') === 'phone') document.querySelector('#device').click();
syncDom();
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  document.querySelector('.proposal').dataset.tab = button.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
}));
document.querySelectorAll('[data-work]').forEach(button => button.addEventListener('click', () => {
  select(button.dataset.work);
  document.querySelector('.member-details').open = true;
  document.querySelector('#chat-selection').textContent = '已关联：' + members.find(item => item.id === button.dataset.work).name;
  document.querySelectorAll('[data-chat-member]').forEach(item => item.dataset.selected = String(item.dataset.chatMember === button.dataset.work));
}));
document.querySelectorAll('[data-reply]').forEach(button => button.addEventListener('click', () => {
  document.querySelector('#chat-draft').value = '@' + button.dataset.reply + ' ';
  document.querySelector('#chat-draft').focus();
}));
document.querySelector('#chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const draft = document.querySelector('#chat-draft');
  if (!draft.value.trim()) return;
  const article = document.createElement('article'), author = document.createElement('strong'), text = document.createElement('p');
  author.textContent = '你 · 演示消息'; text.textContent = draft.value;
  article.append(author, text); document.querySelector('#chat-messages').append(article); draft.value = '';
});

try {
  const THREE = await import('https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js');
  createStudio(THREE);
} catch (error) {
  document.querySelector('#scene-message').textContent = '三维场景暂不可用，请通过成员列表查看；重新打开页面可重试。';
  document.querySelector('#labels').hidden = true;
  root.dataset.scene = 'fallback';
  console.warn('Studio concept could not initialize', error);
}

function createStudio(T) {
  const token = name => getComputedStyle(root).getPropertyValue(name).trim();
  const color = name => new T.Color(token(name));
  const lightTheme = () => root.dataset.theme === 'light';
  const lightColor = () => color(lightTheme() ? '--bg-container' : '--text-bright');
  const scene = new T.Scene();
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, root.dataset.size === 'compact' ? 1 : 1.5));
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = .95;
  renderer.shadowMap.enabled = root.dataset.size !== 'compact';
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  stage.prepend(renderer.domElement);
  renderer.domElement.setAttribute('aria-hidden', 'true');
  const camera = new T.OrthographicCamera(-10, 10, 8, -8, .1, 100);
  camera.position.set(11, 13, 16); camera.lookAt(0, .4, 0);
  scene.add(new T.HemisphereLight(lightColor(), color('--bg-base'), 2.4));
  const sun = new T.DirectionalLight(lightColor(), 3);
  sun.position.set(-5, 12, 6); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, near: .5, far: 35 });
  sun.shadow.bias = -.001; scene.add(sun);
  const materials = [];
  function material(name, options = {}) {
    const mat = new T.MeshStandardMaterial({ color: color(name), roughness: .65, metalness: .12, ...options });
    mat.userData.token = name; materials.push(mat); return mat;
  }
  const floorMat = material('--bg-container');
  const baseMat = material('--bg-elevated');
  const edgeMat = material('--border');
  const deskMat = material('--border');
  const paleMat = material('--text-bright');
  const darkMat = material('--bg-base');
  const visorMat = material('--bg-base', { metalness: .45, roughness: .24 });
  const accentMat = material('--accent', { emissive: color('--accent'), emissiveIntensity: .25 });
  const boxGeometry = new T.BoxGeometry(1, 1, 1);
  const sphereGeometry = new T.SphereGeometry(1, 12, 8);
  function box(parent, dimensions, position, mat, bevel = false) {
    let geometry = boxGeometry;
    if (bevel) {
      const [w, h, d] = dimensions, r = Math.min(w, h, d) * .22;
      const shape = new T.Shape();
      shape.moveTo(-w / 2 + r, -h / 2); shape.lineTo(w / 2 - r, -h / 2);
      shape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
      shape.lineTo(w / 2, h / 2 - r); shape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
      shape.lineTo(-w / 2 + r, h / 2); shape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
      shape.lineTo(-w / 2, -h / 2 + r); shape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
      geometry = new T.ExtrudeGeometry(shape, { depth: d, bevelEnabled: true, bevelThickness: r * .35, bevelSize: r * .25, bevelSegments: 2, steps: 1, curveSegments: 4 });
      geometry.translate(0, 0, -d / 2);
    }
    const mesh = new T.Mesh(geometry, mat);
    if (!bevel) mesh.scale.set(...dimensions);
    mesh.position.set(...position); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }
  function sphere(parent, radius, position, mat) {
    const mesh = new T.Mesh(sphereGeometry, mat); mesh.scale.setScalar(radius); mesh.position.set(...position); parent.add(mesh); return mesh;
  }
  function cylinder(parent, radius, height, position, mat, sides = 32) {
    const mesh = new T.Mesh(new T.CylinderGeometry(radius, radius, height, sides), mat);
    mesh.position.set(...position); mesh.receiveShadow = true; mesh.castShadow = true; parent.add(mesh); return mesh;
  }
  const floor = cylinder(scene, 6.85, .22, [0, -.22, 0], floorMat, 6);
  floor.rotation.y = Math.PI / 6;
  const floorEdge = cylinder(scene, 6.9, .06, [0, -.37, 0], edgeMat, 6); floorEdge.rotation.y = Math.PI / 6;
  const grid = new T.GridHelper(11.2, 14, color('--border'), color('--border-subtle'));
  grid.position.y = -.09; grid.material.transparent = true; grid.material.opacity = .3; scene.add(grid);

  const rigs = [];
  for (const member of members) {
    const group = new T.Group(); group.position.set(member.x, 0, member.z); scene.add(group);
    group.userData.member = member.id;
    const main = member.id === 'main';
    if (main) group.scale.setScalar(1.13);
    cylinder(group, main ? 1.35 : 1.12, .13, [0, .02, 0], baseMat);
    const stMat = material(status(member).token, { emissive: color(status(member).token), emissiveIntensity: .28 });
    const halo = new T.Mesh(new T.TorusGeometry(main ? 1.4 : 1.17, .018, 6, 64), stMat);
    halo.rotation.x = Math.PI / 2; halo.position.y = .12; group.add(halo);
    box(group, [1.85, .13, 1], [0, .92, -.4], deskMat, true);
    box(group, [1.65, .035, .84], [0, 1.01, -.4], baseMat);
    box(group, [.09, .76, .65], [-.76, .49, -.4], edgeMat);
    box(group, [.09, .76, .65], [.76, .49, -.4], edgeMat);
    box(group, [.1, .35, .1], [0, 1.2, -.73], edgeMat);
    box(group, [1.18, .7, .1], [0, 1.65, -.76], visorMat, true);
    box(group, [1.06, .56, .024], [0, 1.65, -.695], darkMat);
    const bars = [];
    for (let i = 0; i < 4; i++) bars.push(box(group, [.45 + i % 2 * .3, .026, .025], [-.12 + i % 2 * .05, 1.8 - i * .1, -.67], i === 0 ? stMat : edgeMat));
    box(group, [.7, .04, .28], [0, 1.03, -.15], edgeMat, true);
    for (let i = 0; i < 4; i++) box(group, [.56, .009, .014], [0, 1.058, -.25 + i * .065], baseMat);
    cylinder(group, .43, .12, [0, .43, .6], edgeMat);
    box(group, [.7, .5, .12], [0, .7, 1.02], baseMat, true);
    cylinder(group, .07, .28, [0, .23, .6], edgeMat);
    const robot = new T.Group(); robot.position.set(0, 0, .58); group.add(robot);
    box(robot, [.53, .48, .42], [0, .83, 0], paleMat, true);
    box(robot, [.27, .13, .045], [0, .87, .23], stMat, true);
    const head = new T.Group(); head.position.set(0, 1.36, 0); robot.add(head);
    box(head, [.77, .57, .58], [0, 0, 0], paleMat, true);
    box(head, [.61, .25, .025], [0, -.01, .304], visorMat, true);
    const eyes = [];
    for (const x of [-.14, .14]) eyes.push(box(head, [.07, .085, .025], [x, 0, .33], stMat, true));
    cylinder(head, .027, .19, [0, .4, 0], edgeMat, 8);
    sphere(head, .064, [0, .51, 0], stMat);
    for (const x of [-.16, .16]) box(robot, [.18, .25, .2], [x, .5, .03], edgeMat, true);
    const hands = [];
    for (const x of [-.39, .39]) {
      const arm = new T.Group(); arm.position.set(x, .98, -.04); robot.add(arm);
      box(arm, [.14, .15, .37], [0, 0, -.12], paleMat, true);
      hands.push(sphere(arm, .09, [0, 0, -.35], stMat));
    }
    const selection = new T.Mesh(new T.TorusGeometry(main ? 1.5 : 1.27, .028, 8, 64), accentMat);
    selection.rotation.x = Math.PI / 2; selection.position.y = .13; group.add(selection);
    const hit = new T.Mesh(new T.CylinderGeometry(1.2, 1.2, 2.3, 12), new T.MeshBasicMaterial({ visible: false }));
    hit.position.y = 1; hit.userData.member = member.id; group.add(hit);
    rigs.push({ member, group, robot, head, hands, eyes, bars, halo, selection, stMat, hit });
  }
  const routes = [];
  for (const member of members.slice(1)) {
    const from = new T.Vector3(0, .18, 0), to = new T.Vector3(member.x, .18, member.z);
    const curve = new T.QuadraticBezierCurve3(from, new T.Vector3(member.x * .4 - member.z * .15, .26, member.z * .4 + member.x * .15), to);
    const line = new T.Line(new T.BufferGeometry().setFromPoints(curve.getPoints(40)), new T.LineBasicMaterial({ color: color('--border'), transparent: true, opacity: .7 }));
    scene.add(line);
    const particleMat = material('--accent', { emissive: color('--accent'), emissiveIntensity: .5 });
    const particles = [0, 1, 2].map(() => sphere(scene, .045, [0, .2, 0], particleMat));
    routes.push({ member, curve, particles, particleMat });
  }
  const raycaster = new T.Raycaster();
  renderer.domElement.addEventListener('pointerup', event => {
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new T.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
    const hit = raycaster.intersectObjects(rigs.map(rig => rig.hit))[0];
    if (hit) select(hit.object.userData.member);
  });
  let disposed = false, elapsed = 0, lastFrame = 0;
  function resize() {
    if (disposed) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio, root.dataset.size === 'compact' ? 1 : 1.5));
    renderer.setSize(w, h, false);
    const aspect = w / h, halfHeight = Math.max(6.3, 8.5 / aspect);
    camera.left = -halfHeight * aspect; camera.right = halfHeight * aspect;
    camera.top = halfHeight; camera.bottom = -halfHeight; camera.updateProjectionMatrix();
    render();
  }
  function updateMaterials() {
    paleMat.userData.token = lightTheme() ? '--border' : '--text-bright';
    darkMat.userData.token = visorMat.userData.token = lightTheme() ? '--text-bright' : '--bg-base';
    floorMat.userData.token = lightTheme() ? '--border-subtle' : '--bg-container';
    deskMat.userData.token = lightTheme() ? '--text-dim' : '--border';
    for (const mat of materials) {
      mat.color.copy(color(mat.userData.token));
      if (mat.emissiveIntensity > 0) mat.emissive.copy(mat.color);
    }
    const fill = scene.children.find(item => item.isHemisphereLight);
    fill.color.copy(lightColor()); fill.intensity = lightTheme() ? 1.6 : 2.4;
    sun.intensity = lightTheme() ? 1.8 : 3;
    sun.color.copy(lightColor());
    for (const route of routes) route.particleMat.color.copy(color(ui.phase === 'done' ? '--ok' : ui.phase === 'review' ? '--warn' : '--accent'));
    render();
  }
  function render() {
    if (disposed) return;
    for (const rig of rigs) {
      const { member } = rig, active = ui.phase === 'running' && member.id !== 'check';
      const motion = ui.motion && active;
      rig.head.rotation.y = motion ? Math.sin(elapsed * 1.1 + rig.member.x) * .1 : 0;
      rig.robot.position.y = motion ? Math.sin(elapsed * 2.2 + rig.member.z) * .016 : 0;
      rig.hands.forEach((hand, i) => { hand.position.y = motion ? Math.sin(elapsed * 11 + i * Math.PI) * .04 : 0; });
      rig.bars.forEach((bar, i) => { bar.scale.x = motion ? .65 + Math.sin(elapsed * 2 + i) * .22 : 1; });
      rig.selection.visible = ui.selected === member.id;
      rig.stMat.color.copy(color(status(member).token)); rig.stMat.emissive.copy(rig.stMat.color);
      const blink = motion && Math.sin(elapsed * .7 + member.z) > .996;
      rig.eyes.forEach(eye => { eye.scale.y = blink ? .15 : 1; });
      const label = new T.Vector3(member.x, member.id === 'main' ? 2.6 : 2.35, member.z).project(camera);
      member.label.style.left = `${(label.x + 1) * stage.clientWidth / 2}px`;
      member.label.style.top = `${(1 - label.y) * stage.clientHeight / 2}px`;
    }
    for (const route of routes) route.particles.forEach((particle, i) => {
      particle.visible = ui.motion && route.member.id !== 'check' && ['dispatch', 'review'].includes(ui.phase);
      let progress = (elapsed * .38 + i / 3) % 1;
      if (ui.phase === 'review') progress = 1 - progress;
      particle.position.copy(route.curve.getPoint(progress));
    });
    renderer.render(scene, camera);
    root.dataset.frames = String(renderer.info.render.frame);
  }
  function animate(time) {
    if (document.hidden) return;
    const interval = root.dataset.size === 'compact' ? 1000 / 30 : 1000 / 60;
    if (lastFrame && time - lastFrame < interval - 1) return;
    const delta = lastFrame ? Math.min((time - lastFrame) / 1000, .1) : 0;
    lastFrame = time; elapsed += delta;
    if (ui.autoplay && time - ui.lastPhase > 4500) {
      const order = Object.keys(phases); setPhase(order[(order.indexOf(ui.phase) + 1) % order.length]);
    }
    if (ui.motion && ui.phase !== 'done' || ui.autoplay) render();
  }
  const observer = new ResizeObserver(resize); observer.observe(stage);
  function visibility() { lastFrame = 0; renderer.setAnimationLoop(document.hidden ? null : animate); }
  function change() { updateMaterials(); render(); }
  window.addEventListener('studio-change', change);
  window.addEventListener('studio-theme', updateMaterials);
  document.addEventListener('visibilitychange', visibility);
  renderer.domElement.addEventListener('webglcontextlost', event => {
    event.preventDefault(); renderer.setAnimationLoop(null);
    document.querySelector('#scene-message').hidden = false;
    document.querySelector('#scene-message').textContent = '三维场景暂停，请通过成员列表查看。';
    root.dataset.scene = 'context-lost';
  });
  window.addEventListener('pagehide', () => {
    disposed = true; renderer.setAnimationLoop(null); observer.disconnect();
    window.removeEventListener('studio-change', change); window.removeEventListener('studio-theme', updateMaterials);
    document.removeEventListener('visibilitychange', visibility);
    const geometries = new Set(), mats = new Set();
    scene.traverse(object => {
      if (object.geometry) geometries.add(object.geometry);
      if (object.material) (Array.isArray(object.material) ? object.material : [object.material]).forEach(mat => mats.add(mat));
    });
    geometries.forEach(geometry => geometry.dispose()); mats.forEach(mat => mat.dispose()); renderer.dispose();
  }, { once: true });
  document.querySelector('#scene-message').hidden = true;
  root.dataset.scene = 'ready';
  updateMaterials(); resize(); renderer.setAnimationLoop(animate);
}
