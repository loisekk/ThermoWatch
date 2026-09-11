import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { CLASS_META } from '@/config/constants';
import type { Facility, FireEvent } from '@/types/domain';

const UNIT = 100; // 1 scene unit = 100 m
const HAZ_HEIGHT: Record<string, number> = { 'G-III': 6, 'G-II': 4, 'G-I': 2.5 };
const RING_ALPHA = [0.4, 0.3, 0.2];

/** Three.js incident scene — used only where WebGL actually rasterizes. */
export function ThreeScene({ ev, facilities }: { ev: FireEvent; facilities: Facility[] }) {
  const mount = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mount.current) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    renderer.setSize(mount.current.clientWidth, mount.current.clientHeight);
    mount.current.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, mount.current.clientWidth / mount.current.clientHeight, 0.1, 500);
    scene.add(new THREE.AmbientLight(0x8ca0b3, 0.7));
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(8, 14, 6);
    scene.add(dir);
    scene.add(new THREE.GridHelper(40, 40, 0x2a3644, 0x1d2833));

    const color = new THREE.Color(CLASS_META[ev.classification.primary].color);

    // Facility massing (nearest mapped asset)
    const fac = facilities.find((f) => f.id === ev.nearestFacilityId);
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

    // Fire core (pulsing)
    const fire = new THREE.Mesh(
      new THREE.SphereGeometry(0.7, 24, 24),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.4, roughness: 0.4 }),
    );
    fire.position.y = 0.7;
    scene.add(fire);

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

    let raf = 0;
    const t0 = performance.now();
    const loop = () => {
      const t = (performance.now() - t0) / 1000;
      fire.scale.setScalar(1 + 0.18 * Math.sin(t * 4));
      apply();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      el.removeEventListener('wheel', onWheel);
      renderer.dispose();
      mount.current?.removeChild(renderer.domElement);
    };
  }, [ev, facilities]);

  return <div ref={mount} className="absolute inset-0" />;
}
