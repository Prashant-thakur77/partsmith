"use client";

/**
 * three.js scene for the CAD viewer (react-three-fiber). Z-up CAD frame, millimetres.
 * Shaded faces + crisp B-rep edges, orbit, fit-to-view, ortho/perspective, section plane with a coloured cut face,
 * two-point measure tool, axes gizmo and an mm grid. Rendering is on demand (no idle GPU use).
 */
import { GizmoHelper, GizmoViewport, Grid, Html, OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import * as React from "react";
import * as THREE from "three";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import type { ViewData } from "./view-data";

export type SectionState = { enabled: boolean; axis: "x" | "y" | "z"; t: number; flip: boolean };
export type ViewerColors = { part: string; edge: string; cut: string; grid: string; gridStrong: string; measure: string };

export type CadSceneProps = {
  data: ViewData;
  ortho: boolean;
  showEdges: boolean;
  showGrid: boolean;
  section: SectionState;
  measuring: boolean;
  points: THREE.Vector3[];
  onPick: (p: THREE.Vector3) => void;
  fitNonce: number;
  colors: ViewerColors;
  onContextLost?: () => void;
};

const AXIS_INDEX = { x: 0, y: 1, z: 2 } as const;

function useBounds(data: ViewData) {
  return React.useMemo(() => {
    const min = new THREE.Vector3(...data.min);
    const max = new THREE.Vector3(...data.max);
    const center = min.clone().add(max).multiplyScalar(0.5);
    const radius = Math.max(1, max.clone().sub(min).length() / 2);
    return { min, max, center, radius };
  }, [data]);
}

export function sectionPlane(data: ViewData, section: SectionState): THREE.Plane | null {
  if (!section.enabled) return null;
  const i = AXIS_INDEX[section.axis];
  const lo = data.min[i]!;
  const hi = data.max[i]!;
  const at = lo + (hi - lo) * section.t;
  const n = new THREE.Vector3(i === 0 ? -1 : 0, i === 1 ? -1 : 0, i === 2 ? -1 : 0);
  if (section.flip) n.negate();
  // keep points with n·p + c >= 0
  return new THREE.Plane(n, section.flip ? -at : at);
}

function PartMesh({
  data,
  plane,
  colors,
  measuring,
  onPick,
}: {
  data: ViewData;
  plane: THREE.Plane | null;
  colors: ViewerColors;
  measuring: boolean;
  onPick: (p: THREE.Vector3) => void;
}) {
  const geometry = React.useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
    if (data.indices) g.setIndex(new THREE.BufferAttribute(data.indices, 1));
    if (data.normals) g.setAttribute("normal", new THREE.BufferAttribute(data.normals, 3));
    else g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  }, [data]);
  React.useEffect(() => () => geometry.dispose(), [geometry]);
  const planes = React.useMemo(() => (plane ? [plane] : []), [plane]);

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (!measuring) return;
    e.stopPropagation();
    onPick(e.point.clone());
  };

  return (
    <group>
      <mesh geometry={geometry} onClick={onClick} castShadow={false}>
        <meshStandardMaterial
          color={colors.part}
          roughness={0.62}
          metalness={0.04}
          clippingPlanes={planes}
          polygonOffset
          polygonOffsetFactor={1}
          polygonOffsetUnits={1}
          side={THREE.FrontSide}
        />
      </mesh>
      {plane ? (
        <mesh geometry={geometry}>
          <meshBasicMaterial color={colors.cut} clippingPlanes={planes} side={THREE.BackSide} />
        </mesh>
      ) : null}
    </group>
  );
}

function EdgeLines({ data, plane, color }: { data: ViewData; plane: THREE.Plane | null; color: string }) {
  const size = useThree((s) => s.size);
  const obj = React.useMemo(() => {
    const geo = new LineSegmentsGeometry();
    geo.setPositions(data.segments);
    const mat = new LineMaterial({ color: new THREE.Color(color).getHex(), linewidth: 1.25, worldUnits: false });
    const line = new LineSegments2(geo, mat);
    line.computeLineDistances();
    return line;
  }, [data, color]);
  React.useEffect(() => {
    obj.material.resolution.set(size.width, size.height);
  }, [obj, size]);
  React.useEffect(() => {
    obj.material.clippingPlanes = plane ? [plane] : [];
    obj.material.needsUpdate = true;
  }, [obj, plane]);
  React.useEffect(
    () => () => {
      obj.geometry.dispose();
      obj.material.dispose();
    },
    [obj],
  );
  if (data.segments.length === 0) return null;
  return <primitive object={obj} />;
}

function Fitter({ data, ortho, nonce }: { data: ViewData; ortho: boolean; nonce: number }) {
  const { camera, size, controls, invalidate } = useThree();
  const { center, radius } = useBounds(data);
  const fitted = React.useRef<string>("");
  React.useEffect(() => {
    const key = `${nonce}|${ortho}|${camera.uuid}`;
    // Re-fit on explicit request or camera switch, and on the very first model — never on a re-bake (keeps the user's view).
    if (fitted.current === key) return;
    fitted.current = key;
    const dir = new THREE.Vector3(1, -1.25, 0.95).normalize();
    camera.up.set(0, 0, 1);
    if (camera instanceof THREE.OrthographicCamera) {
      camera.position.copy(center).addScaledVector(dir, radius * 6);
      camera.near = 0.1;
      camera.far = radius * 40;
      camera.zoom = Math.min(size.width, size.height) / (radius * 2 * 1.25);
    } else if (camera instanceof THREE.PerspectiveCamera) {
      const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.12;
      camera.position.copy(center).addScaledVector(dir, dist);
      camera.near = Math.max(0.05, dist / 200);
      camera.far = dist * 40;
    }
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    const c = controls as unknown as { target?: THREE.Vector3; update?: () => void } | null;
    if (c?.target) {
      c.target.copy(center);
      c.update?.();
    }
    invalidate();
  }, [camera, size, controls, center, radius, nonce, ortho, invalidate]);
  return null;
}

function MeasureMarks({ points, radius, color }: { points: THREE.Vector3[]; radius: number; color: string }) {
  const r = Math.max(0.15, radius * 0.012);
  const [a, b] = points;
  const lineGeo = React.useMemo(() => {
    if (!a || !b) return null;
    return new THREE.BufferGeometry().setFromPoints([a, b]);
  }, [a, b]);
  return (
    <group>
      {points.map((p, i) => (
        <mesh key={i} position={p} renderOrder={10}>
          <sphereGeometry args={[r, 16, 12]} />
          <meshBasicMaterial color={color} depthTest={false} />
        </mesh>
      ))}
      {a && b && lineGeo ? (
        <>
          <lineSegments geometry={lineGeo} renderOrder={10}>
            <lineBasicMaterial color={color} depthTest={false} />
          </lineSegments>
          <Html position={a.clone().add(b).multiplyScalar(0.5)} center zIndexRange={[20, 0]}>
            <div className="pointer-events-none rounded-md bg-inverse px-2 py-1 font-mono text-[12px] whitespace-nowrap text-inverse-fg tnum shadow-md">
              {a.distanceTo(b).toFixed(2)} mm
            </div>
          </Html>
        </>
      ) : null}
    </group>
  );
}

function SceneContent(props: CadSceneProps) {
  const { data, ortho, showEdges, showGrid, section, measuring, points, onPick, fitNonce, colors } = props;
  const { center, radius, min } = useBounds(data);
  const plane = React.useMemo(() => sectionPlane(data, section), [data, section]);
  const gridCell = radius > 60 ? 10 : radius > 12 ? 5 : 1;
  return (
    <>
      {ortho ? (
        <OrthographicCamera makeDefault up={[0, 0, 1]} position={[radius * 4, -radius * 5, radius * 4]} />
      ) : (
        <PerspectiveCamera makeDefault up={[0, 0, 1]} fov={32} position={[radius * 2, -radius * 2.5, radius * 2]} />
      )}
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} target={center} />
      <hemisphereLight args={["#ffffff", "#9a9a9a", 1.1]} />
      <directionalLight position={[radius * 2, -radius * 3, radius * 4]} intensity={1.6} />
      <directionalLight position={[-radius * 3, radius * 2, radius * 1.5]} intensity={0.55} />
      <PartMesh data={data} plane={plane} colors={colors} measuring={measuring} onPick={onPick} />
      {showEdges ? <EdgeLines data={data} plane={plane} color={colors.edge} /> : null}
      {showGrid ? (
        <Grid
          position={[center.x, center.y, min.z - radius * 0.002]}
          rotation={[Math.PI / 2, 0, 0]}
          args={[radius * 6, radius * 6]}
          cellSize={gridCell}
          sectionSize={gridCell * 10}
          cellColor={colors.grid}
          sectionColor={colors.gridStrong}
          cellThickness={0.6}
          sectionThickness={1}
          fadeDistance={radius * 8}
          fadeStrength={1.5}
          infiniteGrid={false}
        />
      ) : null}
      <MeasureMarks points={points} radius={radius} color={colors.measure} />
      <Fitter data={data} ortho={ortho} nonce={fitNonce} />
      <GizmoHelper alignment="bottom-left" margin={[52, 52]}>
        <GizmoViewport axisColors={["#e5484d", "#30a46c", "#3e63dd"]} labelColor="#ffffff" axisHeadScale={0.9} />
      </GizmoHelper>
    </>
  );
}

export default function CadScene(props: CadSceneProps) {
  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      onCreated={({ gl }) => {
        gl.localClippingEnabled = true;
        gl.setClearAlpha(0);
        gl.domElement.addEventListener("webglcontextlost", () => props.onContextLost?.());
      }}
      style={{ cursor: props.measuring ? "crosshair" : "grab" }}
    >
      <SceneContent {...props} />
    </Canvas>
  );
}
