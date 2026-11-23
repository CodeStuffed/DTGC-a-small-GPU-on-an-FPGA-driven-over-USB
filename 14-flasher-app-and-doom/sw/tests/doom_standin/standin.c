/* A stand-in for the Doom engine, for tests only. It is NOT Doom and draws no game.
 *
 * It behaves towards the DTGC platform file the way doomgeneric does: it owns the frame buffer and the colour table,
 * calls DG_Init once, then on every tick draws a frame, asks for keys and sleeps. What it draws is chosen so a test
 * can check every part of the path:
 *   - a pattern that moves one step each frame, so frames can be told apart
 *   - a block in the top left corner holding the engine's number for the last key pressed, and 0 once it is let go
 *   - a new colour table on the fourth frame
 * It stops when the other end of the link goes away.
 */
#include <string.h>

#include "doomgeneric.h"
#include "i_video.h"

pixel_t *DG_ScreenBuffer;

#ifdef CMAP256
boolean palette_changed;
struct color colors[256];

static void set_colours(int shift)
{
    int i;
    for (i = 0; i < 256; i++) {
        colors[i].r = (uint32_t)((i + shift) & 255);
        colors[i].g = (uint32_t)(255 - i);
        colors[i].b = (uint32_t)(i / 2);
        colors[i].a = 0;
    }
    palette_changed = true;
}
#endif

static int frame_number;
static unsigned char shown_key;

void doomgeneric_Create(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    DG_ScreenBuffer = malloc(DOOMGENERIC_RESX * DOOMGENERIC_RESY * sizeof(pixel_t));
#ifdef CMAP256
    set_colours(0);
#endif
    DG_Init();
    DG_SetWindowTitle("stand-in engine");
}

void doomgeneric_Tick(void)
{
    int pressed, x, y;
    unsigned char key;

    while (DG_GetKey(&pressed, &key))
        shown_key = pressed ? key : 0;
#ifdef CMAP256
    if (frame_number == 3)
        set_colours(100);
#endif
    for (y = 0; y < DOOMGENERIC_RESY; y++)
        for (x = 0; x < DOOMGENERIC_RESX; x++) {
            unsigned char value = (x < 8 && y < 8) ? shown_key : (unsigned char)((((x / 16) + (y / 16) + frame_number) & 15) * 17);
#ifdef CMAP256
            DG_ScreenBuffer[y * DOOMGENERIC_RESX + x] = value;
#else
            DG_ScreenBuffer[y * DOOMGENERIC_RESX + x] = (pixel_t)value * 0x010101; /* the same grey in red, green and blue */
#endif
        }
    frame_number++;
    DG_DrawFrame();
    DG_SleepMs(5);
}
