"""Nucleo di rendering condiviso: shader, camera e packing dei buffer.

Usato sia dal viewport Qt interattivo sia dal renderer offscreen (anteprime,
test automatici, screenshot senza aprire la UI).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.core.scene import Scene

VERTEX_SHADER = """
#version 330
uniform mat4 u_mvp;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_norm;
out vec3 v_norm;
out vec3 v_world;
void main() {
    vec4 world = u_model * vec4(in_pos, 1.0);
    v_world = world.xyz;
    v_norm = mat3(u_model) * in_norm;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330
uniform vec4 u_color;
uniform float u_rough;
uniform float u_metal;
uniform vec3 u_eye;
uniform sampler2D u_tex;
uniform float u_tex_mix;      // 0 = tinta piatta, 1 = texture
uniform float u_tiling;       // metri per ripetizione
in vec3 v_norm;
in vec3 v_world;
out vec4 f_color;

// Proiezione triplanare: le texture procedurali sono piastrellate in
// coordinate di mondo, quindi si campionano dalla posizione. Nessuna UV nei
// vertici, nessuna cucitura da gestire.
vec3 triplanar(vec3 p, vec3 n) {
    vec3 w = pow(abs(n), vec3(4.0));
    w /= max(w.x + w.y + w.z, 1e-5);
    vec2 uvx = p.yz / u_tiling;
    vec2 uvy = p.xz / u_tiling;
    vec2 uvz = p.xy / u_tiling;
    return texture(u_tex, uvx).rgb * w.x
         + texture(u_tex, uvy).rgb * w.y
         + texture(u_tex, uvz).rgb * w.z;
}

void main() {
    vec3 n = normalize(v_norm);
    vec3 v = normalize(u_eye - v_world);
    vec3 l = normalize(vec3(0.45, 0.85, 0.35));
    vec3 l2 = normalize(vec3(-0.6, 0.35, -0.5));

    float sky = 0.5 + 0.5 * n.y;
    vec3 ambient = mix(vec3(0.16, 0.17, 0.20), vec3(0.42, 0.46, 0.52), sky);

    float d1 = max(dot(n, l), 0.0);
    float d2 = max(dot(n, l2), 0.0) * 0.35;

    vec3 h = normalize(l + v);
    float shininess = mix(96.0, 6.0, clamp(u_rough, 0.0, 1.0));
    float spec = pow(max(dot(n, h), 0.0), shininess) * (1.0 - u_rough * 0.85);

    vec3 base = u_color.rgb;
    if (u_tex_mix > 0.001) {
        vec3 detail = triplanar(v_world, n);
        // la texture modula la tinta del materiale, non la sostituisce
        // la mappa e' gia' normalizzata attorno a 0.5: modula, non sostituisce
        float d = detail.r - 0.5;
        base = mix(base, clamp(base * (1.0 + 1.15 * d), 0.0, 1.0), u_tex_mix);
    }
    vec3 diffuse = base * (ambient + d1 * 0.85 + d2);
    vec3 specular = mix(vec3(1.0), base, u_metal) * spec * (0.35 + 0.65 * u_metal);

    vec3 color = diffuse + specular;
    color = pow(color, vec3(1.0 / 1.9));            // gamma morbida
    f_color = vec4(color, u_color.a);
}
"""

GRID_VERTEX = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in float in_shade;
out float v_shade;
void main() {
    v_shade = in_shade;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

GRID_FRAGMENT = """
#version 330
in float v_shade;
out vec4 f_color;
void main() { f_color = vec4(vec3(0.42, 0.44, 0.48) * v_shade, 0.85); }
"""


@dataclass
class DrawItem:
    buffer: np.ndarray          # float32 interleaved: pos(3) + normal(3)
    color: tuple[float, float, float, float]
    roughness: float
    metallic: float
    node_id: str
    transparent: bool
    texture: np.ndarray | None = None   # (n, n, 3) in 0..1, gia' piastrellabile
    tiling: float = 0.4
    detail: float = 0.8


def _finish_texture(material: str, size: int = 128):
    """Mappa di dettaglio in scala di grigi per l'anteprima, con cache."""
    from app.materials.library import finish_for
    from app.materials.texture import generate

    finish = finish_for(material)
    if finish is None or not finish.enabled():
        return None, 0.4, 0.0
    key = (finish.texture, size)
    cached = _TEXTURE_CACHE.get(key)
    if cached is None:
        colour = generate(finish.texture, size=size, seed=0).base_color
        luma = colour @ np.array([0.299, 0.587, 0.114])
        # Normalizzata a media 0.5 e contrasto pieno: senza questo passaggio una
        # texture scura (la gomma) modulerebbe pochissimo e resterebbe invisibile.
        spread = max(float(np.std(luma)), 1e-4)
        detail = np.clip(0.5 + (luma - float(np.mean(luma))) / (spread * 4.0), 0.0, 1.0)
        cached = np.ascontiguousarray(np.repeat(detail[..., None], 3, axis=2).astype("f4"))
        _TEXTURE_CACHE[key] = cached
    return cached, float(finish.tiling), float(finish.detail)


_TEXTURE_CACHE: dict[tuple[str, int], np.ndarray] = {}


def pack_scene(scene: Scene, textured: bool = True) -> list[DrawItem]:
    items: list[DrawItem] = []
    for n in scene.nodes:
        m = n.mesh
        if len(m.faces) == 0:
            continue
        verts = m.vertices[m.faces].reshape(-1, 3)
        norms = np.repeat(m.face_normals, 3, axis=0)
        data = np.hstack([verts, norms]).astype("f4")
        rgba = n.material.rgba()
        texture, tiling, detail = (_finish_texture(n.material.name) if textured
                                   else (None, 0.4, 0.0))
        items.append(DrawItem(
            buffer=data, color=rgba,
            roughness=float(n.material.roughness), metallic=float(n.material.metallic),
            node_id=n.id, transparent=rgba[3] < 0.999,
            texture=texture, tiling=tiling, detail=detail,
        ))
    items.sort(key=lambda i: i.transparent)  # opachi prima, trasparenti dopo
    return items


def grid_buffer(extent: float = 6.0, step: float = 0.5) -> np.ndarray:
    lines: list[list[float]] = []
    n = int(extent / step)
    for i in range(-n, n + 1):
        p = i * step
        shade = 1.0 if i % 2 == 0 else 0.55
        lines += [[-extent, 0.0, p, shade], [extent, 0.0, p, shade]]
        lines += [[p, 0.0, -extent, shade], [p, 0.0, extent, shade]]
    return np.asarray(lines, dtype="f4")


# --------------------------------------------------------------------------- #
# camera
# --------------------------------------------------------------------------- #
def perspective(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4), dtype="f4")
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = target - eye
    f = f / (np.linalg.norm(f) + 1e-9)
    s = np.cross(f, up)
    s = s / (np.linalg.norm(s) + 1e-9)
    u = np.cross(s, f)
    m = np.eye(4, dtype="f4")
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


@dataclass
class Orbit:
    azimuth: float = 38.0
    elevation: float = 18.0
    distance: float = 9.0
    target: tuple[float, float, float] = (0.0, 0.8, 0.0)

    def eye(self) -> np.ndarray:
        a, e = math.radians(self.azimuth), math.radians(self.elevation)
        t = np.asarray(self.target, dtype="f4")
        return t + np.array([
            self.distance * math.cos(e) * math.sin(a),
            self.distance * math.sin(e),
            self.distance * math.cos(e) * math.cos(a),
        ], dtype="f4")

    def matrices(self, aspect: float) -> tuple[np.ndarray, np.ndarray]:
        eye = self.eye()
        view = look_at(eye, np.asarray(self.target, dtype="f4"), np.array([0, 1, 0], dtype="f4"))
        proj = perspective(42.0, aspect, max(self.distance * 0.01, 0.02), self.distance * 12 + 60)
        return proj @ view, eye

    def frame(self, scene: Scene) -> None:
        """Inquadra automaticamente la scena."""
        if not scene.nodes:
            return
        b = scene.bounds()
        center = (b[0] + b[1]) / 2
        size = float(np.max(b[1] - b[0]))
        self.target = (float(center[0]), float(center[1]), float(center[2]))
        self.distance = max(size * 1.9, 1.2)
