/* Stand-in for doomgeneric's i_video.h, for tests only: the colour table the DTGC platform file reads. */
#ifndef __I_VIDEO__
#define __I_VIDEO__

#include <stdint.h>

typedef enum { false, true } boolean;

struct color {
    uint32_t b : 8;
    uint32_t g : 8;
    uint32_t r : 8;
    uint32_t a : 8;
};

#ifdef CMAP256
extern boolean palette_changed;
extern struct color colors[256];
#endif

#endif
