/* The DTGC platform file for doomgeneric (https://github.com/ozkl/doomgeneric), the portable Doom engine.
 *
 * Usage: built by scripts/get_doom.py together with the engine, then started by: python -m sw.dtgc doom
 *
 * doomgeneric asks a platform for six small functions: start, show a frame, sleep, tell the time, hand over a key,
 * and set a title. This file answers them over a local socket. The Python side (sw/dtgc/doom.py) listens on that
 * socket, sends each frame on to the DTGC board, and sends back the keys pressed in its window.
 *
 * Build with -DCMAP256 -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200. With CMAP256 the engine hands over one byte per
 * pixel, a number into a table of 256 colours, which is exactly what DTGC stores. Without it the engine hands over
 * full colour, and this file cuts each pixel down to DTGC's built-in 3-3-2 colours, which looks coarser.
 *
 * Messages, engine to PC:   'P' then 768 bytes     the 256 colours, as red, green, blue
 *                           'D'                    use DTGC's built-in colours (the build without CMAP256)
 *                           'F' w(2) h(2) pixels   one frame, w*h bytes, low byte of w and h first
 *                           'T' n(2) text          the window title
 * Messages, PC to engine:   'K' pressed(1) key(1)  a key went down (1) or up (0). Key numbers are listed below.
 *
 * This file is ours. The engine it is compiled with is under the GNU GPL version 2, so the program built from the two
 * together is as well.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "doomgeneric.h"
#include "doomkeys.h"
#include "i_video.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN /* leaves out the Windows headers that have their own "boolean", which clashes with the engine's */
#include <winsock2.h>
#include <windows.h>
typedef SOCKET socket_t;
#define close_socket closesocket
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
typedef int socket_t;
#define INVALID_SOCKET (-1)
#define close_socket close
#endif

/* Key numbers the PC sends. Below 128 a number is the plain character (letters in lower case). The rest are ours,
 * and are turned into the engine's own numbers here, so those always come from the engine's doomkeys.h.
 * sw/dtgc/doom.py holds the same list. */
enum {
    PC_LEFT = 128, PC_RIGHT, PC_UP, PC_DOWN, PC_FIRE, PC_USE, PC_STRAFE_LEFT, PC_STRAFE_RIGHT, PC_RUN, PC_STRAFE,
    PC_ESCAPE, PC_ENTER, PC_TAB, PC_BACKSPACE, PC_PAUSE, PC_F1 /* F1 to F12 follow on: 143 to 154 */
};

#define QUEUE_SIZE 64

static socket_t link_socket = INVALID_SOCKET;
static unsigned char key_queue[QUEUE_SIZE][2];
static int queue_head, queue_tail;
static unsigned char pending[3];
static int pending_count;

static void stop(const char *why)
{
    fprintf(stderr, "dtgc doom: %s\n", why);
    exit(0);
}

static void send_all(const void *data, int length)
{
    const char *bytes = (const char *)data;
    while (length > 0) {
        int sent = send(link_socket, bytes, length, 0);
        if (sent <= 0)
            stop("the DTGC window has gone, so the game stops");
        bytes += sent;
        length -= sent;
    }
}

static unsigned char engine_key(unsigned char pc)
{
    static const unsigned char function_keys[12] = {KEY_F1, KEY_F2, KEY_F3, KEY_F4, KEY_F5, KEY_F6,
                                                    KEY_F7, KEY_F8, KEY_F9, KEY_F10, KEY_F11, KEY_F12};
    if (pc < 128)
        return pc;
    if (pc >= PC_F1 && pc < PC_F1 + 12)
        return function_keys[pc - PC_F1];
    switch (pc) {
    case PC_LEFT: return KEY_LEFTARROW;
    case PC_RIGHT: return KEY_RIGHTARROW;
    case PC_UP: return KEY_UPARROW;
    case PC_DOWN: return KEY_DOWNARROW;
    case PC_FIRE: return KEY_FIRE;
    case PC_USE: return KEY_USE;
    case PC_STRAFE_LEFT: return KEY_STRAFE_L;
    case PC_STRAFE_RIGHT: return KEY_STRAFE_R;
    case PC_RUN: return KEY_RSHIFT;
    case PC_STRAFE: return KEY_RALT;
    case PC_ESCAPE: return KEY_ESCAPE;
    case PC_ENTER: return KEY_ENTER;
    case PC_TAB: return KEY_TAB;
    case PC_BACKSPACE: return KEY_BACKSPACE;
    case PC_PAUSE: return KEY_PAUSE;
    default: return 0;
    }
}

/* Takes whatever key messages have arrived, without waiting. */
static void read_keys(void)
{
    for (;;) {
        fd_set readable;
        struct timeval no_wait = {0, 0};
        unsigned char buffer[96];
        int got, i;

        FD_ZERO(&readable);
        FD_SET(link_socket, &readable);
        if (select((int)link_socket + 1, &readable, NULL, NULL, &no_wait) <= 0)
            return;
        got = recv(link_socket, (char *)buffer, sizeof buffer, 0);
        if (got <= 0)
            stop("the DTGC window has gone, so the game stops");
        for (i = 0; i < got; i++) {
            pending[pending_count++] = buffer[i];
            if (pending[0] != 'K') {
                pending_count = 0; /* not a message we know: skip the byte */
            } else if (pending_count == 3) {
                int next = (queue_tail + 1) % QUEUE_SIZE;
                unsigned char key = engine_key(pending[2]);
                if (key && next != queue_head) {
                    key_queue[queue_tail][0] = pending[1] ? 1 : 0;
                    key_queue[queue_tail][1] = key;
                    queue_tail = next;
                }
                pending_count = 0;
            }
        }
    }
}

void DG_Init(void)
{
    const char *port_text = getenv("DTGC_DOOM_PORT");
    struct sockaddr_in address;
    int no_delay = 1;
#ifdef _WIN32
    WSADATA winsock;
    if (WSAStartup(MAKEWORD(2, 2), &winsock) != 0)
        stop("could not start Windows networking");
#endif
    link_socket = socket(AF_INET, SOCK_STREAM, 0);
    if (link_socket == INVALID_SOCKET)
        stop("could not make a socket");
    memset(&address, 0, sizeof address);
    address.sin_family = AF_INET;
    address.sin_port = htons((unsigned short)(port_text ? atoi(port_text) : 7655));
    address.sin_addr.s_addr = htonl(0x7F000001); /* 127.0.0.1: this PC only */
    if (connect(link_socket, (struct sockaddr *)&address, sizeof address) != 0)
        stop("nothing is listening. Start the game with: python -m sw.dtgc doom");
    setsockopt(link_socket, IPPROTO_TCP, TCP_NODELAY, (const char *)&no_delay, sizeof no_delay);
#ifndef CMAP256
    send_all("D", 1);
#endif
}

void DG_DrawFrame(void)
{
    unsigned char header[5] = {'F', DOOMGENERIC_RESX & 255, DOOMGENERIC_RESX >> 8, DOOMGENERIC_RESY & 255, DOOMGENERIC_RESY >> 8};
#ifdef CMAP256
    static unsigned char sent_colours[1 + 768];
    unsigned char now[1 + 768];
    int i;

    /* Compared with the last table sent instead of trusting a flag, so a change can never be missed. */
    now[0] = 'P';
    for (i = 0; i < 256; i++) {
        now[1 + 3 * i] = (unsigned char)colors[i].r;
        now[2 + 3 * i] = (unsigned char)colors[i].g;
        now[3 + 3 * i] = (unsigned char)colors[i].b;
    }
    if (memcmp(now, sent_colours, sizeof now) != 0) {
        memcpy(sent_colours, now, sizeof now);
        send_all(now, sizeof now);
    }
    send_all(header, sizeof header);
    send_all(DG_ScreenBuffer, DOOMGENERIC_RESX * DOOMGENERIC_RESY);
#else
    static unsigned char reduced[DOOMGENERIC_RESX * DOOMGENERIC_RESY];
    int i;

    for (i = 0; i < DOOMGENERIC_RESX * DOOMGENERIC_RESY; i++) {
        unsigned int pixel = DG_ScreenBuffer[i]; /* 0x00RRGGBB */
        reduced[i] = (unsigned char)(((pixel >> 16) & 0xE0) | ((pixel >> 11) & 0x1C) | ((pixel >> 6) & 0x03));
    }
    send_all(header, sizeof header);
    send_all(reduced, sizeof reduced);
#endif
    read_keys();
}

void DG_SleepMs(uint32_t ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    usleep(ms * 1000);
#endif
}

uint32_t DG_GetTicksMs(void)
{
#ifdef _WIN32
    return GetTickCount();
#else
    struct timeval now;
    gettimeofday(&now, NULL);
    return (uint32_t)(now.tv_sec * 1000 + now.tv_usec / 1000);
#endif
}

int DG_GetKey(int *pressed, unsigned char *key)
{
    if (queue_head == queue_tail)
        read_keys();
    if (queue_head == queue_tail)
        return 0;
    *pressed = key_queue[queue_head][0];
    *key = key_queue[queue_head][1];
    queue_head = (queue_head + 1) % QUEUE_SIZE;
    return 1;
}

void DG_SetWindowTitle(const char *title)
{
    size_t length = strlen(title);
    unsigned char header[3];

    if (link_socket == INVALID_SOCKET)
        return;
    if (length > 200)
        length = 200;
    header[0] = 'T';
    header[1] = (unsigned char)length;
    header[2] = 0;
    send_all(header, sizeof header);
    send_all(title, (int)length);
}

int main(int argc, char **argv)
{
    doomgeneric_Create(argc, argv);
    for (;;)
        doomgeneric_Tick();
    return 0;
}
