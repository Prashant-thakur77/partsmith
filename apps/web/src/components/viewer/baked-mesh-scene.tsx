"use client";

/**
 * The small 3D view for baked meshes: drag to turn, no zoom or pan, a slow turn until the first drag. It holds the last mesh
 * while the next loads, so a knob never flashes empty. Loaded on demand (three.js is not in any page's first bundle).
 */
import { Edges, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import * as React from "react";
import * as THREE from "three";
import { decodeMesh, meshUrl } from "@/lib/baked-models";
import { fetchViewData } from "./view-data";

const cache = new Map<string, Promise<THREE.BufferGeometry>>();

function loadGeometry(file: string): Promise<THREE.BufferGeometry> {
  const url = meshUrl(file);
  let p = cache.get(url);
  if (!p) {
    const mesh: Promise<{ positions: Float32Array; indices: Uint32Array | null }> = url.includes(".bin")
      ? fetch(url).then(async (r) => {
          if (!r.ok) throw new Error(`${url}: ${r.status}`);
          return decodeMesh(await r.arrayBuffer());
        })
      : fetchViewData(url);
    p = mesh.then(({ positions, indices }) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      if (indices) g.setIndex(new THREE.BufferAttribute(indices, 1));
      g.computeBoundingBox();
      const c = new THREE.Vector3();
      g.boundingBox!.getCenter(c);
      g.translate(-c.x, -c.y, -c.z);
      g.computeBoundingBox();
      g.computeVertexNormals();
      return g;
    });
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return p;
}

/** Fetch these meshes now, so moving a knob swaps at once. */
export function preloadMeshes(files: readonly string[]) {
  for (const f of files) void loadGeometry(f).catch(() => undefined);
}

function Fit({ sizeMm, view }: { sizeMm: number; view: "iso" | "under" }) {
  const camera = useThree((s) => s.camera);
  React.useEffect(() => {
    const d = sizeMm * 1.22;
    if (view === "under") camera.position.set(0, -d * 0.98, d * 0.02);
    else camera.position.set(d * 0.62, d * 0.72, d * 0.78);
    camera.near = sizeMm / 50;
    camera.far = sizeMm * 40;
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }, [camera, sizeMm, view]);
  return null;
}

function colors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, f: string) => cs.getPropertyValue(n).trim() || f;
  return { part: v("--viewer-part", "#d9d8d3"), edge: v("--viewer-edge", "#2b2b2b") };
}

export default function BakedMeshScene({
  file,
  sizeMm,
  turning = true,
  onError,
  onReady,
  scale,
  view = "iso",
}: {
  file: string;
  /** largest dimension to frame, in mm (fixed across a knob's steps); framed to the mesh itself when left out */
  sizeMm?: number;
  turning?: boolean;
  onError?: (e: unknown) => void;
  onReady?: () => void;
  /** scales the drawn mesh along its own axes, for showing what stretching a mesh does; left out, it draws as baked */
  scale?: [number, number, number];
  view?: "iso" | "under";
}) {
  const [geometry, setGeometry] = React.useState<THREE.BufferGeometry | null>(null);
  const [palette, setPalette] = React.useState<{ part: string; edge: string } | null>(null);
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    const update = () => setPalette(colors());
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);

  React.useEffect(() => {
    let live = true;
    loadGeometry(file)
      .then((g) => {
        if (!live) return;
        setGeometry(g);
        onReady?.();
      })
      .catch((e: unknown) => {
        if (live) onError?.(e);
      });
    return () => {
      live = false;
    };
    // onError and onReady are callbacks from the parent's render; only a new file should reload
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  const spin = turning && !touched;
  const box = geometry?.boundingBox;
  // framed by the mesh's diagonal, so a tall part fits as well as a flat one
  const frame = sizeMm ?? (box ? Math.hypot(box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z) * 1.08 : null);
  return (
    <Canvas
      camera={{ fov: 34 }}
      dpr={[1, 2]}
      frameloop={spin ? "always" : "demand"}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}
      style={{ touchAction: "pan-y" }}
    >
      {frame ? <Fit sizeMm={frame} view={view} /> : null}
      <ambientLight intensity={1.1} />
      <directionalLight position={[3, 6, 4]} intensity={1.7} />
      <directionalLight position={[-4, 2, -3]} intensity={0.5} />
      {geometry && palette ? (
        // CadQuery is Z up; the scene is Y up
        <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} scale={scale ?? [1, 1, 1]}>
          <meshStandardMaterial color={palette.part} roughness={0.72} metalness={0.02} flatShading side={THREE.DoubleSide} />
          <Edges threshold={28} color={palette.edge} />
        </mesh>
      ) : null}
      <OrbitControls
        enablePan={false}
        enableZoom={false}
        autoRotate={spin}
        autoRotateSpeed={1.1}
        makeDefault
        onStart={() => setTouched(true)}
      />
    </Canvas>
  );
}
