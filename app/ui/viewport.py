"""Viewport 3D interattivo: QOpenGLWidget + moderngl.

Nessun motore di rendering esterno: shader propri, camera in orbita, griglia.
Condivide shader e camera con il renderer offscreen (app/ui/render_core.py).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent, QSurfaceFormat, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from app.core.logging_setup import get
from app.core.scene import Scene
from app.ui.render_core import (
    FRAGMENT_SHADER, GRID_FRAGMENT, GRID_VERTEX, VERTEX_SHADER,
    DrawItem, Orbit, grid_buffer, pack_scene,
)

log = get("ui.viewport")


def configure_opengl() -> None:
    """Va chiamata PRIMA di creare QApplication."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)


class Viewport(QOpenGLWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ctx = None
        self.prog = None
        self.grid_prog = None
        self.grid_vao = None
        self._vaos: list[tuple[object, object, DrawItem]] = []
        self._textures: dict[int, object] = {}
        self._blank = None
        self._pending: list[DrawItem] = []
        self._dirty = False
        self.orbit = Orbit()
        self.show_grid = True
        self.show_textures = True
        self.wireframe = False
        self.background = (0.098, 0.105, 0.125)
        self._last_pos = None
        self.gl_error: str = ""
        self.setMinimumSize(480, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------- OpenGL #
    def initializeGL(self) -> None:
        import moderngl
        try:
            self.ctx = moderngl.create_context()
            self.prog = self.ctx.program(vertex_shader=VERTEX_SHADER,
                                         fragment_shader=FRAGMENT_SHADER)
            self.grid_prog = self.ctx.program(vertex_shader=GRID_VERTEX,
                                              fragment_shader=GRID_FRAGMENT)
            gbuf = grid_buffer(12.0, 0.5)
            gvbo = self.ctx.buffer(gbuf.tobytes())
            self.grid_vao = self.ctx.vertex_array(
                self.grid_prog, [(gvbo, "3f 1f", "in_pos", "in_shade")])
            log.info("contesto OpenGL pronto: %s", self.ctx.info.get("GL_RENDERER", "?"))
        except Exception as exc:  # pragma: no cover - dipende dai driver
            self.gl_error = str(exc)
            log.error("inizializzazione OpenGL fallita: %s", exc)

    def _upload(self) -> None:
        if self.ctx is None:
            return
        for vao, vbo, _ in self._vaos:
            try:
                vao.release()
                vbo.release()
            except Exception:
                pass
        self._vaos = []
        for item in self._pending:
            vbo = self.ctx.buffer(item.buffer.tobytes())
            vao = self.ctx.vertex_array(self.prog, [(vbo, "3f 3f", "in_pos", "in_norm")])
            self._vaos.append((vao, vbo, item))
        self._dirty = False

    def _texture_for(self, item: DrawItem):
        """Le texture procedurali sono poche e condivise: si caricano una volta."""
        if item.texture is None:
            return None
        key = id(item.texture)
        cached = self._textures.get(key)
        if cached is None:
            cached = self.ctx.texture(item.texture.shape[:2], 3,
                                      item.texture.tobytes(), dtype="f4")
            cached.repeat_x = cached.repeat_y = True
            cached.build_mipmaps()
            self._textures[key] = cached
        return cached

    def paintGL(self) -> None:
        if self.ctx is None:
            return
        import moderngl

        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        fbo.use()
        self.ctx.clear(*self.background, 1.0)
        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        if self._dirty:
            self._upload()

        aspect = max(self.width(), 1) / max(self.height(), 1)
        mvp, eye = self.orbit.matrices(aspect)
        mvp_bytes = mvp.T.astype("f4").tobytes()

        if self.show_grid and self.grid_vao is not None:
            self.grid_prog["u_mvp"].write(mvp_bytes)
            self.grid_vao.render(moderngl.LINES)

        self.prog["u_mvp"].write(mvp_bytes)
        self.prog["u_model"].write(np.eye(4, dtype="f4").T.tobytes())
        self.prog["u_eye"].value = tuple(float(v) for v in eye)

        if self._blank is None:
            self._blank = self.ctx.texture((1, 1), 3, np.ones(3, dtype="f4").tobytes(),
                                           dtype="f4")
        self.prog["u_tex"].value = 0

        mode = moderngl.LINES if self.wireframe else moderngl.TRIANGLES
        for vao, _vbo, item in self._vaos:
            self.prog["u_color"].value = item.color
            self.prog["u_rough"].value = item.roughness
            self.prog["u_metal"].value = item.metallic
            self.prog["u_tiling"].value = max(item.tiling, 1e-3)

            texture = self._texture_for(item) if self.show_textures else None
            if texture is not None:
                texture.use(0)
                self.prog["u_tex_mix"].value = float(item.detail)
            else:
                self._blank.use(0)
                self.prog["u_tex_mix"].value = 0.0
            vao.render(mode)

    # -------------------------------------------------------------- scena #
    def set_scene(self, scene: Scene | None) -> None:
        self._pending = pack_scene(scene, textured=True) if scene is not None else []
        self._dirty = True
        if scene is not None and scene.nodes:
            self.orbit.frame(scene)
        self.update()

    def reset_view(self) -> None:
        self.orbit.azimuth, self.orbit.elevation = 38.0, 18.0
        self.update()

    # -------------------------------------------------------------- mouse #
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._last_pos = e.position()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._last_pos is None:
            return
        d = e.position() - self._last_pos
        self._last_pos = e.position()
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.orbit.azimuth -= d.x() * 0.4
            self.orbit.elevation = float(np.clip(self.orbit.elevation + d.y() * 0.35, -88, 88))
        elif e.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton):
            scale = self.orbit.distance * 0.0016
            tx, ty, tz = self.orbit.target
            a = np.radians(self.orbit.azimuth)
            self.orbit.target = (tx - float(np.cos(a)) * d.x() * scale,
                                 ty + d.y() * scale,
                                 tz + float(np.sin(a)) * d.x() * scale)
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._last_pos = None

    def wheelEvent(self, e: QWheelEvent) -> None:
        factor = 0.88 if e.angleDelta().y() > 0 else 1.14
        self.orbit.distance = float(np.clip(self.orbit.distance * factor, 0.3, 400.0))
        self.update()
