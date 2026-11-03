import * as T from 'three'
import { swarmStateToken, type StudioNode } from '../swarm-protocol'

type Rig = { node: StudioNode; group: T.Group; robot: T.Group; head: T.Group; hands: T.Object3D[]; bars: T.Mesh[]; status: T.MeshStandardMaterial; selected: T.Mesh; hit: T.Mesh; position: T.Vector3 }
export function createStudio(host: HTMLDivElement, labels: HTMLDivElement, select: (id: string) => void, coarse: boolean, onLost: () => void) {
  const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const color = (name: string) => new T.Color(css(name))
  const light = () => color('--text-bright').getHSL({ h: 0, s: 0, l: 0 }).l < .5
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio, coarse ? 1 : 1.5))
  renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = .95
  renderer.shadowMap.enabled = !coarse; renderer.shadowMap.type = T.PCFSoftShadowMap
  renderer.domElement.setAttribute('aria-hidden', 'true'); host.prepend(renderer.domElement)
  const scene = new T.Scene(), camera = new T.OrthographicCamera(-10, 10, 7, -7, .1, 100)
  camera.position.set(11, 13, 16); camera.lookAt(0, .4, 0)
  const fill = new T.HemisphereLight(color('--text-bright'), color('--bg-base'), 2.4)
  const sun = new T.DirectionalLight(color('--text-bright'), 3)
  sun.position.set(-5, 12, 6); sun.castShadow = !coarse; sun.shadow.mapSize.set(1024, 1024)
  Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: .5, far: 40 }); sun.shadow.bias = -.001
  scene.add(fill, sun)
  const materials: T.Material[] = [], geometries = new Set<T.BufferGeometry>()
  const mat = (token: string, emissive = false) => {
    const material = new T.MeshStandardMaterial({ color: color(token), roughness: .65, metalness: .12, ...(emissive ? { emissive: color(token), emissiveIntensity: .25 } : {}) })
    material.userData.token = token; materials.push(material); return material
  }
  const floorMat = mat('--bg-container'), deskMat = mat('--border'), bodyMat = mat('--text-bright'), darkMat = mat('--bg-base'), edgeMat = mat('--border'), baseMat = mat('--bg-elevated'), accentMat = mat('--accent', true)
  const boxGeo = new T.BoxGeometry(1, 1, 1), ballGeo = new T.SphereGeometry(1, 12, 8), ringGeo = new T.TorusGeometry(1.15, .02, 6, 48)
  geometries.add(boxGeo); geometries.add(ballGeo); geometries.add(ringGeo)
  const mesh = (parent: T.Object3D, geometry: T.BufferGeometry, material: T.Material, position: number[], scale?: number[]) => {
    geometries.add(geometry); const value = new T.Mesh(geometry, material); value.position.set(position[0], position[1], position[2]); if (scale) value.scale.set(scale[0], scale[1], scale[2]); value.castShadow = true; value.receiveShadow = true; parent.add(value); return value
  }
  const box = (parent: T.Object3D, size: number[], at: number[], material: T.Material) => mesh(parent, boxGeo, material, at, size)
  const rounded = (parent: T.Object3D, size: number[], at: number[], material: T.Material) => {
    const [w, h, d] = size, r = Math.min(w, h, d) * .2, shape = new T.Shape()
    shape.moveTo(-w / 2 + r, -h / 2); shape.lineTo(w / 2 - r, -h / 2); shape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r)
    shape.lineTo(w / 2, h / 2 - r); shape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2); shape.lineTo(-w / 2 + r, h / 2)
    shape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r); shape.lineTo(-w / 2, -h / 2 + r); shape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2)
    const geometry = new T.ExtrudeGeometry(shape, { depth: d, bevelEnabled: true, bevelThickness: r * .25, bevelSize: r * .2, bevelSegments: 2, steps: 1, curveSegments: 4 })
    geometry.translate(0, 0, -d / 2); return mesh(parent, geometry, material, at)
  }
  const floor = mesh(scene, new T.CylinderGeometry(6.9, 6.9, .22, 6), floorMat, [0, -.2, 0]); floor.rotation.y = Math.PI / 6
  let rigs: Rig[] = [], selected = 'main', motion = true, reduced = false, disposed = false, lost = false, elapsed = 0, lastFrame = 0, eventUntil = 0
  const routes: { id: string; curve: T.QuadraticBezierCurve3; particles: T.Mesh[]; reverse: boolean }[] = []
  const transport = mat('--accent', true)
  function build(node: StudioNode, index: number, total: number): Rig {
    const position = new T.Vector3()
    if (!node.main) {
      const order = [Math.PI, 0, Math.PI / 2, -Math.PI / 2]
      const memberIndex = Math.max(0, index - 1)
      const angle = total <= 4 ? order[memberIndex] : memberIndex * Math.PI * 2 / Math.min(total, 12)
      const radius = total <= 4 ? 4.1 : index <= 12 ? 4.5 : 7.5
      position.set(Math.cos(angle) * radius, 0, Math.sin(angle) * radius)
    }
    const group = new T.Group(); group.position.copy(position); scene.add(group); if (node.main) group.scale.setScalar(1.13)
    const status = mat(swarmStateToken(node.state), true)
    const ring = mesh(group, ringGeo, status, [0, .1, 0]); ring.rotation.x = Math.PI / 2
    const selectedRing = mesh(group, ringGeo, accentMat, [0, .12, 0], [1.1, 1.1, 1.1]); selectedRing.rotation.x = Math.PI / 2
    rounded(group, [1.85, .13, 1], [0, .92, -.4], deskMat)
    box(group, [.1, .76, .65], [-.76, .49, -.4], edgeMat); box(group, [.1, .76, .65], [.76, .49, -.4], edgeMat)
    box(group, [.1, .35, .1], [0, 1.2, -.73], edgeMat); rounded(group, [1.18, .7, .1], [0, 1.65, -.76], darkMat)
    const bars = Array.from({ length: 4 }, (_, i) => box(group, [.45 + i % 2 * .3, .026, .025], [-.12, 1.8 - i * .1, -.69], i === 0 ? status : edgeMat))
    box(group, [.7, .04, .28], [0, 1.03, -.15], edgeMat)
    rounded(group, [.7, .5, .12], [0, .7, 1.02], baseMat)
    const robot = new T.Group(); robot.position.set(0, 0, .58); group.add(robot)
    rounded(robot, [.53, .48, .42], [0, .83, 0], bodyMat)
    const head = new T.Group(); head.position.y = 1.36; robot.add(head)
    rounded(head, [.77, .57, .58], [0, 0, 0], bodyMat); rounded(head, [.61, .25, .025], [0, -.01, .304], darkMat)
    for (const x of [-.14, .14]) box(head, [.07, .085, .025], [x, 0, .33], status)
    box(head, [.03, .19, .03], [0, .4, 0], edgeMat); mesh(head, ballGeo, status, [0, .51, 0], [.064, .064, .064])
    for (const x of [-.16, .16]) box(robot, [.18, .25, .2], [x, .5, .03], edgeMat)
    const hands = [-.39, .39].map(x => rounded(robot, [.14, .15, .37], [x, .98, -.16], bodyMat))
    const invisible = new T.MeshBasicMaterial({ visible: false }); materials.push(invisible)
    const hit = mesh(group, new T.CylinderGeometry(1.2, 1.2, 2.3, 12), invisible, [0, 1, 0]); hit.userData.id = node.id
    if (!node.main) {
      const curve = new T.QuadraticBezierCurve3(new T.Vector3(0, .18, 0), new T.Vector3(position.x * .4 - position.z * .15, .24, position.z * .4), new T.Vector3(position.x, .18, position.z))
      const particles = [0, 1, 2].map(() => mesh(scene, ballGeo, transport, [0, .2, 0], [.045, .045, .045]))
      routes.push({ id: node.id, curve, particles, reverse: false })
    }
    return { node, group, robot, head, hands, bars, status, selected: selectedRing, hit, position }
  }
  function render() {
    if (disposed || lost) return
    for (const rig of rigs) {
      const active = motion && !reduced && ['running', 'preparing'].includes(rig.node.state)
      rig.head.rotation.y = active ? Math.sin(elapsed * 1.1 + rig.position.x) * .1 : 0
      rig.robot.position.y = active ? Math.sin(elapsed * 2.2 + rig.position.z) * .016 : 0
      rig.hands.forEach((hand, i) => hand.position.y = .98 + (active ? Math.sin(elapsed * 11 + i * Math.PI) * .035 : 0))
      rig.bars.forEach((bar, i) => bar.scale.x = active ? .65 + Math.sin(elapsed * 2 + i) * .22 : 1)
      rig.selected.visible = rig.node.id === selected; rig.status.color.copy(color(swarmStateToken(rig.node.state))); rig.status.emissive.copy(rig.status.color)
      const label = labels.querySelector<HTMLElement>(`[data-studio-id="${rig.node.id}"]`)
      if (label) { const point = rig.position.clone().add(new T.Vector3(0, 2.4, 0)).project(camera); label.style.left = `${(point.x + 1) * host.clientWidth / 2}px`; label.style.top = `${(1 - point.y) * host.clientHeight / 2}px` }
    }
    for (const route of routes) route.particles.forEach((particle, i) => { particle.visible = motion && !reduced && performance.now() < eventUntil; const p = (elapsed * .8 + i / 3) % 1; particle.position.copy(route.curve.getPoint(route.reverse ? 1 - p : p)) })
    renderer.render(scene, camera)
  }
  function animate(time: number) {
    if (time - lastFrame < (coarse ? 1000 / 30 : 1000 / 60) - 1) return
    elapsed += lastFrame ? Math.min((time - lastFrame) / 1000, .1) : 0; lastFrame = time; render(); schedule()
  }
  function schedule() {
    const active = motion && !reduced && rigs.some(rig => ['running', 'preparing'].includes(rig.node.state))
    renderer.setAnimationLoop(!document.hidden && host.clientWidth > 0 && host.clientHeight > 0 && !lost && (active || motion && !reduced && performance.now() < eventUntil) ? animate : null)
  }
  function resize() {
    if (disposed) return
    if (!host.clientWidth || !host.clientHeight) { schedule(); return }
    renderer.setSize(host.clientWidth, host.clientHeight, false)
    const aspect = host.clientWidth / host.clientHeight, span = rigs.length > 13 ? 12 : 8.5, half = Math.max(span * .74, span / aspect)
    camera.left = -half * aspect; camera.right = half * aspect; camera.top = half; camera.bottom = -half; camera.updateProjectionMatrix(); render(); schedule()
  }
  function theme() {
    bodyMat.userData.token = light() ? '--border' : '--text-bright'; darkMat.userData.token = light() ? '--text-bright' : '--bg-base'
    floorMat.userData.token = light() ? '--border-subtle' : '--bg-container'; deskMat.userData.token = light() ? '--text-dim' : '--border'
    for (const material of materials) if (material instanceof T.MeshStandardMaterial) { material.color.copy(color(material.userData.token)); if (material.emissiveIntensity) material.emissive.copy(material.color) }
    fill.color.copy(color(light() ? '--bg-container' : '--text-bright')); sun.color.copy(fill.color); fill.intensity = light() ? 1.6 : 2.4; sun.intensity = light() ? 1.8 : 3; render()
  }
  const observer = new ResizeObserver(resize); observer.observe(host)
  const themeObserver = new MutationObserver(theme); themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'data-theme'] })
  const visibility = () => { lastFrame = 0; render(); schedule() }; document.addEventListener('visibilitychange', visibility)
  const raycaster = new T.Raycaster(); let down: { x: number; y: number } | null = null
  const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY } }
  const pointerUp = (event: PointerEvent) => { if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 8) return; const r = renderer.domElement.getBoundingClientRect(); raycaster.setFromCamera(new T.Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera); const hit = raycaster.intersectObjects(rigs.map(rig => rig.hit))[0]; if (hit) select(String(hit.object.userData.id)) }
  renderer.domElement.addEventListener('pointerdown', pointerDown); renderer.domElement.addEventListener('pointerup', pointerUp)
  const contextLost = (event: Event) => { event.preventDefault(); lost = true; schedule(); onLost() }; renderer.domElement.addEventListener('webglcontextlost', contextLost)
  return {
    update(nodes: StudioNode[]) {
      const shown = nodes.slice(0, 24)
      if (shown.map(node => node.id).join() !== rigs.map(rig => rig.node.id).join()) {
        const keep = new Set(shown.map(node => node.id))
        for (const rig of rigs.filter(item => !keep.has(item.node.id))) {
          scene.remove(rig.group)
          rig.group.traverse(object => { if (object instanceof T.Mesh && !([boxGeo, ballGeo, ringGeo] as T.BufferGeometry[]).includes(object.geometry)) { object.geometry.dispose(); geometries.delete(object.geometry) } })
          for (const material of [rig.status, rig.hit.material as T.Material]) { material.dispose(); const index = materials.indexOf(material); if (index >= 0) materials.splice(index, 1) }
          const index = routes.findIndex(route => route.id === rig.node.id)
          if (index >= 0) { for (const particle of routes[index].particles) scene.remove(particle); routes.splice(index, 1) }
        }
        const previous = new Map(rigs.filter(rig => keep.has(rig.node.id)).map(rig => [rig.node.id, rig]))
        rigs = shown.map((node, i) => { const rig = previous.get(node.id) || build(node, shown[0]?.main ? i : i + 1, shown.length - (shown[0]?.main ? 1 : 0)); rig.node = node; return rig })
        floor.scale.setScalar(shown.length > 13 ? 1.6 : 1)
      } else for (const rig of rigs) { const next = shown.find(node => node.id === rig.node.id)!; if (next.state !== rig.node.state && !document.hidden) { eventUntil = performance.now() + 650; const route = routes.find(item => item.id === next.id); if (route) route.reverse = ['verifying', 'waiting_user', 'succeeded', 'failed'].includes(next.state) } rig.node = next }
      theme(); resize(); schedule()
    },
    select(id: string) { selected = id; render() },
    motion(value: boolean, reduce: boolean) { motion = value; reduced = reduce; render(); schedule() },
    dispose() { disposed = true; renderer.setAnimationLoop(null); observer.disconnect(); themeObserver.disconnect(); document.removeEventListener('visibilitychange', visibility); renderer.domElement.removeEventListener('pointerdown', pointerDown); renderer.domElement.removeEventListener('pointerup', pointerUp); renderer.domElement.removeEventListener('webglcontextlost', contextLost); geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); renderer.dispose(); renderer.domElement.remove() },
  }
}
