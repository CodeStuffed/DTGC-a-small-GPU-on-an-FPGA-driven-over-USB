"""DT-Upscale: the reference model of the hardware picture scaler. No neural networks.

Usage:
    from sw.dtgc import upscale
    big = upscale.upscale(small, 2, "bicubic", sharpen=2)    # small is an H x W x 3 uint8 array
    upscale.psnr(reference, big), upscale.ssim(reference, big)

Whole-number scales only, integer maths only, and each output pixel depends on a small window of
input pixels, so all of this can become a pipeline of adders and small line memories.

Methods:
    nearest   repeats pixels. The baseline, and it costs nothing
    bilinear  blends the 4 nearest pixels
    bicubic   blends the 16 nearest pixels with Catmull-Rom weights, which keeps edges crisper
    edge      splits each square of 4 pixels into 2 triangles along whichever diagonal has the smaller
              difference, then blends inside the triangle, so diagonal edges do not turn into stairs

sharpen adds back part of the difference between a pixel and its 2 neighbours along each axis.
"""
import numpy as np

METHODS = ("nearest", "bilinear", "bicubic", "edge")
FRACTION_BITS = 8
ONE = 1 << FRACTION_BITS


def catmull_rom_weights(phase, scale):
    """The 4 weights for a position phase / scale between two pixels, in 1/256ths, always summing to 256."""
    t = phase / scale
    exact = [(-t ** 3 + 2 * t ** 2 - t) / 2, (3 * t ** 3 - 5 * t ** 2 + 2) / 2,
             (-3 * t ** 3 + 4 * t ** 2 + t) / 2, (t ** 3 - t ** 2) / 2]
    weights = [round(w * ONE) for w in exact]
    weights[1] += ONE - sum(weights)
    return weights


def _positions(size, scale):
    """Input pixel and phase for each output position, with phase in units of 1 / (2 * scale).

    The middles of the two pictures line up: each input pixel covers a block of scale output pixels, and
    the output pixels sit evenly around its centre. Input pixel -1 means the blend starts off the picture.
    """
    position = 2 * np.arange(size * scale) + 1 - scale
    return position // (2 * scale), position % (2 * scale)


def _shift_round(values, bits):
    return (values + (1 << (bits - 1))) >> bits


def _nearest(image, scale):
    return image.repeat(scale, axis=0).repeat(scale, axis=1).astype(np.int64)


def _bilinear(image, scale):
    return _blend_axes(image, scale, lambda phase: [0, ONE - phase * ONE // (2 * scale), phase * ONE // (2 * scale), 0])


def _bicubic(image, scale):
    return _blend_axes(image, scale, lambda phase: catmull_rom_weights(phase, 2 * scale))


def _blend_axes(image, scale, weights_for):
    """Filters across, then down, as hardware would with one horizontal and one vertical stage."""
    table = np.array([weights_for(phase) for phase in range(2 * scale)], dtype=np.int64)
    work = image.astype(np.int64)
    for axis in (1, 0):
        size = work.shape[axis]
        pixel, phase = _positions(size, scale)
        out = 0
        for tap in range(4):
            source = np.clip(pixel + tap - 1, 0, size - 1)
            shape = [1, 1, 1]
            shape[axis] = -1
            out = out + np.take(work, source, axis=axis) * table[phase, tap].reshape(shape)
        # Keep the rows' extra precision until the second stage, then drop everything at once.
        work = out
    return np.clip(_shift_round(work, 2 * FRACTION_BITS), 0, 255)


def luma(image):
    """A cheap brightness: (r + 2g + b) / 4, which needs only adders."""
    image = image.astype(np.int64)
    return (image[..., 0] + 2 * image[..., 1] + image[..., 2]) >> 2


def _edge(image, scale):
    height, width = image.shape[:2]
    y_pixel, y_phase = _positions(height, scale)
    x_pixel, x_phase = _positions(width, scale)
    x_pixel, y_pixel = np.clip(x_pixel, -1, width - 1), np.clip(y_pixel, -1, height - 1)
    x_before, y_before = np.meshgrid(x_pixel, y_pixel)
    u, v = np.meshgrid(x_phase, y_phase)
    x0, y0 = np.maximum(x_before, 0), np.maximum(y_before, 0)
    x1, y1 = np.minimum(x_before + 1, width - 1), np.minimum(y_before + 1, height - 1)
    work = image.astype(np.int64)
    a, b, c, d = work[y0, x0], work[y0, x1], work[y1, x0], work[y1, x1]
    gray = luma(image)
    main_gap = np.abs(gray[y0, x0] - gray[y1, x1])    # a to d
    other_gap = np.abs(gray[y0, x1] - gray[y1, x0])   # b to c
    use_main = (main_gap <= other_gap)[..., None]
    u, v = u[..., None], v[..., None]
    # Each result is the three corners of one triangle, in units of 1 / unit.
    unit = 2 * scale
    upper = unit * a + u * (b - a) + v * (d - b)      # main diagonal, u >= v
    lower = unit * a + u * (d - c) + v * (c - a)      # main diagonal, u < v
    main = np.where(u >= v, upper, lower)
    near = unit * a + u * (b - a) + v * (c - a)       # other diagonal, u + v <= unit
    far = unit * d + (unit - u) * (c - d) + (unit - v) * (b - d)
    other = np.where(u + v <= unit, near, far)
    picked = np.where(use_main, main, other)
    return np.clip((picked + scale) // unit, 0, 255)


def _sharpen(image, amount):
    """Each axis: pixel + (2 * pixel - both neighbours) * amount / 8. Amount 0 changes nothing."""
    if amount == 0:
        return image
    out = image.astype(np.int64)
    for axis in (1, 0):
        before = np.roll(out, 1, axis=axis)
        after = np.roll(out, -1, axis=axis)
        # At the picture's edge a pixel is its own missing neighbour.
        if axis == 1:
            before[:, 0], after[:, -1] = out[:, 0], out[:, -1]
        else:
            before[0, :], after[-1, :] = out[0, :], out[-1, :]
        out = out + (((2 * out - before - after) * amount) >> 3)
    return np.clip(out, 0, 255)


def upscale(image, scale, method="bicubic", sharpen=0):
    """Returns an array of the same type, scale times the width and height."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method}, choose from {METHODS}")
    if scale < 1 or scale != int(scale):
        raise ValueError("scale must be a whole number of at least 1")
    do = {"nearest": _nearest, "bilinear": _bilinear, "bicubic": _bicubic, "edge": _edge}[method]
    return _sharpen(do(image, scale), sharpen).astype(np.uint8)


def downscale(image, scale):
    """Averages blocks of pixels. Makes the small test input from a large reference picture."""
    height, width = image.shape[0] // scale * scale, image.shape[1] // scale * scale
    blocks = image[:height, :width].astype(np.int64).reshape(height // scale, scale, width // scale, scale, 3)
    return ((blocks.sum(axis=(1, 3)) + scale * scale // 2) // (scale * scale)).astype(np.uint8)


def psnr(reference, picture):
    """Peak signal-to-noise ratio in dB. Higher is closer. Infinite when the pictures are identical."""
    error = np.mean((reference.astype(np.float64) - picture.astype(np.float64)) ** 2)
    return float("inf") if error == 0 else 10 * np.log10(255 ** 2 / error)


def ssim(reference, picture, window=8):
    """Structural similarity on brightness over 8 x 8 blocks: 1 is identical. A simple form, not a library's."""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    a, b = luma(reference).astype(np.float64), luma(picture).astype(np.float64)
    rows, columns = a.shape[0] // window, a.shape[1] // window
    a = a[:rows * window, :columns * window].reshape(rows, window, columns, window)
    b = b[:rows * window, :columns * window].reshape(rows, window, columns, window)
    mean_a, mean_b = a.mean(axis=(1, 3)), b.mean(axis=(1, 3))
    var_a, var_b = a.var(axis=(1, 3)), b.var(axis=(1, 3))
    together = ((a - mean_a[:, None, :, None]) * (b - mean_b[:, None, :, None])).mean(axis=(1, 3))
    scores = ((2 * mean_a * mean_b + c1) * (2 * together + c2)) / ((mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2))
    return float(scores.mean())
