import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { CLASS_META } from '@/config/constants';
import type { Facility, FireEvent } from '@/types/domain';
import { capByFrp, clusterEllipse, toEnu,
  type Detection } from '@/features/scene/sceneData';
import { buildEllipseLine, buildHotspotField, buildPlume,
  disposeSharedTexture, type HotspotField } from '@/features/scene/threeBuilders';
import { buildLabelSprite, buildOsmScene, buildHaloLabel,
  pickBuilding, type BuildingPick, type SceneContext } from '@/features/scene/osmScene';
import { CARTO } from '@/features/scene/cartography';
import { pixelVariance, shouldRenderSize, UNIFORM_RASTER_VARIANCE, type GLDiag } from './glSelfCheck';

const UNIT = 100; // 1 scene unit = 100 m
const HAZ_HEIGHT: Record<string, number> = { 'G-III': 6, 'G-II': 4, 'G-I': 2.5 };
const RING_ALPHA = [0.4, 0.3, 0.2];

interface ThreeSceneProps {
  ev: FireEvent;
  facilities: Facility[];
  /** Per-detection cloud (capped) from the live buffer; null = centroid mode. */
  detections?: Detection[] | null;
  /** null = latest; epoch ms = hide detections acquired after t. Read via ref each frame. */
  replayT?: number | null;
  /** Live OSM context (source "osm-overpass" mounts real surroundings). */
  osm?: SceneContext | null;
  /** Anti-confusion callout at the top-FRP hotspot (scene units). */
  callout?: { text: string; x: number; z: number } | null;
  /** T9 hover provenance (pure ray→ground-plane math — no pick meshes). */
  onHover?: (pick: BuildingPick | null, cx: number, cy: number) => void;
  /** T9 truth chip: OSM mesh count from the built group. */
  onOsmStats?: (s: { meshes: number }) => void;
  /** T9 scale bar / north arrow: camera distance (units) + yaw (deg), 250 ms. */
  onCamera?: (distUnits: number, yawDeg: number) => void;
  /** T10 GL rescue ladder: uniform raster / context lost / frozen frames. */
  onGlDead?: (reason: string) => void;
  /** T15: frame-2 self-check PASSED — the shell may clear the persisted pin. */
  onGlAlive?: () => void;
  /** T15 GL DIAG feed (throttled 250 ms). */
  onGlDiag?: (d: GLDiag) => void;
}

/** Three.js incident scene — used only where WebGL actually rasterizes.
 *  With detections: one additive sprite per FIRMS detection + 2σ ellipse +
 *  illustrative plume + replay; without: honest centroid mode. */
export function ThreeScene({ ev, facilities, detections, replayT, osm, callout,
  onHover, onOsmStats, onCamera, onGlDead, onGlAlive, onGlDiag }: ThreeSceneProps) {
  const mount = useRef<HTMLDivElement>(null);
  // Replay is scrubbed at high frequency — feed it to the render loop through a
  // ref so the WebGL context is never torn down for a slider drag.
  const replayRef = useRef<number | null>(replayT ?? null);
  replayRef.current = replayT ?? null;

  useEffect(() => {
    if (!mount.current) return;
    // T15: the renderer OWNS its context (an externally-supplied one can drop
    // attributes) and the paint ban holds at three layers — opaque alpha:false +
    // clear-alpha 1 + dark CSS on canvas element / dialog body / dialog panel.
    // A never-presented frame can therefore only ever read as dark ground.
    const canvas = document.createElement('canvas');
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.background = `#${CARTO.ground.toString(16).padStart(6, '0')}`; // paint-ban layer 1
    const renderer = new THREE.WebGLRenderer({
      canvas, alpha: false, antialias: true,
      powerPreference: 'high-performance', preserveDrawingBuffer: false,
    });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    renderer.setClearColor(new THREE.Color(CARTO.ground), 1);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.current.appendChild(renderer.domElement);

    // T10 GL rescue ladder — context loss is reported, never silently swallowed.
    let glDead = false;
    const die = (reason: string) => {
      if (!glDead) { glDead = true; onGlDead?.(reason); }
    };
    const onContextLost = (e: Event) => { e.preventDefault(); die('context lost'); };
    renderer.domElement.addEventListener('webglcontextlost', onContextLost);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0b0f14, 60, 220);
    const camera = new THREE.PerspectiveCamera(45, mount.current.clientWidth / mount.current.clientHeight, 0.1, 500);

    // T15 layout-safe size loop: RO flags + throttled rect compare (250 ms). A
    // zero-size mount (dialog transition, hidden tab) never reaches setSize, and
    // >2 s of it pins the dialog to canvas — never a 0×0 buffer that presents
    // nothing forever.
    const container = mount.current;
    let lastW = 0;
    let lastH = 0;
    let sizeDirty = true;
    let lastSizeCheckMs = 0;
    let zeroSinceMs = 0;
    const syncSize = (nowMs: number): boolean => {
      if (!sizeDirty && nowMs - lastSizeCheckMs < 250) return true;
      sizeDirty = false;
      lastSizeCheckMs = nowMs;
      const r = container.getBoundingClientRect();
      if (!shouldRenderSize(r.width, r.height)) return false;
      if (r.width !== lastW || r.height !== lastH) {
        renderer.setSize(r.width, r.height, false); // CSS owns layout
        camera.aspect = r.width / r.height;
        camera.updateProjectionMatrix();
        lastW = r.width;
        lastH = r.height;
      }
      return true;
    };
    const sizeRO = new ResizeObserver(() => { sizeDirty = true; });
    sizeRO.observe(container);

    scene.add(new THREE.AmbientLight(0x8ca0b3, 0.55));
    // T9 cartographic legibility: sky/ground bounce + stronger key light
    scene.add(new THREE.HemisphereLight(0x33404d, 0x0d1116, 0.9));
    const dir = new THREE.DirectionalLight(0xffffff, 1.15);
    dir.position.set(8, 14, 6);
    scene.add(dir);
    const grid = new THREE.GridHelper(40, 40, 0x2a3644, 0x1d2833);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = CARTO.gridOpacity;
    scene.add(grid);
    // T9 ground: matte map-like base under the real OSM context
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(80, 80),
      new THREE.MeshStandardMaterial({ color: CARTO.ground, roughness: 1, metalness: 0 }));
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const hasOsm = osm?.source === 'osm-overpass';
    const buildCount = osm?.buildings.length ?? 0;
    const shadows = hasOsm && buildCount > 0 && buildCount <= 400;
    if (shadows) {
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      dir.castShadow = true;
      dir.shadow.mapSize.set(1024, 1024);
      dir.shadow.camera.near = 0.5;
      dir.shadow.camera.far = 80;
      dir.shadow.camera.left = -30;
      dir.shadow.camera.right = 30;
      dir.shadow.camera.top = 30;
      dir.shadow.camera.bottom = -30;
    }

    const color = new THREE.Color(CLASS_META[ev.classification.primary].color);

    // Facility massing: with REAL OSM footprints the procedural schematic box is
    // hidden (real context wins); without OSM it stays as the honest fallback.
    const fac = !hasOsm ? facilities.find((f) => f.id === ev.nearestFacilityId) : undefined;
    if (fac) {
      const dx = ((fac.lon - ev.lon) * 111_320 * Math.cos((ev.lat * Math.PI) / 180)) / UNIT;
      const dz = ((fac.lat - ev.lat) * 110_540) / UNIT;
      const h = HAZ_HEIGHT[fac.hazard] ?? 3;
      const box = new THREE.Mesh(
        new THREE.BoxGeometry(3, h, 3),
        new THREE.MeshStandardMaterial({ color: 0x7d8da1, roughness: 0.7, metalness: 0.2 }),
      );
      box.position.set(dx, h / 2, -dz);
      scene.add(box);
      const edge = new THREE.LineSegments(
        new THREE.EdgesGeometry(box.geometry),
        new THREE.LineBasicMaterial({ color: 0xe8eef5 }),
      );
      edge.position.copy(box.position);
      scene.add(edge);
    }

    // Scene 2.0: per-detection hotspot cloud replaces the centroid ball when the
    // live buffer has detections; centroid fire core stays as the honest fallback.
    const dets = detections?.length ? capByFrp(detections) : null;
    const origin = { lat: ev.lat, lon: ev.lon };
    let field: HotspotField | null = null;
    let ellipseLine: THREE.LineLoop | null = null;
    let plume: ReturnType<typeof buildPlume> | null = null;
    let fire: THREE.Mesh | null = null;
    let osmScene: ReturnType<typeof buildOsmScene> | null = null;
    let label: ReturnType<typeof buildLabelSprite> | null = null;
    let facLabel: ReturnType<typeof buildHaloLabel> | null = null;
    if (hasOsm && osm) {
      // REAL surroundings from OSM: footprints, trees, roads, water/land-use.
      osmScene = buildOsmScene(origin, osm);
      scene.add(osmScene.group);
      onOsmStats?.({ meshes: osmScene.stats.meshes });
      if (callout) {
        label = buildLabelSprite(callout.text);
        label.sprite.position.set(callout.x, 1.4, callout.z);
        scene.add(label.sprite);
      }
      // priority-0 label: the correlated facility name (real OSM-tagged context)
      const facOsm = facilities.find((f) => f.id === ev.nearestFacilityId);
      if (facOsm) {
        const dxu = ((facOsm.lon - ev.lon) * 111_320 * Math.cos((ev.lat * Math.PI) / 180)) / UNIT;
        const dzu = ((facOsm.lat - ev.lat) * 110_540) / UNIT;
        facLabel = buildHaloLabel(facOsm.name.slice(0, 24));
        facLabel.sprite.position.set(dxu, 0.5, -dzu);
        scene.add(facLabel.sprite);
      }
    } else {
      onOsmStats?.({ meshes: 0 });
    }
    if (dets) {
      field = buildHotspotField(origin, dets);
      scene.add(field.group);
      const enu = dets.map((d) => toEnu(ev.lat, ev.lon, d.lat, d.lon));
      const ell = clusterEllipse(enu);
      if (ell) {
        ellipseLine = buildEllipseLine(ell);
        scene.add(ellipseLine);
      }
      plume = buildPlume();
      plume.points.position.set(0, 0.3, 0);
      scene.add(plume.points);
    } else {
      fire = new THREE.Mesh(
        new THREE.SphereGeometry(0.7, 24, 24),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.4, roughness: 0.4 }),
      );
      fire.position.y = 0.7;
      scene.add(fire);
    }

    // Spread forecast rings (6/12/24 h) — rate scaled by FRP & class
    const rate =
      ({ wildfire: 0.55, agricultural: 0.35, industrial: 0.08, persistent: 0.05 } as Record<string, number>)[
        ev.classification.primary
      ] *
      (0.7 + Math.min(ev.frp, 800) / 1600);
    [6, 12, 24].forEach((h, i) => {
      const r = (rate * h * 1000) / UNIT;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(Math.max(0.4, r - 0.12), Math.max(0.5, r), 64),
        new THREE.MeshBasicMaterial({
          color: i === 2 ? 0xff4444 : 0xff6b35,
          transparent: true,
          opacity: RING_ALPHA[i],
          side: THREE.DoubleSide,
        }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.02 + i * 0.01;
      scene.add(ring);
    });

    // Manual orbit (no addons — keeps bundle lean)
    let theta = Math.PI / 4, phi = Math.PI / 3.2, radius = 26;
    let dragging = false, lx = 0, ly = 0;
    const apply = () => {
      camera.position.set(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(0, 1, 0);
    };
    const el = renderer.domElement;
    const onDown = (e: PointerEvent) => { dragging = true; lx = e.clientX; ly = e.clientY; };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      theta -= (e.clientX - lx) * 0.005;
      phi = Math.min(1.45, Math.max(0.35, phi - (e.clientY - ly) * 0.005));
      lx = e.clientX; ly = e.clientY;
    };
    const onUp = () => { dragging = false; };
    const onWheel = (e: WheelEvent) => { e.preventDefault(); radius = Math.min(80, Math.max(6, radius * (e.deltaY > 0 ? 1.1 : 0.9))); };
    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    el.addEventListener('wheel', onWheel, { passive: false });

    // T9 hover provenance: ray → ground plane (y=0) → pure pickBuilding math.
    const ray = new THREE.Raycaster();
    const onHoverMove = (e: PointerEvent) => {
      if (dragging) return;
      if (!hasOsm || !osm) return onHover?.(null, 0, 0);
      const r = el.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const dy = ray.ray.direction.y;
      if (Math.abs(dy) < 1e-6) return;
      const t = -ray.ray.origin.y / dy;
      if (t <= 0) return onHover?.(null, 0, 0);
      const p = ray.ray.origin.clone().addScaledVector(ray.ray.direction, t);
      onHover?.(pickBuilding(p.x, p.z, origin, osm.buildings), e.clientX, e.clientY);
    };
    el.addEventListener('pointermove', onHoverMove);

    // T9 scale bar + north arrow feed (250 ms — cheap trig, no per-frame churn)
    const camTimer = window.setInterval(() => {
      const d = Math.hypot(camera.position.x, camera.position.y - 1, camera.position.z);
      const yaw = THREE.MathUtils.radToDeg(Math.atan2(camera.position.x, camera.position.z));
      onCamera?.(d, yaw);
      // T15 GL DIAG feed — degradation-tolerant renderer/driver strings.
      if (onGlDiag) {
        const gl = renderer.getContext();
        let rendererStr = String(gl.getParameter(gl.RENDERER) ?? 'unknown');
        let vendorStr = String(gl.getParameter(gl.VENDOR) ?? 'unknown');
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        if (dbg) {
          rendererStr = String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) ?? rendererStr);
          vendorStr = String(gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) ?? vendorStr);
        }
        const attrs = gl.getContextAttributes();
        onGlDiag({
          contextType: renderer.capabilities.isWebGL2 ? 'WebGL2' : 'WebGL1',
          attributes: attrs ? Object.entries(attrs).map(([k, v]) => `${k}=${v}`).join(' ') : 'n/a',
          renderer: rendererStr,
          vendor: vendorStr,
          backingW: gl.drawingBufferWidth,
          backingH: gl.drawingBufferHeight,
          pixelRatio: renderer.getPixelRatio(),
          frames,
          lastVariance,
          drawCalls: renderer.info.render.calls,
          triangles: renderer.info.render.triangles,
        });
      }
    }, 250);

    let raf = 0;
    const t0 = performance.now();
    let lastMs = t0;
    let frames = 0;
    let rasterChecked = false;
    let lastVariance: number | null = null;
    const loop = () => {
      const nowMs = performance.now();
      const dt = Math.min(0.1, (nowMs - lastMs) / 1000);
      lastMs = nowMs;
      // T15: never render into a zero-size buffer — pin after 2 s of it.
      if (!syncSize(nowMs)) {
        if (zeroSinceMs === 0) zeroSinceMs = nowMs;
        if (nowMs - zeroSinceMs > 2000) die('zero-size raster');
        raf = requestAnimationFrame(loop);
        return;
      }
      zeroSinceMs = 0;
      if (fire) fire.scale.setScalar(1 + 0.18 * Math.sin(((nowMs - t0) / 1000) * 4));
      field?.setReplay(replayRef.current);
      field?.update(nowMs);
      plume?.update(dt);
      apply();
      renderer.render(scene, camera);
      frames++;
      // T10 one-shot in-scene raster self-check: readPixels in the SAME frame
      // right after render (valid without preserveDrawingBuffer). A uniform
      // raster means the context presents nothing — pin to canvas, never black.
      if (!rasterChecked && frames === 2 && !glDead) {
        rasterChecked = true;
        try {
          const gl = renderer.getContext();
          const w = gl.drawingBufferWidth;
          const h = gl.drawingBufferHeight;
          const px = new Uint8Array(32 * 32 * 4);
          gl.readPixels(((w / 2) | 0) - 16, ((h / 2) | 0) - 16, 32, 32, gl.RGBA, gl.UNSIGNED_BYTE, px);
          lastVariance = pixelVariance(px);
          if (lastVariance < UNIFORM_RASTER_VARIANCE) die('uniform raster');
          else onGlAlive?.(); // T15: frame-2 passed — the shell may clear the persisted pin
        } catch {
          die('raster read failed');
        }
      }
      raf = requestAnimationFrame(loop);
    };
    loop();
    // T10 frozen-frame watchdog: no frame advance across two 1.5 s checks is a
    // wedged context (no per-frame readPixels — one-shot only, per doctrine).
    let seenFrames = 0;
    let frozenChecks = 0;
    const watchdog = window.setInterval(() => {
      if (glDead) return;
      if (frames === seenFrames) {
        frozenChecks++;
        if (frozenChecks >= 2) die('frozen frames');
      } else {
        frozenChecks = 0;
        seenFrames = frames;
      }
    }, 1500);

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('pointermove', onHoverMove);
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost);
      window.clearInterval(camTimer);
      window.clearInterval(watchdog);
      sizeRO.disconnect();
      field?.dispose();
      if (ellipseLine) {
        ellipseLine.geometry.dispose();
        (ellipseLine.material as THREE.Material).dispose();
      }
      plume?.dispose();
      osmScene?.dispose();
      label?.dispose();
      facLabel?.dispose();
      ground.geometry.dispose();
      (ground.material as THREE.Material).dispose();
      grid.geometry.dispose();
      (grid.material as THREE.Material).dispose();
      disposeSharedTexture();
      renderer.dispose();
      mount.current?.removeChild(renderer.domElement);
    };
  }, [ev, facilities, detections, osm, callout]);

  return <div ref={mount} className="absolute inset-0" />;
}
