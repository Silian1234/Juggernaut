"""Turned lands, an oil groove and grip serrations on the approved knee drives.

The coordinates are the centres and outer radius used by lower_frame.actuator.
Project onto the existing moving shell in its rest space; the baked finish then
follows the original skin weights in every pose.
"""
import numpy as np


def ramp(low, high, x):
    u = np.clip((x-low)/(high-low), 0, 1)
    return u*u*(3-2*u)


def apply(material, name, p, n, color, height, spec, gloss, metal):
    if not name.lower().startswith("legframe_"):
        return color, height, spec, gloss, metal
    side = 1 if "_l_" in name.lower() else -1
    x = p[:, 0]*side - .322
    y = p[:, 1] + .0396617
    z = p[:, 2] - .5106257
    r = np.hypot(y, z)
    is_drive = (r < .0435) & (x > -.0155) & (x < .0255)
    if not np.any(is_drive) or any(t in material.lower() for t in ("rubber","polymer","cable","webbing")):
        return color, height, spec, gloss, metal
    theta = np.arctan2(z, y)
    # Exclude the hex heads and their sockets from the annular face treatment.
    normal_x = side*n[:, 0]
    face = is_drive * ramp(.70, .94, normal_x) * ramp(.0175, .0194, x)
    land = face * ramp(.009, .0118, r) * (1-ramp(.0252,.0273,r))
    grooves = np.exp(-((r-.0208)/.00112)**2)*land
    concentric = (.5+.5*np.cos((r-.011)*2*np.pi/.00285))**1.6 * land
    # Millimetre-wide radial indicator cuts on part of the central land.
    theta_distance = np.abs(np.arctan2(np.sin(18*theta+.4), np.cos(18*theta+.4)))
    scale = (1-ramp(.18,.60,theta_distance))*ramp(.014,.0152,r)*(1-ramp(.017,.0181,r))
    scale *= land * ramp(-.18,.12,np.cos(theta-.4))
    # Transverse shallow flutes form a grip on the side wall of the can.
    barrel = is_drive * (1-ramp(.46,.81,np.abs(normal_x))) * ramp(.035,.040,r)
    barrel *= ramp(.001,.0045,x)*(1-ramp(.015,.0195,x))
    flutes = (.5+.5*np.cos(34*theta+120*x))**2 * barrel
    height += -.00070*grooves + .00025*concentric - .00037*scale - .00048*flutes
    color *= (1 - .33*grooves - .23*scale - .165*flutes)[:,None]
    if spec.ndim == 2:
        polished = (.23*concentric)[:,None]
        spec += (np.array([.73,.77,.80],np.float32)-spec)*polished
        spec *= (1 - .36*grooves - .20*flutes)[:,None]
    else:
        spec += (.76-spec)*(.23*concentric)
        spec *= 1 - .36*grooves - .20*flutes
    gloss += (.70-gloss)*(.36*concentric + .24*grooves)
    return color,height,spec,gloss,metal
