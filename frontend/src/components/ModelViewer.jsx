import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

export default function ModelViewer({ model }) {
  const hostRef = useRef(null)

  useEffect(() => {
    const host = hostRef.current
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0xf3f4f6)
    const camera = new THREE.PerspectiveCamera(45, host.clientWidth / host.clientHeight, 0.1, 10000)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(host.clientWidth, host.clientHeight)
    host.appendChild(renderer.domElement)

    scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 1.2))
    scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const sun = new THREE.DirectionalLight(0xffffff, 1.5)
    sun.position.set(1, 2, 1.5)
    scene.add(sun)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    new GLTFLoader().load(model.url, (gltf) => {
      const obj = gltf.scene
      obj.traverse((o) => {
        if (o.isMesh) {
          if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals()
          o.material = new THREE.MeshStandardMaterial({ color: 0x9aa4b2, metalness: 0.1, roughness: 0.6, flatShading: true })
          o.add(new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 25),
            new THREE.LineBasicMaterial({ color: 0x334155 })))
        }
      })
      scene.add(obj)
      const box = new THREE.Box3().setFromObject(obj)
      const size = box.getSize(new THREE.Vector3()).length()
      const center = box.getCenter(new THREE.Vector3())
      camera.position.copy(center).add(new THREE.Vector3(size * 0.7, size * 0.6, size * 0.9))
      camera.near = size / 100; camera.far = size * 100; camera.updateProjectionMatrix()
      controls.target.copy(center)
      const grid = new THREE.GridHelper(size * 2, 20, 0xcccccc, 0xe5e7eb)
      grid.position.y = box.min.y
      scene.add(grid)
    })

    let frame
    const tick = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(tick) }
    tick()
    const ro = new ResizeObserver(() => {
      camera.aspect = host.clientWidth / host.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(host.clientWidth, host.clientHeight)
    })
    ro.observe(host)
    return () => {
      cancelAnimationFrame(frame); ro.disconnect(); controls.dispose(); renderer.dispose()
      host.removeChild(renderer.domElement)
    }
  }, [model.url])

  const spec = model.spec || {}
  return (
    <div className="model">
      <div className="recon-banner">⚠ {model.label}</div>
      <div className="model-canvas" ref={hostRef} />
      <div className="model-meta small">
        <b>Method:</b> {model.method} · <b>Units:</b> {spec.units}
        {spec.evidence?.length > 0 && (
          <details>
            <summary>{spec.evidence.length} dimensions read from the drawing</summary>
            <ul>{spec.evidence.map((e, i) => <li key={i}>{e.dim} = {e.value} (p{e.page}) {e.note}</li>)}</ul>
          </details>
        )}
      </div>
    </div>
  )
}
