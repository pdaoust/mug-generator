"""Mug body surface: half-profile storage and radius interpolation."""

from __future__ import annotations


class MugSurface:
    """Represents a mug body as an axially symmetric half-profile.

    The profile is a polyline of (radius, z) points in mm.
    The mug axis is at the document X origin (x=0); all stored
    radii are the raw X coordinates.
    """

    def __init__(self, raw_profile: list[list[float]]) -> None:
        """Initialize from raw profile points [[x, z], ...].

        Args:
            raw_profile: Points where x is distance from the document
                         X origin (the mug axis) and z is height.
        """
        if len(raw_profile) < 2:
            raise ValueError("Mug profile must have at least 2 points")

        self.axis_x = 0.0

        # Store as (radius, z) sorted by z ascending
        self.profile: list[tuple[float, float]] = sorted(
            ((p[0], p[1]) for p in raw_profile),
            key=lambda p: p[1],
        )

        for r, z in self.profile:
            if r < -1e-9:
                raise ValueError(
                    f"Profile point has negative radius {r:.4f} at z={z:.4f}. "
                    f"All points must be at or right of the document X origin."
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

    def detect_foot_concavity(self) -> tuple[float, float] | None:
        """Detect foot concavity in the outer profile.

        A concave foot (like a foot ring) has the bottom of the profile at
        some radius R_foot, then the radius decreases (tucks inward) before
        increasing again as the body wall begins.

        Returns:
            (foot_concavity_z, foot_concavity_radius) if concave, else None.
            foot_concavity_radius: radius of the foot ring at the bottom.
            foot_concavity_z: Z height where the profile radius returns to
                              foot_concavity_radius (top of the concavity).
        """
        r_foot = self.profile[0][0]

        # Walk upward from the bottom looking for any point with radius < r_foot
        has_concavity = False
        for r, z in self.profile[1:]:
            if r < r_foot - 1e-9:
                has_concavity = True
                break

        if not has_concavity:
            return None

        # Find the Z at which radius returns to r_foot (interpolate)
        for i in range(1, len(self.profile)):
            r0, z0 = self.profile[i - 1]
            r1, z1 = self.profile[i]
            if r0 < r_foot - 1e-9 and r1 >= r_foot - 1e-9:
                # Interpolate the crossing
                if abs(r1 - r0) < 1e-12:
                    return (z0, r_foot)
                t = (r_foot - r0) / (r1 - r0)
                crossing_z = z0 + t * (z1 - z0)
                return (crossing_z, r_foot)

        # Concavity never resolves (profile stays tucked in) — treat as concave
        # up to the top of the profile
        return (self.profile[-1][1], r_foot)
