"""Rendering offscreen: anteprime PNG senza aprire la UI.

Serve per i test automatici e per generare provini rapidi da riga di comando.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.scene import Scene
from app.ui.render_core import (
    FRAGMENT_SHADER, GRID_FRAGMENT, GRID_VERTEX, VERTEX_SHADER,
    Orbit, grid_buffer, pack_scene,
)


def render(scene: Scene, path: str | Path, size: tuple[int, int] = (1100, 700),
           azimuth: float = 38.0, elevation: float = 16.0,
           background: tuple[float, float, float] = (0.10, 0.11, 0.13),
           textured: bool = True) -> Path:
    import moderngl
    from PIL import Image

    ctx = moderngl.create_standalone_context()
    w, h = size
    color = ctx.texture((w, h), 4, samples=0)
    depth = ctx.depth_renderbuffer((w, h))
    fbo = ctx.framebuffer(color_attachments=[color], depth_attachment=depth)
    fbo.use()
    ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
    ctx.clear(*background, 1.0)

    orbit = Orbit(azimuth=azimuth, elevation=elevation)
    orbit.frame(scene)
    mvp, eye = orbit.matrices(w / h)

    grid_prog = ctx.program(vertex_shader=GRID_VERTEX, fragment_shader=GRID_FRAGMENT)
    gbuf = grid_buffer(max(6.0, orbit.distance), 0.5)
    gvbo = ctx.buffer(gbuf.tobytes())
    gvao = ctx.vertex_array(grid_prog, [(gvbo, "3f 1f", "in_pos", "in_shade")])
    grid_prog["u_mvp"].write(mvp.T.astype("f4").tobytes())
    gvao.render(moderngl.LINES)

    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    prog["u_mvp"].write(mvp.T.astype("f4").tobytes())
    prog["u_model"].write(np.eye(4, dtype="f4").T.tobytes())
    prog["u_eye"].value = tuple(float(v) for v in eye)

    prog["u_tex"].value = 0
    blank = ctx.texture((1, 1), 3, np.ones(3, dtype="f4").tobytes(), dtype="f4")

    for item in pack_scene(scene, textured=textured):
        vbo = ctx.buffer(item.buffer.tobytes())
        vao = ctx.vertex_array(prog, [(vbo, "3f 3f", "in_pos", "in_norm")])
        prog["u_color"].value = item.color
        prog["u_rough"].value = item.roughness
        prog["u_metal"].value = item.metallic
        prog["u_tiling"].value = max(item.tiling, 1e-3)

        texture = None
        if item.texture is not None:
            texture = ctx.texture(item.texture.shape[:2], 3, item.texture.tobytes(), dtype="f4")
            texture.repeat_x = texture.repeat_y = True
            texture.build_mipmaps()
            texture.use(0)
            prog["u_tex_mix"].value = float(item.detail)
        else:
            blank.use(0)
            prog["u_tex_mix"].value = 0.0

        vao.render()
        vao.release()
        vbo.release()
        if texture is not None:
            texture.release()
    blank.release()

    data = fbo.read(components=3, alignment=1)
    img = Image.frombytes("RGB", (w, h), data).transpose(Image.FLIP_TOP_BOTTOM)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    ctx.release()
    return out
