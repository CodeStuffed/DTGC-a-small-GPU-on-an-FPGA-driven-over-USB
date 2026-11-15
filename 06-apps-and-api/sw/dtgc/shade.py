"""The reference model of rtl/shade_pipe.v, in the same whole numbers, so the two can be compared bit for bit.

Usage:
    from sw.dtgc import shade
    red, green, blue = shade.shade(normal, light, ambient, amount, x, y, base, dst, alpha)

normal and light are (x, y, z) in Q4.12, where 4096 is 1.0. ambient is Q8.8, where 256 is 1.0. alpha is 0 to 256.
amount is 0 to 255, and x and y are 0 to 255, for the noise. base and dst are (red, green, blue), 0 to 255.
"""


def noise(x, y):
    """A hash of the position, from -128 to 127, with no state."""
    value = (x << 8) | y
    value ^= (value << 7) & 0xFFFF
    value ^= value >> 9
    value ^= (value << 8) & 0xFFFF
    return (value >> 8) - 128


def light(normal, direction, ambient, amount, x, y):
    """The light on a pixel in Q8.8, from 0 to 256."""
    dot = sum(n * d for n, d in zip(normal, direction))
    diffuse = max(0, dot >> 16)
    return min(256, max(0, ambient + diffuse + ((noise(x, y) * amount) >> 8)))


def shade(normal, direction, ambient, amount, x, y, base, dst, alpha):
    amount_of_light = light(normal, direction, ambient, amount, x, y)
    lit = [(colour * amount_of_light + 128) >> 8 for colour in base]
    return tuple(old + (((new - old) * alpha + 128) >> 8) for new, old in zip(lit, dst))
