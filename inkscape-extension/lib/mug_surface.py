"""Mug body surface: half-profile storage and radius interpolation."""

from __future__ import annotations


class MugSurface:
    """Represents a mug body as an axially symmetric half-profile.

    The profile is a polyline of (radius, z) points in mm.
    The mug axis is at the minimum X of the raw profile; all stored
    radii are relative to that axis.
    """

    def __init__(self, raw_profile: list[list[float]]) -> None:
        """Initialize from raw profile points [[x, z], ...].

        Args:
            raw_profile: Points where x is distance from SVG left edge
                         and z is height. Y is already inverted (z up).
        """
        if len(raw_profile) < 2:
            raise ValueError("Mug profile must have at least 2 points")

        axis_x = min(p[0] for p in raw_profile)
        self.axis_x = axis_x

        # Store as (radius, z) sorted by z ascending
        self.profile: list[tuple[float, float]] = sorted(
            ((p[0] - axis_x, p[1]) for p in raw_profile),
            key=lambda p: p[1],
        )

        for r, z in self.profile:
            if r < -1e-9:
                raise ValueError(
                    f"Profile point has negative radius {r:.4f} at z={z:.4f} "
                    f"(axis_x={axis_x:.4f}). All points must be at or right of the axis."
                )

    @property
    def z_min(self) -> float:
        return self.profile[0][1]

    @property
    def z_max(self) -> float:
        return self.profile[-1][1]

    def radius_at_z(self, z: float) -> float | None:
        """Linearly interpolate radius at a given z height.

        Returns None if z is outside the profile's z range.
        """
        if z < self.profile[0][1] - 1e-9 or z > self.profile[-1][1] + 1e-9:
            return None

        # Clamp to range
        z = max(self.profile[0][1], min(z, self.profile[-1][1]))

        # Find the segment containing z
        for i in range(len(self.profile) - 1):
            r0, z0 = self.profile[i]
            r1, z1 = self.profile[i + 1]
            if z0 <= z <= z1 + 1e-9:
                if abs(z1 - z0) < 1e-12:
                    return r0
                t = (z - z0) / (z1 - z0)
                return r0 + t * (r1 - r0)

        return self.profile[-1][0]
