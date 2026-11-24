"""Dependency-free, software-rendered 3D hologram suit for the HUD."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import monotonic

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class _Part:
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    color: tuple[int, int, int, int]
    wire_lines: tuple[tuple[int, ...], ...] = ()


IRON_HAND_POSE = -math.radians(65)


def _ellipsoid(
    center: tuple[float, float, float],
    radii: tuple[float, float, float],
    color: tuple[int, int, int, int],
    *,
    tilt: float = 0.0,
    segments: int = 20,
    rings: int = 12,
) -> _Part:
    cx, cy, cz = center
    rx, ry, rz = radii
    ct, st = math.cos(tilt), math.sin(tilt)
    vertices: list[tuple[float, float, float]] = []
    for row in range(rings + 1):
        latitude = -math.pi / 2 + math.pi * row / rings
        cl, sl = math.cos(latitude), math.sin(latitude)
        for column in range(segments):
            longitude = 2 * math.pi * column / segments
            x = rx * cl * math.sin(longitude)
            y = -ry * cl * math.cos(longitude)
            z = rz * sl
            vertices.append((cx + x * ct + z * st, cy + y,
                             cz - x * st + z * ct))
    triangles: list[tuple[int, int, int]] = []
    for row in range(rings):
        for column in range(segments):
            a = row * segments + column
            b = row * segments + (column + 1) % segments
            c = (row + 1) * segments + (column + 1) % segments
            d = (row + 1) * segments + column
            triangles.extend(((a, b, c), (a, c, d)))
    wire_lines: list[tuple[int, ...]] = []
    for row in range(2, rings, 3):
        start = row * segments
        wire_lines.append(tuple(start + column for column in range(segments)) + (start,))
    for column in range(0, segments, 4):
        wire_lines.append(tuple(row * segments + column for row in range(rings + 1)))
    return _Part(tuple(vertices), tuple(triangles), color, wire_lines=tuple(wire_lines))


def _armor_shell(
    center: tuple[float, float, float],
    radii: tuple[float, float, float],
    color: tuple[int, int, int, int],
    *,
    sides: int = 6,
) -> _Part:
    """Low-poly faceted shell with clipped top/bottom edges for armor masses."""
    cx, cy, cz = center
    rx, ry, rz = radii
    # Flat bands create broad planes and hard shoulders instead of ellipsoid-like
    # transitions.  The central bands keep a human silhouette under the armor.
    profile = ((-1.00, .38, .50), (-.88, .58, .68), (-.66, .80, .84),
               (-.34, .96, .97), (.28, 1.0, 1.0), (.58, .91, .94),
               (.82, .70, .80), (1.00, .43, .58))
    vertices = []
    for z_factor, x_factor, y_factor in profile:
        for side in range(sides):
            angle = 2 * math.pi * side / sides
            vertices.append((cx + rx * x_factor * math.sin(angle),
                             cy - ry * y_factor * math.cos(angle),
                             cz + rz * z_factor))
    triangles = []
    for band in range(len(profile) - 1):
        for side in range(sides):
            a = band * sides + side
            b = band * sides + (side + 1) % sides
            c = (band + 1) * sides + (side + 1) % sides
            d = (band + 1) * sides + side
            triangles.extend(((a, b, c), (a, c, d)))
    # Horizontal seams emphasize machined plate transitions; longitudinal
    # lines are sparse and only serve as faint holographic construction marks.
    wire_lines = [tuple(band * sides + side for side in range(sides)) + (band * sides,)
                  for band in (2, 4)]
    wire_lines.extend(tuple(band * sides + side for band in range(len(profile)))
                      for side in range(0, sides, 2))
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=tuple(wire_lines))


def _sectioned_shell(
    center: tuple[float, float, float],
    radii: tuple[float, float, float],
    color: tuple[int, int, int, int],
    profile: tuple[tuple[float, float, float], ...],
    *,
    sides: int = 10,
) -> _Part:
    """Anatomically profiled loft: width and depth change at each body station."""
    cx, cy, cz = center
    rx, ry, rz = radii
    vertices = []
    for z_factor, x_factor, y_factor in profile:
        for side in range(sides):
            angle = math.tau * side / sides
            vertices.append((cx + rx * x_factor * math.sin(angle),
                             cy - ry * y_factor * math.cos(angle),
                             cz + rz * z_factor))
    triangles = []
    for band in range(len(profile) - 1):
        for side in range(sides):
            a = band * sides + side
            b = band * sides + (side + 1) % sides
            c = (band + 1) * sides + (side + 1) % sides
            d = (band + 1) * sides + side
            triangles.extend(((a, b, c), (a, c, d)))
    contour_bands = sorted({max(1, len(profile) // 3),
                            min(len(profile) - 2, 2 * len(profile) // 3)})
    wire_lines = [tuple(band * sides + side for side in range(sides)) + (band * sides,)
                  for band in contour_bands]
    wire_lines.extend(tuple(band * sides + side for band in range(len(profile)))
                      for side in range(0, sides, 4))
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=tuple(wire_lines))


def _torus(
    center: tuple[float, float, float],
    major: float,
    tube: float,
    color: tuple[int, int, int, int],
    *,
    segments: int = 32,
    sides: int = 8,
) -> _Part:
    cx, cy, cz = center
    vertices: list[tuple[float, float, float]] = []
    for ring in range(segments):
        around = 2 * math.pi * ring / segments
        ca, sa = math.cos(around), math.sin(around)
        for side in range(sides):
            cross = 2 * math.pi * side / sides
            radial = major + tube * math.cos(cross)
            vertices.append((cx + radial * sa, cy - tube * math.sin(cross),
                             cz + radial * ca))
    triangles: list[tuple[int, int, int]] = []
    for ring in range(segments):
        for side in range(sides):
            a = ring * sides + side
            b = ring * sides + (side + 1) % sides
            c = ((ring + 1) % segments) * sides + (side + 1) % sides
            d = ((ring + 1) % segments) * sides + side
            triangles.extend(((a, b, c), (a, c, d)))
    wire_lines = []
    for ring in range(0, segments, 4):
        start = ring * sides
        wire_lines.append(tuple(start + side for side in range(sides)) + (start,))
    for side in range(0, sides, 2):
        wire_lines.append(tuple((ring % segments) * sides + side
                                for ring in range(segments + 1)))
    return _Part(tuple(vertices), tuple(triangles), color, wire_lines=tuple(wire_lines))


def _tapered_cylinder_depth(
    center: tuple[float, float, float],
    front_radius: float,
    back_radius: float,
    half_depth: float,
    color: tuple[int, int, int, int],
    *,
    segments: int = 48,
) -> _Part:
    """A truncated cone with flat caps, narrowing from front to back."""
    cx, cy, cz = center
    front = [(cx + front_radius * math.cos(math.tau * index / segments),
              cy - half_depth,
              cz + front_radius * math.sin(math.tau * index / segments))
             for index in range(segments)]
    back = [(cx + back_radius * math.cos(math.tau * index / segments),
             cy + half_depth,
             cz + back_radius * math.sin(math.tau * index / segments))
            for index in range(segments)]
    front_center = (cx, cy - half_depth, cz)
    back_center = (cx, cy + half_depth, cz)
    vertices = front + back + [front_center, back_center]
    front_center_index = 2 * segments
    back_center_index = front_center_index + 1
    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        following = (index + 1) % segments
        # Front cap faces toward the camera; back cap faces away.
        triangles.append((front_center_index, index, following))
        triangles.append((back_center_index, segments + following,
                          segments + index))
        # Two outward-facing triangles form each flat side facet.
        triangles.append((index, segments + index, segments + following))
        triangles.append((index, segments + following, following))
    front_line = tuple(range(segments)) + (0,)
    back_line = tuple(range(segments, 2 * segments)) + (segments,)
    side_lines = tuple((index, segments + index)
                       for index in range(0, segments, 4))
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=(front_line, back_line) + side_lines)


def _tapered_hollow_shell(
    center: tuple[float, float, float],
    outer_front: float,
    outer_back: float,
    inner_front: float,
    inner_back: float,
    half_depth: float,
    color: tuple[int, int, int, int],
    *,
    segments: int = 64,
) -> _Part:
    """Tapered annular chassis that leaves a channel for the glowing core."""
    cx, cy, cz = center
    angles = [math.tau * index / segments for index in range(segments)]
    front_outer = [(cx + outer_front * math.cos(a), cy - half_depth,
                    cz + outer_front * math.sin(a)) for a in angles]
    back_outer = [(cx + outer_back * math.cos(a), cy + half_depth,
                   cz + outer_back * math.sin(a)) for a in angles]
    front_inner = [(cx + inner_front * math.cos(a), cy - half_depth,
                    cz + inner_front * math.sin(a)) for a in angles]
    back_inner = [(cx + inner_back * math.cos(a), cy + half_depth,
                   cz + inner_back * math.sin(a)) for a in angles]
    vertices = front_outer + back_outer + front_inner + back_inner
    outer_back_start = segments
    inner_front_start = 2 * segments
    inner_back_start = 3 * segments
    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        following = (index + 1) % segments
        fo, fon = index, following
        bo, bon = outer_back_start + index, outer_back_start + following
        fi, fin = inner_front_start + index, inner_front_start + following
        bi, bin_ = inner_back_start + index, inner_back_start + following

        # Front and back annuli face in opposite directions.
        triangles.extend(((fo, fon, fin), (fo, fin, fi),
                          (bo, bi, bin_), (bo, bin_, bon)))
        # Tapered outer wall and the inside wall around the light channel.
        triangles.extend(((fo, bo, bon), (fo, bon, fon),
                          (fi, fin, bin_), (fi, bin_, bi)))

    front_outer_line = tuple(range(segments)) + (0,)
    back_outer_line = tuple(range(outer_back_start, outer_back_start + segments)) + (outer_back_start,)
    front_inner_line = tuple(range(inner_front_start, inner_front_start + segments)) + (inner_front_start,)
    back_inner_line = tuple(range(inner_back_start, inner_back_start + segments)) + (inner_back_start,)
    side_lines = tuple((index, outer_back_start + index,
                        inner_back_start + index, inner_front_start + index)
                       for index in range(0, segments, 4))
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=(front_outer_line, back_outer_line,
                             front_inner_line, back_inner_line) + side_lines)


def _tapered_rib(
    center: tuple[float, float, float],
    angle: float,
    front_radius: float,
    back_radius: float,
    half_depth: float,
    half_width: float,
    half_radial: float,
    color: tuple[int, int, int, int],
) -> _Part:
    """A narrow cage rail that follows the tapered side wall."""
    cx, cy, cz = center
    tangent, radial = math.cos(angle), math.sin(angle)
    radial_x, radial_z = math.sin(angle), math.cos(angle)
    corners = ((-half_width, -half_radial), (half_width, -half_radial),
               (half_width, half_radial), (-half_width, half_radial))

    def ring(y: float, radius: float) -> list[tuple[float, float, float]]:
        points = []
        for tangent_offset, radial_offset in corners:
            distance = radius + radial_offset
            points.append((cx + distance * radial_x + tangent_offset * tangent,
                           y,
                           cz + distance * radial_z - tangent_offset * radial))
        return points

    vertices = (ring(cy - half_depth, front_radius)
                + ring(cy + half_depth, back_radius))
    triangles = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)]
    for index in range(4):
        following = (index + 1) % 4
        triangles.extend(((index, following, 4 + following),
                          (index, 4 + following, 4 + index)))
    front_line, back_line = (0, 1, 2, 3, 0), (4, 5, 6, 7, 4)
    joins = tuple((index, index + 4) for index in range(4))
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=(front_line, back_line) + joins)


def _beveled_plate(
    center: tuple[float, float, float],
    half_width: float,
    half_height: float,
    color: tuple[int, int, int, int],
    outline: tuple[tuple[float, float], ...],
    *,
    depth: float = .045,
    bevel: float = .055,
) -> _Part:
    """A front-facing armor plate with clipped corners and a raised bevel."""
    cx, cy, cz = center
    count = len(outline)
    outer = [(cx + x * half_width, cy - depth, cz + z * half_height)
             for x, z in outline]
    inset_scale = .84
    inner = [(cx + x * half_width * inset_scale, cy - depth - bevel,
              cz + z * half_height * inset_scale) for x, z in outline]
    face_center = (cx, cy - depth - bevel - .002, cz)
    vertices = outer + inner + [face_center]
    center_index = 2 * count
    triangles: list[tuple[int, int, int]] = []

    def front_facing(a: int, b: int, c: int) -> None:
        p, q, r = vertices[a], vertices[b], vertices[c]
        ab = (q[0]-p[0], q[1]-p[1], q[2]-p[2])
        ac = (r[0]-p[0], r[1]-p[1], r[2]-p[2])
        normal_y = ab[2] * ac[0] - ab[0] * ac[2]
        triangles.append((a, c, b) if normal_y > 0 else (a, b, c))

    for index in range(count):
        following = (index + 1) % count
        front_facing(index, following, count + following)
        front_facing(index, count + following, count + index)
        front_facing(center_index, count + index, count + following)

    outer_line = tuple(range(count)) + (0,)
    inner_line = tuple(range(count, 2 * count)) + (count,)
    return _Part(tuple(vertices), tuple(triangles), color,
                 wire_lines=(outer_line, inner_line))


def _beveled_box(
    center: tuple[float, float, float],
    half_width: float,
    half_depth: float,
    half_height: float,
    color: tuple[int, int, int, int],
    outline: tuple[tuple[float, float], ...],
    *,
    bevel: float = .045,
) -> _Part:
    """A chamfered extruded case with a real side wall and inset front face."""
    cx, cy, cz = center
    count = len(outline)
    front = [(cx + x * half_width, cy - half_depth, cz + z * half_height)
             for x, z in outline]
    back = [(cx + x * half_width, cy + half_depth, cz + z * half_height)
            for x, z in outline]
    inset = [(cx + x * half_width * .84, cy - half_depth - bevel,
              cz + z * half_height * .84) for x, z in outline]
    face_center = (cx, cy - half_depth - bevel - .002, cz)
    back_center = (cx, cy + half_depth, cz)
    vertices = front + back + inset + [face_center, back_center]
    center_index = 3 * count
    back_center_index = center_index + 1
    triangles: list[tuple[int, int, int]] = []

    def face(a: int, b: int, c: int) -> None:
        p, q, r = vertices[a], vertices[b], vertices[c]
        ab = (q[0]-p[0], q[1]-p[1], q[2]-p[2])
        ac = (r[0]-p[0], r[1]-p[1], r[2]-p[2])
        normal_y = ab[2] * ac[0] - ab[0] * ac[2]
        triangles.append((a, c, b) if normal_y > 0 else (a, b, c))

    for index in range(count):
        following = (index + 1) % count
        face(index, following, count + following)
        face(index, count + following, count + index)
        face(index, following, 2 * count + following)
        face(index, 2 * count + following, 2 * count + index)
        face(center_index, 2 * count + index, 2 * count + following)
        face(back_center_index, count + following, count + index)

    outer_line = tuple(range(count)) + (0,)
    inset_line = tuple(range(2 * count, 3 * count)) + (2 * count,)
    depth_edges = tuple((index, count + index) for index in range(0, count, 2))
    wire_lines = (outer_line, inset_line) + depth_edges
    return _Part(tuple(vertices), tuple(triangles), color, wire_lines=wire_lines)


class HologramSuitDisplay(QWidget):
    """Rotatable full-body armor hologram, rendered locally with Qt painter."""

    RED = (190, 27, 34, 205)
    RED_LIGHT = (225, 54, 43, 205)
    RED_DARK = (91, 17, 26, 195)
    GOLD = (209, 161, 69, 215)
    GOLD_LIGHT = (245, 213, 133, 220)
    STEEL = (34, 82, 101, 210)
    CYAN = (66, 225, 248, 230)
    CORE = (96, 238, 255, 245)

    def __init__(self) -> None:
        super().__init__()
        self.phase = 0.0
        self.language = "ko"
        self.ai_busy = False
        self.gesture_yaw = 0.0
        self.gesture_zoom = 1.0
        self.gesture_paused = False
        self.power_active = False
        self._power_started = 0.0
        self._power_until = 0.0
        self.flight_lift = 0.0
        self.model = "suit"
        self.view_target_x = 0.0
        self.view_target_z = 4.25
        self.camera_x = 0.0
        self.camera_z = 4.25
        self._last_gesture_action = 0.0
        self._last_hand_x: float | None = None
        self._last_hand_time = 0.0
        self.setMinimumSize(300, 310)
        self._parts = self._build_suit()
        self.animation = QTimer(self)
        self.animation.timeout.connect(self._advance)
        self.animation.start(85)

    def set_ai_busy(self, busy: bool) -> None:
        """Lower renderer CPU use while a local model is generating or speaking."""
        busy = bool(busy)
        if self.ai_busy == busy:
            return
        self.ai_busy = busy
        self.animation.setInterval(135 if busy else 85)
        self.update()

    @classmethod
    def _build_suit(cls) -> tuple[_Part, ...]:
        parts: list[_Part] = []
        chamfered = ((-.72, -1), (.72, -1), (1, -.58), (1, .52),
                     (.68, 1), (-.68, 1), (-1, .52), (-1, -.58))
        shield = ((-.72, -1), (.72, -1), (1, -.55), (.88, .45),
                  (.46, 1), (-.46, 1), (-.88, .45), (-1, -.55))
        faceplate = ((-.58, 1), (.58, 1), (.92, .62), (.82, -.30),
                     (.42, -.82), (0, -1), (-.42, -.82), (-.82, -.30),
                     (-.92, .62))
        eye_slot = ((-1, -.28), (-.72, -1), (.72, -1), (1, -.28),
                    (.78, 1), (-.78, 1))
        torso_profile = (
            (-1.00, .54, .56), (-.84, .70, .70), (-.64, .72, .76),
            (-.43, .82, .84), (-.20, .92, .95), (.04, .98, 1.0),
            (.28, 1.0, 1.0), (.52, .96, .94), (.72, .80, .83),
            (.90, .50, .64), (1.0, .34, .48),
        )
        upper_arm_profile = (
            (-1.0, .56, .66), (-.72, .78, .83), (-.34, .96, .97),
            (.18, 1.0, 1.0), (.58, .86, .91), (1.0, .68, .76),
        )
        forearm_profile = (
            (-1.0, .62, .72), (-.72, .74, .84), (-.36, .90, .96),
            (.08, 1.0, 1.0), (.48, .96, .98), (.82, .84, .88),
            (1.0, .72, .76),
        )
        thigh_profile = (
            (-1.0, .63, .72), (-.78, .78, .84), (-.42, .94, .96),
            (.05, 1.0, 1.0), (.42, .98, .97), (.78, .88, .90),
            (1.0, .78, .82),
        )
        shin_profile = (
            (-1.0, .56, .65), (-.72, .72, .80), (-.36, .90, .94),
            (.08, 1.0, 1.0), (.44, .94, .98), (.78, .80, .87),
            (1.0, .68, .75),
        )

        def add(center, radii, material, *, tilt=0.0, segments=20, rings=12):
            parts.append(_ellipsoid(center, radii, material, tilt=tilt,
                                    segments=segments, rings=rings))

        def shell(center, radii, material, *, profile=None):
            mesh = (_sectioned_shell(center, radii, material, profile)
                    if profile else _armor_shell(center, radii, material))
            parts.append(mesh)

        def plate(center, width, height, material, outline=chamfered,
                  *, depth=.045, bevel=.055):
            parts.append(_beveled_plate(center, width, height, material, outline,
                                        depth=depth, bevel=bevel))

        # Torso, articulated abdomen, and waist.
        shell((0, .015, 6.12), (1.10, .56, 1.20), cls.RED_DARK,
              profile=torso_profile)
        plate((0, -.46, 6.99), .47, .12, cls.RED_LIGHT, chamfered,
              depth=.03, bevel=.025)
        shell((0, -.40, 4.82), (.78, .20, .37), cls.GOLD)
        shell((0, 0.02, 4.72), (.62, .46, .42), cls.RED_DARK)

        # Neck and angular helmet with a separate gold faceplate and visor.
        shell((0, 0.00, 7.25), (.34, .31, .38), cls.STEEL)
        shell((0, .015, 8.07), (.59, .56, .70), cls.RED_LIGHT)
        plate((0, -.525, 8.05), .425, .47, cls.GOLD_LIGHT, faceplate,
              depth=.035, bevel=.045)
        plate((0, -.635, 8.18), .355, .085, (5, 18, 28, 248), chamfered,
              depth=.025, bevel=.022)
        for side in (-1, 1):
            plate((side * .19, -.69, 8.18), .125, .027, cls.CYAN, eye_slot,
                  depth=.012, bevel=.01)
        for side in (-1, 1):
            plate((side * .54, -.16, 8.09), .095, .18, cls.GOLD, shield,
                  depth=.025, bevel=.025)

        # Shoulder armor, arms, elbow joints, gauntlets, and hands.
        for side in (-1, 1):
            shell((side * 1.08, .015, 6.56), (.55, .57, .53), cls.RED_LIGHT)
            shell((side * 1.34, .00, 5.66), (.39, .43, .78), cls.RED,
                  profile=upper_arm_profile)
            shell((side * 1.48, -.015, 4.70), (.36, .41, .69), cls.RED_DARK,
                  profile=forearm_profile)
            shell((side * 1.53, .00, 4.02), (.31, .37, .36), cls.GOLD)
            shell((side * 1.55, -.16, 3.53), (.255, .30, .31), cls.RED)
            plate((side * 1.56, -.31, 3.56), .12, .17, cls.GOLD_LIGHT, shield,
                  depth=.025, bevel=.02)
            for finger in range(3):
                shell((side * (1.48 + finger * .075), -.388, 3.47),
                      (.026, .018, .10), cls.GOLD_LIGHT)
            # Inset articulation bearings at the elbows.
            shell((side * 1.46, -.38, 5.02), (.15, .10, .16), cls.STEEL)

        # Full articulated legs, knee shields, shin plates, and boots.
        for side in (-1, 1):
            x = side * .47
            shell((x, .00, 3.73), (.43, .48, .92), cls.GOLD,
                  profile=thigh_profile)
            shell((x, .00, 2.70), (.34, .38, .34), cls.RED_DARK)
            shell((x, .015, 1.72), (.355, .43, .75), cls.RED,
                  profile=shin_profile)
            shell((x, -.13, .55), (.42, .61, .39), cls.RED_DARK)
            plate((x, -.48, .53), .30, .18, cls.RED_LIGHT, shield,
                  depth=.035, bevel=.025)

        # Chest reactor housing, luminous core, and raised alloy rim.
        add((0, -.594, 6.47), (.46, .105, .46), cls.STEEL)
        parts.append(_torus((0, -.70, 6.47), .37, .075, cls.CYAN))
        add((0, -.724, 6.47), (.255, .105, .255), cls.CORE, segments=20, rings=12)
        add((0, -.824, 6.47), (.105, .045, .105), (237, 255, 255, 255),
            segments=16, rings=10)

        # A single clean bevel per armor region keeps the silhouette legible.
        for side in (-1, 1):
            plate((side * .52, -.575, 6.60), .43, .30, cls.GOLD_LIGHT, shield,
                  depth=.035, bevel=.035)
            # Shoulder and forearm shells use sharp, slanted outer edges.
            plate((side * 1.08, -.525, 6.56), .44, .35, cls.RED_LIGHT, shield,
                  depth=.04, bevel=.04)
            plate((side * 1.48, -.405, 4.72), .255, .49, cls.RED_LIGHT, chamfered,
                  depth=.035, bevel=.032)
            plate((side * 1.53, -.315, 4.02), .245, .27, cls.GOLD_LIGHT, shield,
                  depth=.035, bevel=.03)

            # Faceted thigh, knee, shin and boot plates give the silhouette a
            # segmented mechanical profile instead of a smooth toy-like shell.
            x = side * .47
            plate((x, -.595, 3.73), .275, .72, cls.RED_LIGHT, chamfered,
                  depth=.035, bevel=.04)
            plate((x, -.43, 2.70), .29, .29, cls.GOLD_LIGHT, shield,
                  depth=.035, bevel=.04)
            plate((x, -.425, 1.73), .235, .55, cls.GOLD, shield,
                  depth=.035, bevel=.04)
            plate((x, -.75, .55), .32, .18, cls.RED_LIGHT, chamfered,
                  depth=.035, bevel=.025)

        # Three separate abdominal cassettes make the waist read as machined armor.
        for z, width in ((5.82, .57), (5.56, .52), (5.30, .46)):
            plate((0, -.715, z), width * .91, .105, cls.RED_LIGHT, chamfered,
                  depth=.03, bevel=.027)
        return tuple(parts)

    @classmethod
    def _build_web_shooter(cls) -> tuple[_Part, ...]:
        """Standalone wrist-mounted web shooter, kept in the same cyan holo style."""
        parts: list[_Part] = []
        chamfered = ((-.72, -1), (.72, -1), (1, -.58), (1, .52),
                     (.68, 1), (-.68, 1), (-1, .52), (-1, -.58))
        shield = ((-.72, -1), (.72, -1), (1, -.55), (.88, .45),
                  (.46, 1), (-.46, 1), (-.88, .45), (-1, -.55))
        cartridge = ((-.72, -1), (.72, -1), (1, -.82), (1, .82),
                     (.72, 1), (-.72, 1), (-1, .82), (-1, -.82))
        mount_metal = (64, 83, 89, 242)
        case_metal = (151, 170, 175, 245)
        lid_metal = (205, 219, 221, 250)
        dark_steel = (27, 42, 48, 250)
        fastener_metal = (232, 241, 241, 255)

        angle = math.radians(22)

        def angle_part(part, center):
            cx, cy, cz = center
            cosine, sine = math.cos(angle), math.sin(angle)
            vertices = tuple(
                (cx + (x - cx) * cosine + (z - cz) * sine,
                 y,
                 cz - (x - cx) * sine + (z - cz) * cosine)
                for x, y, z in part.vertices
            )
            parts.append(_Part(vertices, part.triangles, part.color, part.wire_lines))

        def angled_plate(center, half_width, half_height, material, outline,
                         *, depth=.05, bevel=.04):
            part = _beveled_plate(center, half_width, half_height, material,
                                  outline, depth=depth, bevel=bevel)
            angle_part(part, center)

        def angled_box(center, half_width, half_depth, half_height, material):
            part = _beveled_box(center, half_width, half_depth, half_height,
                                material, cartridge, bevel=.05)
            angle_part(part, center)

        # Four raised cartridge cases in two parallel rows, on a single plate.
        angled_box((0, -.40, 4.25), 1.32, .12, .49, mount_metal)
        cosine, sine = math.cos(angle), math.sin(angle)
        for station in (-1, 1):
            for row in (-1, 1):
                local_x, local_z = station * .61, row * .205
                cx = local_x * cosine + local_z * sine
                cz = 4.25 - local_x * sine + local_z * cosine
                angled_box((cx, -.57, cz), .63, .15, .17, case_metal)
                angled_plate((cx, -.735, cz), .50, .125, lid_metal, cartridge,
                             depth=.02, bevel=.018)
                # Four small fasteners frame each rectangular cartridge lid.
                for lid_x in (-.46, .46):
                    for lid_z in (-.09, .09):
                        sx = cx + lid_x * cosine + lid_z * sine
                        sz = cz - lid_x * sine + lid_z * cosine
                        parts.append(_ellipsoid((sx, -.79, sz), (.021, .018, .021),
                                                fastener_metal, segments=8, rings=6))
        # Slim guide rails frame the outside edges without covering the lids.
        for rail_side in (-1, 1):
            rail_local_z = rail_side * .405
            rail_x = rail_local_z * sine
            rail_z = 4.25 + rail_local_z * cosine
            angled_box((rail_x, -.70, rail_z), 1.20, .035, .022, mount_metal)
        # Keep only the long firing rod on the centerline between the cartridge
        # rows; the lower protruding slide/base is intentionally omitted.
        angled_box((0, -.84, 4.25), 1.08, .025, .024, fastener_metal)
        # A compact web-shooter head caps the rod's lower-right end.
        muzzle_x = 1.04 * cosine
        muzzle_z = 4.25 - 1.04 * sine
        angled_box((muzzle_x, -.86, muzzle_z), .19, .065, .09, dark_steel)
        angled_plate((muzzle_x, -.935, muzzle_z), .145, .067,
                     lid_metal, chamfered, depth=.018, bevel=.012)
        angled_plate((muzzle_x, -.963, muzzle_z), .074, .038,
                     dark_steel, chamfered, depth=.012, bevel=.008)
        angled_plate((muzzle_x, -.984, muzzle_z), .037, .016,
                     (74, 215, 235, 255), chamfered, depth=.008, bevel=.004)
        # Small face screws finish the muzzle housing and make it read as a
        # serviceable mechanical part instead of a smooth decorative block.
        for screw_x in (-.12, .12):
            for screw_z in (-.045, .045):
                sx = muzzle_x + screw_x * cosine + screw_z * sine
                sz = muzzle_z - screw_x * sine + screw_z * cosine
                parts.append(_ellipsoid((sx, -.982, sz), (.012, .01, .012),
                                        fastener_metal, segments=8, rings=6))
        return tuple(parts)

    @classmethod
    def _build_arc_reactor(cls) -> tuple[_Part, ...]:
        """A circular, segmented arc reactor inspired by the supplied reference."""
        parts: list[_Part] = []
        dark_steel = (17, 34, 43, 250)
        steel = (78, 119, 132, 250)
        silver = (153, 183, 191, 255)
        copper = (135, 82, 49, 255)
        copper_light = (180, 119, 69, 255)
        cyan = (36, 190, 238, 255)
        cyan_bright = (104, 231, 255, 255)
        outline = ((-.72, -1), (.72, -1), (1, -.58), (1, .52),
                   (.68, 1), (-.68, 1), (-1, .52), (-1, -.58))

        # A true flat-sided cylindrical chassis gives the reactor substantial
        # depth instead of the thin, rounded profile of an ellipsoid.
        parts.append(_tapered_hollow_shell((0, .03, 4.25),
                                           1.18, .68, .55, .20, .62,
                                           dark_steel, segments=64))
        # The luminous core continues through the hollow center from the front
        # lens into the deep tapered chassis, so its light reaches the side gaps.
        parts.append(_tapered_cylinder_depth((0, -.05, 4.25), .45, .13, .70,
                                             (28, 148, 198, 248), segments=48))
        for segment in range(12):
            angle = math.tau * segment / 12
            parts.append(_tapered_rib((0, .03, 4.25), angle, 1.14, .64,
                                      .60, .042, .065, steel))

        # Muted blue-steel windows between the cage supports catch and reflect
        # the core light; they are deliberately not emissive light bars.
        for segment in range(12):
            angle = math.tau * (segment + .5) / 12
            parts.append(_tapered_rib((0, .03, 4.25), angle, 1.20, .70,
                                      .54, .105, .022,
                                      (27, 106, 148, 220)))

        # A smaller rear lip makes the narrowing toward the back easy to read.
        parts.append(_torus((0, .64, 4.25), .66, .035, steel,
                            segments=48, sides=10))
        parts.append(_torus((0, -.62, 4.25), 1.08, .045, steel,
                            segments=48, sides=10))
        parts.append(_torus((0, -.70, 4.25), .88, .035, cyan,
                            segments=48, sides=10))
        parts.append(_torus((0, -.76, 4.25), .69, .032, silver,
                            segments=48, sides=10))
        parts.append(_torus((0, -.82, 4.25), .52, .035, cyan_bright,
                            segments=48, sides=10))

        # Twelve separate alloy housings form the segmented outer ring.
        for segment in range(12):
            angle = math.tau * segment / 12
            x = .98 * math.sin(angle)
            z = 4.25 + .98 * math.cos(angle)
            part = _beveled_box((x, -.63, z), .135, .065, .105,
                                copper_light if segment % 3 == 0 else copper,
                                outline, bevel=.03)
            cosine, sine = math.cos(angle), math.sin(angle)
            vertices = tuple(
                (x + (vx - x) * cosine + (vz - z) * sine,
                 vy,
                 z - (vx - x) * sine + (vz - z) * cosine)
                for vx, vy, vz in part.vertices
            )
            parts.append(_Part(vertices, part.triangles, part.color, part.wire_lines))

        # Small blue luminous cells sit between the outer metal segments.
        for segment in range(16):
            angle = math.tau * (segment + .5) / 16
            x = .80 * math.sin(angle)
            z = 4.25 + .80 * math.cos(angle)
            parts.append(_ellipsoid((x, -.72, z), (.044, .022, .073), cyan,
                                    tilt=angle, segments=12, rings=8))

        # A bright central lens is recessed inside the innermost alloy ring.
        parts.append(_ellipsoid((0, -.83, 4.25), (.36, .08, .36), cyan,
                                segments=32, rings=18))
        parts.append(_ellipsoid((0, -.90, 4.25), (.255, .035, .255), cyan_bright,
                                segments=32, rings=18))
        parts.append(_ellipsoid((0, -.94, 4.25), (.16, .022, .16),
                                (42, 194, 239, 255), segments=28, rings=16))
        return tuple(parts)

    @classmethod
    def _build_iron_hand(cls) -> tuple[_Part, ...]:
        """Open palm armor with articulated red fingers and a palm repulsor."""
        parts: list[_Part] = []
        chamfered = ((-.72, -1), (.72, -1), (1, -.58), (1, .52),
                     (.68, 1), (-.68, 1), (-1, .52), (-1, -.58))
        dark_steel = (32, 64, 79, 245)
        red = (166, 25, 32, 248)
        red_light = (216, 43, 47, 250)
        red_dark = (94, 17, 25, 245)

        def rotated_plate(center, half_width, half_height, color, angle,
                          *, depth=.03, bevel=.025):
            part = _beveled_plate(center, half_width, half_height, color,
                                  chamfered, depth=depth, bevel=bevel)
            cx, cy, cz = center
            cosine, sine = math.cos(angle), math.sin(angle)
            vertices = tuple(
                (cx + (x - cx) * cosine + (z - cz) * sine,
                 y,
                 cz - (x - cx) * sine + (z - cz) * cosine)
                for x, y, z in part.vertices
            )
            parts.append(_Part(vertices, part.triangles, part.color, part.wire_lines))

        # Palm shell and a separate cuff terminate at the wrist; no arm is drawn.
        parts.append(_armor_shell((0, .015, 4.28), (.69, .34, .72), red_dark))
        # The palm plate tapers toward the wrist and sweeps toward the thumb,
        # avoiding the square, toy-like silhouette of the earlier version.
        # Broad knuckle fan tapering into a narrower wrist, like a real palm.
        palm_outline = ((-.48, -1), (.48, -1), (.68, -.82), (.82, -.45),
                        (.92, -.08), (1, .25), (.82, .54), (.70, .79),
                        (.48, 1), (.18, .94), (-.20, 1), (-.48, .91),
                        (-.74, .68), (-.92, .35), (-1, .02), (-.88, -.35),
                        (-.72, -.72))
        parts.append(_beveled_plate((-.015, -.34, 4.34), .59, .59,
                                    red_light, palm_outline, depth=.04, bevel=.045))
        # Rotate the forearm armor as a separate section at the wrist pivot.
        # This creates a visible bend instead of merely curving the silhouette.
        def bend_wrist(part: _Part) -> _Part:
            pivot_x, pivot_z = 0.0, 3.72
            bend = -math.radians(42)
            cosine, sine = math.cos(bend), math.sin(bend)
            bent_vertices = []
            for x, y, z in part.vertices:
                dx, dz = x - pivot_x, z - pivot_z
                bent_vertices.append((pivot_x + dx * cosine + dz * sine,
                                      y,
                                      pivot_z - dx * sine + dz * cosine))
            return _Part(tuple(bent_vertices), part.triangles, part.color,
                         part.wire_lines)

        wrist_shell = _armor_shell((.10, .025, 3.47), (.78, .39, .72),
                                   red_dark, sides=16)
        parts.append(bend_wrist(wrist_shell))
        wrist_panel = ((-.62, -1), (.55, -1), (.82, -.72), (.94, -.18),
                       (.84, .58), (.58, 1), (-.54, 1), (-.84, .58),
                       (-.94, -.18), (-.82, -.72))
        wrist_plate = _beveled_plate((.10, -.295, 3.49), .59, .47,
                                     red, wrist_panel, depth=.032, bevel=.035)
        parts.append(bend_wrist(wrist_plate))
        # The film prop uses grooved gauntlet armor; add restrained recessed
        # channels along the forearm rather than another stack of surface plates.
        for groove_z in (3.30, 3.10, 2.90):
            groove = _beveled_plate((.10, -.355, groove_z), .43, .014,
                                    red_dark, chamfered, depth=.004, bevel=.004)
            parts.append(bend_wrist(groove))
        # A slim inset seam marks the flex point without splitting the armor.
        wrist_seam = _beveled_plate((0, -.46, 3.70), .54, .055,
                                    dark_steel, chamfered, depth=.014, bevel=.008)
        parts.append(bend_wrist(wrist_seam))
        # Rounded red end closes the bent cuff without a protruding cyan strip.
        cuff_end = _ellipsoid((.10, .01, 2.86), (.61, .33, .22), red_dark,
                              segments=24, rings=12)
        parts.append(bend_wrist(cuff_end))

        # Four separated fingers fan upward, each with visible knuckle joints.
        fingers = (
            (-.56, 4.58, -math.radians(35), (.36, .30, .25), .12),
            (-.31, 4.83, math.radians(5), (.43, .36, .29), .132),
            (-.025, 4.91, math.radians(30), (.48, .40, .32), .14),
            (.29, 4.83, math.radians(65), (.42, .36, .29), .132),
        )
        # The thumb opens out to the right, as in the reference pose.
        fingers += ((.55, 4.17, math.radians(122), (.42, .35, .29), .145),)
        for base_x, base_z, angle, lengths, width in fingers:
            direction_x, direction_z = math.sin(angle), math.cos(angle)
            distance = 0.0
            for segment, segment_length in enumerate(lengths):
                center_distance = distance + segment_length * .5
                center = (base_x + direction_x * center_distance,
                          -.045,
                          base_z + direction_z * center_distance)
                segment_width = width * (1.0 - .11 * segment)
                parts.append(_ellipsoid(center,
                                        (segment_width, .14, segment_length * .61),
                                        red_dark if segment == 1 else red,
                                        tilt=angle, segments=14, rings=8))
                rotated_plate((center[0], -.205, center[2]),
                              segment_width * .82, segment_length * .50,
                              red_light if segment != 1 else red,
                              angle, depth=.025, bevel=.022)
                distance += segment_length
                if segment < len(lengths) - 1:
                    joint = (base_x + direction_x * distance,
                             -.225,
                             base_z + direction_z * distance)
                    parts.append(_ellipsoid(joint,
                                            (segment_width * .62, .065, .034),
                                            dark_steel, tilt=angle,
                                            segments=12, rings=8))
                    parts.append(_beveled_plate(
                        (joint[0], -.285, joint[2]), segment_width * .46, .016,
                        dark_steel, chamfered, depth=.01, bevel=.007,
                    ))

        # Small articulated plates protect the palm under the finger roots.
        for x in (-.39, -.13, .15, .40):
            parts.append(_beveled_plate((x, -.375, 4.79), .095, .075,
                                        red, chamfered, depth=.02, bevel=.018))

        # Layered circular palm emitter, bright enough to read as a repulsor.
        # Keep the reactor centered on the palm face, raised on a socket that
        # is part of the palm armor (never on the back of the hand or wrist).
        repulsor = (0, 4.28)
        parts.append(_ellipsoid((repulsor[0], -.43, repulsor[1]),
                                (.34, .11, .34), red_dark))
        parts.append(_ellipsoid((repulsor[0], -.52, repulsor[1]),
                                (.285, .085, .285), dark_steel))
        parts.append(_torus((repulsor[0], -.595, repulsor[1]), .225, .032,
                            (165, 226, 239, 245), segments=40, sides=10))
        parts.append(_ellipsoid((repulsor[0], -.635, repulsor[1]),
                                (.175, .045, .175), (229, 246, 250, 255),
                                segments=28, rings=16))
        parts.append(_ellipsoid((repulsor[0], -.68, repulsor[1]),
                                (.135, .025, .135), (255, 255, 255, 255),
                                segments=28, rings=16))

        # Turn the whole open hand so the fingers fan toward the upper-left and
        # the wrist cuff trails to the right, matching the supplied pose.
        pose = IRON_HAND_POSE
        cosine, sine = math.cos(pose), math.sin(pose)
        posed_parts = []
        for part in parts:
            vertices = tuple(
                (x * cosine + (z - 4.25) * sine,
                 y,
                 4.25 - x * sine + (z - 4.25) * cosine)
                for x, y, z in part.vertices
            )
            posed_parts.append(_Part(vertices, part.triangles,
                                     part.color, part.wire_lines))
        return tuple(posed_parts)

    def set_model(self, model: str) -> None:
        if model not in {"suit", "web_shooter", "arc_reactor", "iron_hand"} or model == self.model:
            return
        self.model = model
        self._parts = {
            "suit": self._build_suit,
            "web_shooter": self._build_web_shooter,
            "arc_reactor": self._build_arc_reactor,
            "iron_hand": self._build_iron_hand,
        }[model]()
        self.gesture_yaw = 0.0
        self.gesture_zoom = 1.0
        self.gesture_paused = False
        self.view_target_x = self.camera_x = 0.0
        self.view_target_z = self.camera_z = 4.25
        self._last_hand_x = None
        self.power_active = False
        self._power_until = 0.0
        self.flight_lift = 0.0
        self.update()

    def set_language(self, language: str) -> None:
        self.language = language
        self.update()

    def _advance(self) -> None:
        now = monotonic()
        self.power_active = now < self._power_until
        if self.power_active and self.model == "suit":
            target_lift = .52 + .10 * math.sin((now - self._power_started) * 9)
        else:
            target_lift = 0.0
        self.flight_lift += (target_lift - self.flight_lift) * .22
        if not self.gesture_paused:
            self.phase = (self.phase + 2.1) % 360
        # Smooth hand-driven camera movement so landmark noise does not make
        # the view shake while the L gesture is held.
        self.camera_x += (self.view_target_x - self.camera_x) * .22
        self.camera_z += (self.view_target_z - self.camera_z) * .22
        self.update()

    def apply_gesture(self, name: str, hand_x: float, hand_y: float = .5) -> None:
        now = monotonic()
        hand_delta = 0.0
        if self._last_hand_x is not None and now - self._last_hand_time <= .4:
            hand_delta = hand_x - self._last_hand_x
        self._last_hand_x = hand_x
        self._last_hand_time = now
        if name == "OK_Gesture":
            if not self.power_active:
                self._power_started = now
            self.power_active = True
            self._power_until = now + .38
            self.gesture_paused = False
        if name == "L_Gesture":
            # The L pose acts like a virtual camera joystick. Moving the hand
            # across the image selects a point on the suit to bring into view.
            self.view_target_x = max(-1.35, min(1.35, (hand_x - .5) * 2.7))
            self.view_target_z = max(.45, min(8.25, (1.0 - hand_y) * 8.7))
        if name == "Open_Palm":
            if abs(hand_delta) >= .012:
                # One full hand sweep across the camera view produces about one turn.
                # Keep this unbounded for the hand too, then wrap to a full circle;
                # the previous narrow clamp made the hologram appear stuck.
                yaw_delta = hand_delta * math.tau * 1.33
                self.gesture_yaw = (self.gesture_yaw + yaw_delta) % math.tau
            self.gesture_paused = False
        elif name == "Closed_Fist":
            self.gesture_paused = True
        elif name == "Victory" and now - self._last_gesture_action > 1.2:
            self.gesture_yaw = 0.0
            self.gesture_zoom = 1.0
            self.view_target_x = self.camera_x = 0.0
            self.view_target_z = self.camera_z = 4.25
            self.gesture_paused = False
            self._last_gesture_action = now
        elif name == "Thumb_Up":
            self.gesture_zoom = min(1.42, self.gesture_zoom * 1.035)
        elif name == "Thumb_Down":
            self.gesture_zoom = max(.78, self.gesture_zoom / 1.035)
        self.update()

    @staticmethod
    def _rotate(point, yaw: float, pitch: float):
        x, y, z = point
        cy, sy = math.cos(yaw), math.sin(yaw)
        x, y = x * cy - y * sy, x * sy + y * cy
        cp, sp = math.cos(pitch), math.sin(pitch)
        return x, y * cp - z * sp, y * sp + z * cp

    @staticmethod
    def _cross(a, b, c):
        ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        return (ab[1]*ac[2] - ab[2]*ac[1],
                ab[2]*ac[0] - ab[0]*ac[2],
                ab[0]*ac[1] - ab[1]*ac[0])

    def _project(self, point, yaw: float, pitch: float, zoom: float):
        x, y, z = self._rotate(point, yaw, pitch)
        model_scale = (3.7 if self.model == "web_shooter" else
                       2.7 if self.model == "arc_reactor" else
                       2.2 if self.model == "iron_hand" else 1.0)
        if model_scale != 1.0:
            x *= model_scale
            y *= model_scale
            z = 4.25 + (z - 4.25) * model_scale
        distance = 20.0
        base_focal = 720.0
        focal = base_focal * zoom
        depth = max(10.0, distance + y)
        factor = focal / depth
        base_factor = base_focal / depth
        # Keep zoom centered around the suit's waist/chest midpoint instead of
        # the feet; otherwise magnifying makes the lower body dominate the view.
        focus_z = 4.25 + (self.camera_z - 4.25) * model_scale
        screen_y = 356 - focus_z * base_factor - (z - focus_z) * factor
        return QPointF(210 + (x - self.camera_x * model_scale) * factor, screen_y), y

    def _current_yaw(self) -> float:
        idle_turn = math.sin(math.radians(self.phase * .5)) * .28
        return self.gesture_yaw + idle_turn

    def _draw_suit(self, painter: QPainter, pulse: float) -> QPointF:
        yaw = self._current_yaw()
        pitch = math.sin(math.radians(self.phase * .19)) * .018
        faces = []
        light = (.24, -.86, .46)
        light_len = math.sqrt(sum(v*v for v in light))
        light = tuple(v / light_len for v in light)
        view = (0.0, -1.0, 0.0)
        half_vector = tuple(light[i] + view[i] for i in range(3))
        half_len = math.sqrt(sum(v*v for v in half_vector))
        half_vector = tuple(v / half_len for v in half_vector)
        wire_paths = []
        depth_triangles = []

        for part in self._parts:
            rotated = [
                self._rotate(vertex, yaw, pitch) for vertex in part.vertices
            ]
            if self.model == "suit" and self.flight_lift > .001:
                rotated = [(x, y, z + self.flight_lift) for x, y, z in rotated]
            projected = [self._project(vertex, 0.0, 0.0, self.gesture_zoom)
                         for vertex in rotated]
            for ia, ib, ic in part.triangles:
                a, b, c = rotated[ia], rotated[ib], rotated[ic]
                normal = self._cross(a, b, c)
                length = math.sqrt(sum(v*v for v in normal))
                if length < 1e-7:
                    continue
                normal = tuple(v / length for v in normal)
                # The virtual camera looks toward the suit from the negative Y axis.
                if normal[1] > -.025:
                    continue
                diffuse = max(0.0, sum(normal[i] * light[i] for i in range(3)))
                specular = max(0.0, sum(normal[i] * half_vector[i] for i in range(3))) ** 38
                shade = .30 + .62 * diffuse
                # Cyan Fresnel rim light makes the armor read as a lit volume,
                # while preserving dark, transparent centers like a projection.
                rim = (1.0 - max(0.0, -normal[1])) ** 2.4
                if self.model in {"web_shooter", "arc_reactor", "iron_hand"}:
                    # Preserve machined metal and emissive material colors on
                    # the two standalone devices; the armor remains cyan-only.
                    red, green, blue, alpha = part.color
                    metal_light = min(1.0, specular * 2.4 + rim * .22)
                    metal_shade = .42 + .58 * diffuse
                    color = QColor(
                        min(255, int(red * metal_shade + 95 * metal_light + 8 * rim)),
                        min(255, int(green * metal_shade + 112 * metal_light + 24 * rim)),
                        min(255, int(blue * metal_shade + 120 * metal_light + 34 * rim)),
                        min(255, int(alpha * (.70 + .30 * diffuse) + 16 * rim)),
                    )
                else:
                    # Monochrome cyan hologram for the armor.
                    glow = min(1.0, shade * .42 + specular * 2.1 + rim * .72)
                    color = QColor(
                        int(3 + 38 * glow),
                        int(15 + 105 * glow),
                        int(24 + 128 * glow),
                        int(38 + 44 * shade + 58 * rim),
                    )
                pa, da = projected[ia]
                pb, db = projected[ib]
                pc, dc = projected[ic]
                depth = (da + db + dc) / 3
                faces.append((depth, color, (pa, pb, pc)))
                depth_triangles.append((pa, pb, pc, 20.0 + da, 20.0 + db, 20.0 + dc))

            for indices in part.wire_lines:
                run = []
                run_depth = []
                for index in indices:
                    if rotated[index][1] < -.025:
                        run.append(projected[index][0])
                        run_depth.append(projected[index][1])
                    elif len(run) > 1:
                        wire_paths.append((sum(run_depth) / len(run_depth), tuple(run),
                                           tuple(20.0 + value for value in run_depth)))
                        run, run_depth = [], []
                if len(run) > 1:
                    wire_paths.append((sum(run_depth) / len(run_depth), tuple(run),
                                       tuple(20.0 + value for value in run_depth)))

        # Coarse software depth buffer prevents hidden back-side armor seams
        # from drawing over the front plates. At 2 logical pixels per cell it
        # stays inexpensive for this lightweight Qt renderer.
        buffer_width, buffer_height = ((140, 137) if self.ai_busy else (210, 205))
        depth_scale = buffer_width / 420.0
        depth_buffer = [[float("inf")] * buffer_width for _ in range(buffer_height)]
        for pa, pb, pc, da, db, dc in depth_triangles:
            ax, ay = pa.x() * depth_scale, pa.y() * depth_scale
            bx, by = pb.x() * depth_scale, pb.y() * depth_scale
            cx, cy = pc.x() * depth_scale, pc.y() * depth_scale
            denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(denominator) < 1e-8:
                continue
            min_x = max(0, int(min(ax, bx, cx)))
            max_x = min(buffer_width - 1, int(max(ax, bx, cx)) + 1)
            min_y = max(0, int(min(ay, by, cy)))
            max_y = min(buffer_height - 1, int(max(ay, by, cy)) + 1)
            for iy in range(min_y, max_y + 1):
                py = iy + .5
                for ix in range(min_x, max_x + 1):
                    px = ix + .5
                    wa = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
                    wb = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
                    wc = 1.0 - wa - wb
                    if wa >= -.015 and wb >= -.015 and wc >= -.015:
                        inverse_depth = wa / da + wb / db + wc / dc
                        if inverse_depth > 0:
                            pixel_depth = 1.0 / inverse_depth
                            if pixel_depth < depth_buffer[iy][ix]:
                                depth_buffer[iy][ix] = pixel_depth

        faces.sort(key=lambda face: face[0], reverse=True)
        for _, color, vertices in faces:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF(list(vertices)))
        wire_paths.sort(key=lambda line: line[0], reverse=True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for _, points, depths in wire_paths:
            visible_runs = []
            current_run = []
            for segment in range(len(points) - 1):
                start, end = points[segment], points[segment + 1]
                start_depth, end_depth = depths[segment], depths[segment + 1]
                dx, dy = end.x() - start.x(), end.y() - start.y()
                steps = max(1, int(max(abs(dx), abs(dy)) * .75))
                for step in range(steps + 1):
                    fraction = step / steps
                    px = start.x() + dx * fraction
                    py = start.y() + dy * fraction
                    ix, iy = int(px * depth_scale), int(py * depth_scale)
                    inside = 0 <= ix < buffer_width and 0 <= iy < buffer_height
                    line_depth = start_depth + (end_depth - start_depth) * fraction
                    visible = (inside and line_depth <= depth_buffer[iy][ix] + .18)
                    if visible:
                        point = QPointF(px, py)
                        if (not current_run or
                                abs(px - current_run[-1].x())
                                + abs(py - current_run[-1].y()) > .45):
                            current_run.append(point)
                    elif len(current_run) > 1:
                        visible_runs.append(tuple(current_run))
                        current_run = []
                    else:
                        current_run = []
            if len(current_run) > 1:
                visible_runs.append(tuple(current_run))
            for visible_points in visible_runs:
                path = QPolygonF(list(visible_points))
                # A soft wide pass below a crisp core line gives the wireframe
                # emissive bloom without revealing lines behind front plates.
                if self.model == "iron_hand":
                    # Keep the red armor readable; a subdued hologram trace
                    # should accent its shape instead of outlining every seam.
                    painter.setPen(QPen(QColor(30, 190, 225, 8 + int(pulse * 3)), 2.0))
                    painter.drawPolyline(path)
                    painter.setPen(QPen(QColor(118, 225, 240, 58 + int(pulse * 16)), .55))
                    painter.drawPolyline(path)
                else:
                    painter.setPen(QPen(QColor(30, 190, 225, 12 + int(pulse * 5)), 3.8))
                    painter.drawPolyline(path)
                    painter.setPen(QPen(QColor(55, 210, 238, 30 + int(pulse * 9)), 1.9))
                    painter.drawPolyline(path)
                    painter.setPen(QPen(QColor(118, 235, 250, 116 + int(pulse * 32)), .72))
                    painter.drawPolyline(path)

        if self.model == "arc_reactor":
            core, _ = self._project((0, -.98, 4.25), yaw, pitch,
                                    self.gesture_zoom)
            power_wave = (math.sin((monotonic() - self._power_started) * 18) + 1) / 2
            radius = (112 if self.power_active else 70) * min(
                self.width() / 420, self.height() / 410
            ) * self.gesture_zoom
            glow = QRadialGradient(core, radius * 1.8)
            glow.setColorAt(0, QColor(185, 250, 255, 225 if self.power_active else 150))
            glow.setColorAt(.28, QColor(63, 232, 255,
                                        int(165 + 65 * power_wave) if self.power_active else 90))
            glow.setColorAt(.58, QColor(40, 190, 230,
                                        130 if self.power_active else 70))
            glow.setColorAt(1, QColor(8, 54, 88, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(core.x()-radius*1.8, core.y()-radius*1.8,
                                       radius*3.6, radius*3.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.power_active:
                ring_radius = radius * (1.16 + .12 * power_wave)
                painter.setPen(QPen(QColor(106, 241, 255, 150), 2.4))
                painter.drawEllipse(QRectF(core.x()-ring_radius, core.y()-ring_radius,
                                           ring_radius*2, ring_radius*2))
                core_glow = QRadialGradient(core, radius * .42)
                core_glow.setColorAt(0, QColor(235, 254, 255, 240))
                core_glow.setColorAt(.38, QColor(94, 234, 255, 190))
                core_glow.setColorAt(1, QColor(40, 175, 255, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(core_glow)
                painter.drawEllipse(QRectF(core.x()-radius*.42, core.y()-radius*.42,
                                           radius*.84, radius*.84))
            return core
        if self.model != "suit":
            if self.model == "web_shooter" and self.power_active:
                self._draw_web_projectile(painter, yaw, pitch)
            if self.model == "iron_hand":
                hand_pose = IRON_HAND_POSE
                repulsor_z = 4.28 - 4.25
                repulsor_x = repulsor_z * math.sin(hand_pose)
                repulsor_z = 4.25 + repulsor_z * math.cos(hand_pose)
                core, _ = self._project((repulsor_x, -.71, repulsor_z), yaw, pitch,
                                        self.gesture_zoom)
                radius = (48 if self.power_active else 28) * min(
                    self.width() / 420, self.height() / 410
                ) * self.gesture_zoom
                repulsor_glow = QRadialGradient(core, radius * 1.7)
                repulsor_glow.setColorAt(
                    0, QColor(255, 255, 255, 245 if self.power_active else 190)
                )
                repulsor_glow.setColorAt(
                    .45, QColor(169, 231, 245, 145 if self.power_active else 62)
                )
                repulsor_glow.setColorAt(1, QColor(25, 120, 220, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(repulsor_glow)
                painter.drawEllipse(QRectF(core.x()-radius*1.7, core.y()-radius*1.7,
                                           radius*3.4, radius*3.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                if self.power_active:
                    painter.setPen(QPen(QColor(154, 242, 255, 185), 2.0))
                    painter.drawEllipse(QRectF(core.x()-radius, core.y()-radius,
                                               radius*2, radius*2))
                return core
            return self._project((0, -.75, 4.22), yaw, pitch,
                                 self.gesture_zoom)[0]

        # Reactor bloom and concentric HUD rings sit in front of the suit.
        core_point = (0, -.93, 6.47 + self.flight_lift)
        core, _ = self._project(core_point, yaw, pitch, self.gesture_zoom)
        radius = 20 * min(self.width() / 420, self.height() / 410) * self.gesture_zoom
        glow = QRadialGradient(core, radius * 1.75)
        glow.setColorAt(0, QColor(63, 232, 255, 92))
        glow.setColorAt(.40, QColor(40, 190, 230, 34))
        glow.setColorAt(1, QColor(8, 54, 88, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(core.x()-radius*1.75, core.y()-radius*1.75,
                                   radius*3.5, radius*3.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(88, 238, 255, 132), 1.0))
        painter.drawEllipse(QRectF(core.x()-radius, core.y()-radius, radius*2, radius*2))
        painter.setPen(QPen(QColor(185, 251, 255, 195), 1.6))
        painter.drawEllipse(QRectF(core.x()-radius*.55, core.y()-radius*.55,
                                   radius*1.1, radius*1.1))
        if self.power_active:
            self._draw_flight_thrusters(painter, yaw, pitch)
        return core

    def _draw_web_projectile(self, painter: QPainter, yaw: float, pitch: float) -> None:
        elapsed = monotonic() - self._power_started
        interval = .52
        age = elapsed % interval
        progress = min(1.0, age / .20)
        fade = max(0.0, min(1.0, (interval - age) / .10))
        angle = math.radians(22)
        direction_x, direction_z = math.cos(angle), -math.sin(angle)
        muzzle_x = 1.04 * math.cos(angle)
        muzzle_z = 4.25 - 1.04 * math.sin(angle)
        start = (muzzle_x + .10 * direction_x, -1.04,
                 muzzle_z + .10 * direction_z)
        end = (muzzle_x + 4.8 * direction_x, -1.04,
               muzzle_z + 4.8 * direction_z)
        start_point = self._project(start, yaw, pitch, self.gesture_zoom)[0]
        end_point = self._project(end, yaw, pitch, self.gesture_zoom)[0]
        tip = QPointF(start_point.x() + (end_point.x() - start_point.x()) * progress,
                      start_point.y() + (end_point.y() - start_point.y()) * progress)
        dx, dy = end_point.x() - start_point.x(), end_point.y() - start_point.y()
        projected_length = max(1.0, math.hypot(dx, dy))
        dx, dy = dx / projected_length, dy / projected_length
        perpendicular = QPointF(-dy, dx)

        # A soft blue cast sits beneath several irregular white web fibers.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPainterPath()
        halo.moveTo(start_point)
        halo.cubicTo(
            QPointF(start_point.x() + dx * projected_length * .32,
                    start_point.y() + dy * projected_length * .32),
            QPointF(tip.x() - dx * projected_length * .28,
                    tip.y() - dy * projected_length * .28),
            tip,
        )
        painter.setPen(QPen(QColor(74, 195, 255, int(45 * fade)), 8.0))
        painter.drawPath(halo)

        for strand_index, offset in enumerate((-3.2, -1.5, 0.0, 1.7, 3.5)):
            bend = math.sin(elapsed * 11 + strand_index * 1.3) * (3.0 + abs(offset) * .55)
            strand_start = QPointF(start_point.x() + perpendicular.x() * offset,
                                   start_point.y() + perpendicular.y() * offset)
            strand_end = QPointF(tip.x() + perpendicular.x() * (offset + bend),
                                 tip.y() + perpendicular.y() * (offset + bend))
            path = QPainterPath()
            path.moveTo(strand_start)
            path.cubicTo(
                QPointF(strand_start.x() + dx * projected_length * .30 + perpendicular.x() * bend,
                        strand_start.y() + dy * projected_length * .30 + perpendicular.y() * bend),
                QPointF(strand_end.x() - dx * projected_length * .27 - perpendicular.x() * bend * .35,
                        strand_end.y() - dy * projected_length * .27 - perpendicular.y() * bend * .35),
                strand_end,
            )
            width = 2.5 if strand_index == 2 else 1.15
            alpha = int((238 if strand_index == 2 else 178) * fade)
            painter.setPen(QPen(QColor(235, 251, 255, alpha), width))
            painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(245, 254, 255, int(220 * fade)))
        painter.drawEllipse(QRectF(tip.x()-2.5, tip.y()-2.5, 5, 5))

    def _draw_flight_thrusters(self, painter: QPainter, yaw: float, pitch: float) -> None:
        length = 28 + 12 * ((math.sin((monotonic() - self._power_started) * 13) + 1) / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        for side in (-1, 1):
            foot = self._project((side * .47, -.42,
                                  .16 + self.flight_lift),
                                 yaw, pitch, self.gesture_zoom)[0]
            flame = QPainterPath()
            flame.moveTo(foot.x()-5, foot.y()-1)
            flame.lineTo(foot.x(), foot.y()+length)
            flame.lineTo(foot.x()+5, foot.y()-1)
            flame.closeSubpath()
            gradient = QLinearGradient(foot.x(), foot.y(), foot.x(), foot.y()+length)
            gradient.setColorAt(0, QColor(202, 252, 255, 230))
            gradient.setColorAt(.35, QColor(61, 219, 255, 180))
            gradient.setColorAt(1, QColor(37, 153, 255, 0))
            painter.setBrush(gradient)
            painter.drawPath(flame)
            painter.setBrush(QColor(50, 210, 255, 35))
            painter.drawEllipse(QRectF(foot.x()-10, foot.y()-2, 20, 18))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 420, self.height() / 410)
        painter.translate((self.width() - 420 * scale) / 2,
                          (self.height() - 410 * scale) / 2)
        painter.scale(scale, scale)
        pulse = (math.sin(math.radians(self.phase * 2)) + 1) / 2

        painter.setPen(QPen(QColor(45, 213, 244, 42), 1))
        painter.setBrush(QColor(2, 13, 22, 34))
        painter.drawRoundedRect(QRectF(38, 22, 344, 342), 10, 10)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(48, 42, 48, 348)
        painter.drawLine(372, 42, 372, 348)
        for y in range(52, 350, 26):
            painter.drawLine(43, y, 50, y)
            painter.drawLine(370, y, 377, y)

        lift = QRadialGradient(210, 352, 145)
        lift.setColorAt(0, QColor(26, 142, 171, 42))
        lift.setColorAt(.60, QColor(18, 86, 112, 17))
        lift.setColorAt(1, QColor(5, 20, 31, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(lift)
        painter.drawEllipse(QRectF(58, 300, 304, 82))

        # A perspective orbit plane behind the figure makes its rotation obvious.
        orbit = []
        for step in range(97):
            angle = 2 * math.pi * step / 96
            point, _ = self._project((2.18 * math.cos(angle),
                                      .35 * math.sin(angle), 4.35),
                                     self._current_yaw(), 0.0, self.gesture_zoom)
            orbit.append(point)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(67, 217, 245, 50 + int(pulse * 20)), 1.0))
        painter.drawPolyline(QPolygonF(orbit))

        for rect, start, span, color in (
            (QRectF(54, 28, 312, 312), int(self.phase * 14), 60, QColor(72, 221, 247, 105)),
            (QRectF(72, 45, 276, 276), int(-self.phase * 9), 45, QColor(72, 221, 247, 67)),
        ):
            painter.setPen(QPen(color, 1.4))
            painter.drawArc(rect, start, span * 16)

        self._draw_suit(painter, pulse)

        # Sweeping light passes over the 3D silhouette without obscuring it.
        scan_y = 34 + (self.phase * 1.35 % 310)
        beam = QLinearGradient(84, scan_y, 336, scan_y)
        beam.setColorAt(0, QColor(41, 220, 255, 0))
        beam.setColorAt(.5, QColor(88, 242, 255, 18 + int(pulse * 22)))
        beam.setColorAt(1, QColor(41, 220, 255, 0))
        painter.fillRect(QRectF(72, scan_y - 5, 276, 10), beam)
        painter.setPen(QPen(QColor(106, 244, 255, 65), .8))
        painter.drawLine(108, scan_y, 312, scan_y)

        painter.setPen(QColor("#b8f5ff"))
        font = painter.font()
        font.setPointSize(13)
        font.setBold(True)
        painter.setFont(font)
        model_labels = {
            "suit": ("3D 슈트 홀로그램  /  MK-01" if self.language == "ko"
                     else "3D SUIT HOLOGRAM  /  MK-01"),
            "web_shooter": ("3D 웹슈터 홀로그램  /  WS-01" if self.language == "ko"
                            else "3D WEB SHOOTER HOLOGRAM  /  WS-01"),
            "arc_reactor": ("3D 아크 리액터 홀로그램  /  AR-01" if self.language == "ko"
                            else "3D ARC REACTOR HOLOGRAM  /  AR-01"),
            "iron_hand": ("3D 아이언맨 손 홀로그램  /  IH-01" if self.language == "ko"
                          else "3D IRON MAN HAND HOLOGRAM  /  IH-01"),
        }
        painter.drawText(QRectF(24, 8, 360, 20), Qt.AlignmentFlag.AlignLeft,
                         model_labels[self.model])

        painter.setPen(QColor("#83c8d8"))
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(35, 365, 120, 12), Qt.AlignmentFlag.AlignLeft,
                         "동력 출력" if self.language == "ko" else "POWER LEVEL")
        painter.drawText(QRectF(320, 365, 65, 12), Qt.AlignmentFlag.AlignRight, "100.0%")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(13, 40, 52, 190))
        painter.drawRoundedRect(QRectF(35, 378, 350, 5), 2, 2)
        painter.setBrush(QColor(62, 211, 234, 190))
        painter.drawRoundedRect(QRectF(35, 378, 340, 5), 2, 2)
        painter.setPen(QPen(QColor(4, 14, 22, 160), 1))
        for segment in range(1, 25):
            x = 35 + segment * 14
            painter.drawLine(x, 378, x, 383)
        painter.setPen(QColor("#6db5ca"))
        font.setPointSize(6)
        font.setBold(False)
        painter.setFont(font)
        caption = "3D 실시간 회전 · 스캔 중" if self.language == "ko" else "3D ROTATION · SCANNING"
        painter.drawText(QRectF(24, 387, 372, 13), Qt.AlignmentFlag.AlignHCenter, caption)

