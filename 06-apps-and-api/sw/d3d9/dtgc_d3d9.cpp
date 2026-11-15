// DTGC Direct3D 9 layer: a d3d9.dll that sits next to a program and draws through the DTGC protocol.
//
// Usage: python sw/d3d9/build.py, then copy build/d3d9/<x86 or x64>/d3d9.dll next to a program of the same
// bitness. Start `python -m sw.dtgc emulator` first (or `python -m sw.dtgc bridge` for real hardware).
// Environment: DTGC_PORT (default 7654), DTGC_D3D9_LOG=<file> lists the calls a program made that this
// layer does not support.
//
// This is a subset: the fixed-function part of Direct3D 9 only. No shaders, no alpha blending, no
// render-to-texture. See docs/direct3d.md for what works and what does not. The picture goes to the GPU, so
// the program's own window stays empty.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <d3d9.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <vector>

namespace {

const int SIDE = 340;
const float GUARD = 4.9f;  // keeps clipped corners inside the GPU's coordinate limit of +-1024 pixels

void note_unsupported(const char *name) {
    static char path[MAX_PATH];
    static bool checked = false;
    if (!checked) {
        checked = true;
        GetEnvironmentVariableA("DTGC_D3D9_LOG", path, MAX_PATH);
    }
    if (path[0]) {
        FILE *file = nullptr;
        if (fopen_s(&file, path, "a") == 0) {
            fprintf(file, "unsupported: %s\n", name);
            fclose(file);
        }
    }
}

// The link ---------------------------------------------------------------------------------------------------
// The same rules as sw/dtgc/client.py: packets wait in a window until acknowledged, and go again if refused
// for a bad CRC or if the link goes quiet.
enum { P_HELLO = 0x01, P_CLEAR = 0x10, P_RECT = 0x12, P_SWAP = 0x14, P_TRIANGLE = 0x17, P_TEX_SPAN = 0x18,
       P_CLEAR_DEPTH = 0x19, P_DEPTH_RECT = 0x1A, P_ACK = 0x80, P_NACK = 0x81 };
const uint8_t SYNC = 0xD7, VERSION_BYTE = 1;
const size_t WINDOW_BYTES = 1024, WINDOW_PACKETS = 64;
const double RETRY_SECONDS = 0.25, GIVE_UP_SECONDS = 5.0;

uint8_t crc8(const uint8_t *data, size_t size) {
    uint8_t crc = 0;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
    return crc;
}

uint16_t crc16(const uint8_t *data, size_t size) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < size; i++) {
        crc ^= (uint16_t)(data[i] << 8);
        for (int bit = 0; bit < 8; bit++) crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
    return crc;
}

double now_seconds() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

class Link {
public:
    bool open() {
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
        char text[16] = "7654";
        GetEnvironmentVariableA("DTGC_PORT", text, sizeof text);
        sockaddr_in address = {};
        address.sin_family = AF_INET;
        address.sin_port = htons((u_short)atoi(text));
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        sock_ = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (sock_ == INVALID_SOCKET) return false;
        if (connect(sock_, (sockaddr *)&address, sizeof address) != 0) {
            closesocket(sock_);
            sock_ = INVALID_SOCKET;
            return false;
        }
        BOOL on = TRUE;
        setsockopt(sock_, IPPROTO_TCP, TCP_NODELAY, (const char *)&on, sizeof on);
        send_packet(P_HELLO, nullptr, 0);
        return flush();
    }

    void close_link() {
        if (sock_ != INVALID_SOCKET) {
            flush();
            closesocket(sock_);
            sock_ = INVALID_SOCKET;
        }
    }

    bool alive() const { return !broken_; }

    void send_packet(uint8_t kind, const void *payload, size_t size) {
        if (broken_ || sock_ == INVALID_SOCKET) return;
        std::vector<uint8_t> packet(9 + size);
        packet[0] = SYNC;
        packet[1] = VERSION_BYTE;
        packet[2] = kind;
        packet[3] = seq_;
        packet[4] = (uint8_t)(size & 0xFF);
        packet[5] = (uint8_t)(size >> 8);
        packet[6] = crc8(&packet[1], 5);
        if (size) memcpy(&packet[7], payload, size);
        uint16_t crc = crc16(&packet[1], 6 + size);
        packet[7 + size] = (uint8_t)(crc & 0xFF);
        packet[8 + size] = (uint8_t)(crc >> 8);

        while (!pending_.empty() && (in_flight_ + packet.size() > WINDOW_BYTES || pending_.size() >= WINDOW_PACKETS)) {
            if (!service()) return;
        }
        if (pending_.empty()) last_progress_ = now_seconds();
        in_flight_ += packet.size();
        write_all(packet.data(), packet.size());
        pending_.push_back({seq_, std::move(packet)});
        seq_++;
        last_send_ = now_seconds();
    }

    bool flush() {
        while (!pending_.empty()) {
            if (!service()) return false;
        }
        return !broken_;
    }

private:
    struct Sent {
        uint8_t seq;
        std::vector<uint8_t> bytes;
    };

    void write_all(const uint8_t *data, size_t size) {
        while (size) {
            int done = send(sock_, (const char *)data, (int)std::min<size_t>(size, 65536), 0);
            if (done <= 0) {
                broken_ = true;
                return;
            }
            data += done;
            size -= (size_t)done;
        }
    }

    void resend_from(uint8_t seq) {
        size_t start = 0;
        for (size_t i = 0; i < pending_.size(); i++) {
            if (pending_[i].seq == seq) {
                start = i;
                break;
            }
        }
        for (size_t i = start; i < pending_.size(); i++) write_all(pending_[i].bytes.data(), pending_[i].bytes.size());
        last_send_ = now_seconds();
    }

    void on_reply(uint8_t kind, uint8_t arg, uint8_t detail) {
        if (kind == P_ACK) {
            bool known = false;
            for (const Sent &sent : pending_) known = known || sent.seq == arg;
            if (!known) return;
            while (!pending_.empty()) {
                uint8_t seq = pending_.front().seq;
                in_flight_ -= pending_.front().bytes.size();
                pending_.pop_front();
                if (seq == arg) break;
            }
            last_progress_ = now_seconds();
        } else if (kind == P_NACK) {
            if (detail == 1 || (!pending_.empty() && now_seconds() - last_send_ > 0.02)) resend_from(arg);
        }
    }

    void feed(uint8_t byte) {
        incoming_.push_back(byte);
        for (;;) {
            size_t skip = 0;
            while (skip < incoming_.size() && incoming_[skip] != SYNC) skip++;
            incoming_.erase(incoming_.begin(), incoming_.begin() + (std::ptrdiff_t)skip);
            if (incoming_.size() < 7) return;
            if (crc8(&incoming_[1], 5) != incoming_[6]) {
                incoming_.erase(incoming_.begin());
                continue;
            }
            size_t size = (size_t)incoming_[4] | ((size_t)incoming_[5] << 8);
            if (incoming_.size() < 9 + size) return;
            uint16_t crc = crc16(&incoming_[1], 6 + size);
            bool good = incoming_[7 + size] == (crc & 0xFF) && incoming_[8 + size] == (crc >> 8);
            if (good && size == 2) on_reply(incoming_[2], incoming_[7], incoming_[8]);
            incoming_.erase(incoming_.begin(), incoming_.begin() + (std::ptrdiff_t)(9 + size));
        }
    }

    bool service() {
        fd_set readable;
        FD_ZERO(&readable);
        FD_SET(sock_, &readable);
        timeval wait = {0, 10000};
        if (select(0, &readable, nullptr, nullptr, &wait) > 0) {
            uint8_t data[4096];
            int got = recv(sock_, (char *)data, sizeof data, 0);
            if (got <= 0) {
                broken_ = true;
                return false;
            }
            for (int i = 0; i < got; i++) feed(data[i]);
        }
        double now = now_seconds();
        if (!pending_.empty() && now - last_progress_ > GIVE_UP_SECONDS) {
            broken_ = true;
            return false;
        }
        if (!pending_.empty() && now - last_send_ > RETRY_SECONDS) resend_from(pending_.front().seq);
        return true;
    }

    SOCKET sock_ = INVALID_SOCKET;
    uint8_t seq_ = 0;
    size_t in_flight_ = 0;
    bool broken_ = false;
    double last_progress_ = 0, last_send_ = 0;
    std::deque<Sent> pending_;
    std::vector<uint8_t> incoming_;
};

// Shared COM helpers -----------------------------------------------------------------------------------------
#define COUNTED_UNKNOWN(iid_check)                                                  \
    STDMETHODIMP QueryInterface(REFIID riid, void **out) override {                 \
        if (riid == IID_IUnknown || iid_check) {                                    \
            *out = this;                                                            \
            AddRef();                                                               \
            return S_OK;                                                            \
        }                                                                           \
        *out = nullptr;                                                             \
        return E_NOINTERFACE;                                                       \
    }                                                                               \
    STDMETHODIMP_(ULONG) AddRef() override { return (ULONG)InterlockedIncrement(&refs_); } \
    STDMETHODIMP_(ULONG) Release() override {                                       \
        LONG left = InterlockedDecrement(&refs_);                                   \
        if (left == 0) delete this;                                                 \
        return (ULONG)left;                                                         \
    }                                                                               \
    volatile LONG refs_ = 1;

template <class T>
void replace_ref(T *&slot, T *value) {
    if (value) value->AddRef();
    if (slot) slot->Release();
    slot = value;
}

class Device;

// Buffers ----------------------------------------------------------------------------------------------------
class VertexBuffer : public IDirect3DVertexBuffer9 {
public:
    VertexBuffer(IDirect3DDevice9 *device, UINT size, DWORD fvf, D3DPOOL pool, DWORD usage)
        : device_(device), data(size), fvf_(fvf), pool_(pool), usage_(usage) {}
    COUNTED_UNKNOWN(riid == IID_IDirect3DVertexBuffer9 || riid == IID_IDirect3DResource9)
    STDMETHODIMP GetDevice(IDirect3DDevice9 **out) override {
        *out = device_;
        device_->AddRef();
        return D3D_OK;
    }
    STDMETHODIMP_(D3DRESOURCETYPE) GetType() override { return D3DRTYPE_VERTEXBUFFER; }
    STDMETHODIMP Lock(UINT offset, UINT size, void **out, DWORD) override {
        if (offset > data.size() || (size && offset + size > data.size())) return D3DERR_INVALIDCALL;
        *out = data.data() + offset;
        return D3D_OK;
    }
    STDMETHODIMP Unlock() override { return D3D_OK; }
    STDMETHODIMP GetDesc(D3DVERTEXBUFFER_DESC *desc) override {
        desc->Format = D3DFMT_VERTEXDATA;
        desc->Type = D3DRTYPE_VERTEXBUFFER;
        desc->Usage = usage_;
        desc->Pool = pool_;
        desc->Size = (UINT)data.size();
        desc->FVF = fvf_;
        return D3D_OK;
    }
#include "IDirect3DVertexBuffer9_stubs.inc"
    IDirect3DDevice9 *device_;
    std::vector<uint8_t> data;
    DWORD fvf_;
    D3DPOOL pool_;
    DWORD usage_;
};

class IndexBuffer : public IDirect3DIndexBuffer9 {
public:
    IndexBuffer(IDirect3DDevice9 *device, UINT size, D3DFORMAT format, D3DPOOL pool, DWORD usage)
        : device_(device), data(size), format_(format), pool_(pool), usage_(usage) {}
    COUNTED_UNKNOWN(riid == IID_IDirect3DIndexBuffer9 || riid == IID_IDirect3DResource9)
    STDMETHODIMP GetDevice(IDirect3DDevice9 **out) override {
        *out = device_;
        device_->AddRef();
        return D3D_OK;
    }
    STDMETHODIMP_(D3DRESOURCETYPE) GetType() override { return D3DRTYPE_INDEXBUFFER; }
    STDMETHODIMP Lock(UINT offset, UINT size, void **out, DWORD) override {
        if (offset > data.size() || (size && offset + size > data.size())) return D3DERR_INVALIDCALL;
        *out = data.data() + offset;
        return D3D_OK;
    }
    STDMETHODIMP Unlock() override { return D3D_OK; }
    STDMETHODIMP GetDesc(D3DINDEXBUFFER_DESC *desc) override {
        desc->Format = format_;
        desc->Type = D3DRTYPE_INDEXBUFFER;
        desc->Usage = usage_;
        desc->Pool = pool_;
        desc->Size = (UINT)data.size();
        return D3D_OK;
    }
#include "IDirect3DIndexBuffer9_stubs.inc"
    IDirect3DDevice9 *device_;
    std::vector<uint8_t> data;
    D3DFORMAT format_;
    D3DPOOL pool_;
    DWORD usage_;
};

// Textures ---------------------------------------------------------------------------------------------------
int bytes_per_texel(D3DFORMAT format) {
    switch (format) {
        case D3DFMT_A8R8G8B8:
        case D3DFMT_X8R8G8B8:
            return 4;
        case D3DFMT_R5G6B5:
        case D3DFMT_X1R5G5B5:
        case D3DFMT_A1R5G5B5:
            return 2;
        case D3DFMT_L8:
            return 1;
        default:
            return 0;
    }
}

uint8_t rrrgggbb(int r, int g, int b) { return (uint8_t)((r & 0xE0) | ((g >> 3) & 0x1C) | (b >> 6)); }

class Texture : public IDirect3DTexture9 {
public:
    Texture(IDirect3DDevice9 *device, UINT width, UINT height, UINT levels, D3DFORMAT format, D3DPOOL pool, DWORD usage)
        : device_(device), format_(format), pool_(pool), usage_(usage) {
        UINT w = width, h = height;
        for (UINT i = 0; levels == 0 || i < levels; i++) {
            Level level;
            level.width = w;
            level.height = h;
            level.pitch = w * (UINT)bytes_per_texel(format);
            level.data.resize((size_t)level.pitch * h);
            levels_.push_back(std::move(level));
            if (w == 1 && h == 1) break;
            w = std::max(1u, w / 2);
            h = std::max(1u, h / 2);
        }
    }
    COUNTED_UNKNOWN(riid == IID_IDirect3DTexture9 || riid == IID_IDirect3DBaseTexture9 || riid == IID_IDirect3DResource9)
    STDMETHODIMP GetDevice(IDirect3DDevice9 **out) override {
        *out = device_;
        device_->AddRef();
        return D3D_OK;
    }
    STDMETHODIMP_(D3DRESOURCETYPE) GetType() override { return D3DRTYPE_TEXTURE; }
    STDMETHODIMP_(DWORD) GetLevelCount() override { return (DWORD)levels_.size(); }
    STDMETHODIMP GetLevelDesc(UINT level, D3DSURFACE_DESC *desc) override {
        if (level >= levels_.size()) return D3DERR_INVALIDCALL;
        desc->Format = format_;
        desc->Type = D3DRTYPE_SURFACE;
        desc->Usage = usage_;
        desc->Pool = pool_;
        desc->MultiSampleType = D3DMULTISAMPLE_NONE;
        desc->MultiSampleQuality = 0;
        desc->Width = levels_[level].width;
        desc->Height = levels_[level].height;
        return D3D_OK;
    }
    STDMETHODIMP LockRect(UINT level, D3DLOCKED_RECT *locked, const RECT *rect, DWORD) override {
        if (level >= levels_.size()) return D3DERR_INVALIDCALL;
        Level &chosen = levels_[level];
        size_t at = rect ? (size_t)rect->top * chosen.pitch + (size_t)rect->left * (size_t)bytes_per_texel(format_) : 0;
        locked->pBits = chosen.data.data() + at;
        locked->Pitch = (INT)chosen.pitch;
        return D3D_OK;
    }
    STDMETHODIMP UnlockRect(UINT level) override {
        if (level == 0) dirty = true;
        return D3D_OK;
    }
    STDMETHODIMP AddDirtyRect(const RECT *) override {
        dirty = true;
        return D3D_OK;
    }

    // The GPU's textures are square with a power of two side up to 256, and one colour number a texel.
    void upload(Link &link, int &next_row, unsigned &generation) {
        if (!dirty && uploaded_generation == generation) return;
        const Level &top = levels_[0];
        UINT longest = std::max(top.width, top.height);
        log2_side = 0;
        while ((1u << log2_side) < longest && log2_side < 8) log2_side++;
        int side = 1 << log2_side;
        if (next_row + side > 2048) {
            next_row = 0;
            generation++;
        }
        row = next_row;
        next_row += side;
        std::vector<uint8_t> payload(3 + (size_t)side);
        for (int y = 0; y < side; y++) {
            int at_row = row + y;
            payload[0] = (uint8_t)(at_row & 0xFF);
            payload[1] = (uint8_t)(at_row >> 8);
            payload[2] = 0;
            const uint8_t *source = top.data.data() + (size_t)(y * top.height / side) * top.pitch;
            for (int x = 0; x < side; x++) payload[3 + (size_t)x] = texel(source, (UINT)(x * top.width / side));
            link.send_packet(P_TEX_SPAN, payload.data(), payload.size());
        }
        dirty = false;
        uploaded_generation = generation;
    }

#include "IDirect3DTexture9_stubs.inc"
    int row = 0;
    int log2_side = 0;

private:
    struct Level {
        UINT width = 0, height = 0, pitch = 0;
        std::vector<uint8_t> data;
    };

    uint8_t texel(const uint8_t *line, UINT x) const {
        switch (format_) {
            case D3DFMT_A8R8G8B8:
            case D3DFMT_X8R8G8B8:
                return rrrgggbb(line[x * 4 + 2], line[x * 4 + 1], line[x * 4]);
            case D3DFMT_R5G6B5: {
                unsigned v = (unsigned)line[x * 2] | ((unsigned)line[x * 2 + 1] << 8);
                return rrrgggbb((v >> 8) & 0xF8, (v >> 3) & 0xFC, (v << 3) & 0xF8);
            }
            case D3DFMT_X1R5G5B5:
            case D3DFMT_A1R5G5B5: {
                unsigned v = (unsigned)line[x * 2] | ((unsigned)line[x * 2 + 1] << 8);
                return rrrgggbb((v >> 7) & 0xF8, (v >> 2) & 0xF8, (v << 3) & 0xF8);
            }
            default:
                return rrrgggbb(line[x], line[x], line[x]);
        }
    }

    IDirect3DDevice9 *device_;
    D3DFORMAT format_;
    D3DPOOL pool_;
    DWORD usage_;
    std::vector<Level> levels_;
    bool dirty = true;
    unsigned uploaded_generation = ~0u;
};

// Maths ------------------------------------------------------------------------------------------------------
struct V4 {
    float x, y, z, w;
};
struct V3 {
    float x, y, z;
};

D3DMATRIX identity() {
    D3DMATRIX m = {};
    m._11 = m._22 = m._33 = m._44 = 1;
    return m;
}

D3DMATRIX multiply(const D3DMATRIX &a, const D3DMATRIX &b) {
    D3DMATRIX out;
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            float sum = 0;
            for (int k = 0; k < 4; k++) sum += a.m[i][k] * b.m[k][j];
            out.m[i][j] = sum;
        }
    return out;
}

V4 transform(const D3DMATRIX &m, float x, float y, float z) {
    return {x * m._11 + y * m._21 + z * m._31 + m._41, x * m._12 + y * m._22 + z * m._32 + m._42,
            x * m._13 + y * m._23 + z * m._33 + m._43, x * m._14 + y * m._24 + z * m._34 + m._44};
}

V3 normalised(V3 v) {
    float size = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    return size > 0 ? V3{v.x / size, v.y / size, v.z / size} : v;
}

float dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

D3DCOLORVALUE color_value(DWORD c) {
    return {((c >> 16) & 255) / 255.0f, ((c >> 8) & 255) / 255.0f, (c & 255) / 255.0f, (c >> 24) / 255.0f};
}

int to_byte(float value) { return value <= 0 ? 0 : value >= 1 ? 255 : (int)(value * 255.0f + 0.5f); }

struct Corner {
    V4 clip;       // or, for ready-made screen coordinates: x, y in back buffer pixels, z, and w unused
    float r, g, b;
    float u, v;
};

// The device -------------------------------------------------------------------------------------------------
class Device : public IDirect3DDevice9 {
public:
    Device(IDirect3D9 *owner, const D3DPRESENT_PARAMETERS &params, HWND window, D3DDEVTYPE type, DWORD flags)
        : owner_(owner), params_(params), window_(window), type_(type), flags_(flags) {
        owner_->AddRef();
        if (params_.BackBufferWidth == 0) params_.BackBufferWidth = SIDE;
        if (params_.BackBufferHeight == 0) params_.BackBufferHeight = SIDE;
        if (params_.BackBufferFormat == D3DFMT_UNKNOWN) params_.BackBufferFormat = D3DFMT_X8R8G8B8;
        world_ = view_ = projection_ = identity();
        reset_state();
    }
    ~Device() {
        replace_ref(vertices_, (IDirect3DVertexBuffer9 *)nullptr);
        replace_ref(indices_, (IDirect3DIndexBuffer9 *)nullptr);
        replace_ref(texture_, (IDirect3DBaseTexture9 *)nullptr);
        link_.close_link();
        owner_->Release();
    }
    bool connect() { return link_.open(); }

    COUNTED_UNKNOWN(riid == IID_IDirect3DDevice9)

    // Basics
    STDMETHODIMP TestCooperativeLevel() override { return link_.alive() ? D3D_OK : D3DERR_DEVICELOST; }
    STDMETHODIMP GetDirect3D(IDirect3D9 **out) override {
        *out = owner_;
        owner_->AddRef();
        return D3D_OK;
    }
    STDMETHODIMP GetCreationParameters(D3DDEVICE_CREATION_PARAMETERS *out) override {
        out->AdapterOrdinal = 0;
        out->DeviceType = type_;
        out->hFocusWindow = window_;
        out->BehaviorFlags = flags_;
        return D3D_OK;
    }
    STDMETHODIMP GetDeviceCaps(D3DCAPS9 *caps) override;
    STDMETHODIMP GetDisplayMode(UINT, D3DDISPLAYMODE *mode) override {
        mode->Width = params_.BackBufferWidth;
        mode->Height = params_.BackBufferHeight;
        mode->RefreshRate = 60;
        mode->Format = D3DFMT_X8R8G8B8;
        return D3D_OK;
    }
    STDMETHODIMP Reset(D3DPRESENT_PARAMETERS *params) override {
        params_ = *params;
        if (params_.BackBufferWidth == 0) params_.BackBufferWidth = SIDE;
        if (params_.BackBufferHeight == 0) params_.BackBufferHeight = SIDE;
        reset_state();
        return link_.alive() ? D3D_OK : D3DERR_DEVICELOST;
    }
    STDMETHODIMP Present(const RECT *, const RECT *, HWND, const RGNDATA *) override {
        link_.send_packet(P_SWAP, nullptr, 0);
        return link_.alive() ? D3D_OK : D3DERR_DEVICELOST;
    }
    STDMETHODIMP BeginScene() override { return D3D_OK; }
    STDMETHODIMP EndScene() override {
        link_.flush();
        return D3D_OK;
    }
    STDMETHODIMP_(UINT) GetAvailableTextureMem() override { return 2048 * 256; }
    STDMETHODIMP EvictManagedResources() override { return D3D_OK; }

    // Fixed-function state
    STDMETHODIMP SetTransform(D3DTRANSFORMSTATETYPE state, const D3DMATRIX *matrix) override {
        if (D3DMATRIXHANDLE_WORLD(state)) world_ = *matrix;
        else if (state == D3DTS_VIEW) view_ = *matrix;
        else if (state == D3DTS_PROJECTION) projection_ = *matrix;
        return D3D_OK;
    }
    STDMETHODIMP GetTransform(D3DTRANSFORMSTATETYPE state, D3DMATRIX *matrix) override {
        *matrix = D3DMATRIXHANDLE_WORLD(state) ? world_ : state == D3DTS_VIEW ? view_ : state == D3DTS_PROJECTION ? projection_ : identity();
        return D3D_OK;
    }
    STDMETHODIMP MultiplyTransform(D3DTRANSFORMSTATETYPE state, const D3DMATRIX *matrix) override {
        if (D3DMATRIXHANDLE_WORLD(state)) world_ = multiply(*matrix, world_);
        else if (state == D3DTS_VIEW) view_ = multiply(*matrix, view_);
        else if (state == D3DTS_PROJECTION) projection_ = multiply(*matrix, projection_);
        return D3D_OK;
    }
    STDMETHODIMP SetViewport(const D3DVIEWPORT9 *viewport) override {
        viewport_ = *viewport;
        return D3D_OK;
    }
    STDMETHODIMP GetViewport(D3DVIEWPORT9 *viewport) override {
        *viewport = viewport_;
        return D3D_OK;
    }
    STDMETHODIMP SetMaterial(const D3DMATERIAL9 *material) override {
        material_ = *material;
        return D3D_OK;
    }
    STDMETHODIMP GetMaterial(D3DMATERIAL9 *material) override {
        *material = material_;
        return D3D_OK;
    }
    STDMETHODIMP SetLight(DWORD index, const D3DLIGHT9 *light) override {
        if (index >= 8) return D3DERR_INVALIDCALL;
        lights_[index] = *light;
        return D3D_OK;
    }
    STDMETHODIMP GetLight(DWORD index, D3DLIGHT9 *light) override {
        if (index >= 8) return D3DERR_INVALIDCALL;
        *light = lights_[index];
        return D3D_OK;
    }
    STDMETHODIMP LightEnable(DWORD index, BOOL on) override {
        if (index >= 8) return D3DERR_INVALIDCALL;
        light_on_[index] = on != FALSE;
        return D3D_OK;
    }
    STDMETHODIMP GetLightEnable(DWORD index, BOOL *on) override {
        if (index >= 8) return D3DERR_INVALIDCALL;
        *on = light_on_[index];
        return D3D_OK;
    }
    STDMETHODIMP SetRenderState(D3DRENDERSTATETYPE state, DWORD value) override {
        if ((UINT)state < 256) render_[state] = value;
        return D3D_OK;
    }
    STDMETHODIMP GetRenderState(D3DRENDERSTATETYPE state, DWORD *value) override {
        *value = (UINT)state < 256 ? render_[state] : 0;
        return D3D_OK;
    }
    STDMETHODIMP SetFVF(DWORD fvf) override {
        fvf_ = fvf;
        return D3D_OK;
    }
    STDMETHODIMP GetFVF(DWORD *fvf) override {
        *fvf = fvf_;
        return D3D_OK;
    }
    // Filtering, blend stages and sampler settings are accepted so programs carry on, but the GPU has a single
    // nearest-texel lookup, so only turning a stage's colour off changes anything.
    STDMETHODIMP SetTextureStageState(DWORD stage, D3DTEXTURESTAGESTATETYPE kind, DWORD value) override {
        if (stage == 0 && kind == D3DTSS_COLOROP) color_op_ = value;
        return D3D_OK;
    }
    STDMETHODIMP SetSamplerState(DWORD, D3DSAMPLERSTATETYPE, DWORD) override { return D3D_OK; }
    STDMETHODIMP SetVertexShader(IDirect3DVertexShader9 *shader) override { return shader ? D3DERR_INVALIDCALL : D3D_OK; }
    STDMETHODIMP SetPixelShader(IDirect3DPixelShader9 *shader) override { return shader ? D3DERR_INVALIDCALL : D3D_OK; }
    STDMETHODIMP SetVertexDeclaration(IDirect3DVertexDeclaration9 *declaration) override { return declaration ? D3DERR_INVALIDCALL : D3D_OK; }

    // Resources
    STDMETHODIMP CreateVertexBuffer(UINT size, DWORD usage, DWORD fvf, D3DPOOL pool, IDirect3DVertexBuffer9 **out, HANDLE *) override {
        if (!size) return D3DERR_INVALIDCALL;
        *out = new VertexBuffer(this, size, fvf, pool, usage);
        return D3D_OK;
    }
    STDMETHODIMP CreateIndexBuffer(UINT size, DWORD usage, D3DFORMAT format, D3DPOOL pool, IDirect3DIndexBuffer9 **out, HANDLE *) override {
        if (!size || (format != D3DFMT_INDEX16 && format != D3DFMT_INDEX32)) return D3DERR_INVALIDCALL;
        *out = new IndexBuffer(this, size, format, pool, usage);
        return D3D_OK;
    }
    STDMETHODIMP CreateTexture(UINT width, UINT height, UINT levels, DWORD usage, D3DFORMAT format, D3DPOOL pool, IDirect3DTexture9 **out, HANDLE *) override {
        if (!width || !height || !bytes_per_texel(format) || (usage & D3DUSAGE_RENDERTARGET)) {
            note_unsupported("CreateTexture with this format or as a render target");
            return D3DERR_INVALIDCALL;
        }
        *out = new Texture(this, width, height, levels, format, pool, usage);
        return D3D_OK;
    }
    STDMETHODIMP SetStreamSource(UINT stream, IDirect3DVertexBuffer9 *buffer, UINT offset, UINT stride) override {
        if (stream != 0) return D3DERR_INVALIDCALL;
        replace_ref(vertices_, buffer);
        stream_offset_ = offset;
        stream_stride_ = stride;
        return D3D_OK;
    }
    STDMETHODIMP GetStreamSource(UINT stream, IDirect3DVertexBuffer9 **buffer, UINT *offset, UINT *stride) override {
        if (stream != 0) return D3DERR_INVALIDCALL;
        *buffer = vertices_;
        if (vertices_) vertices_->AddRef();
        *offset = stream_offset_;
        *stride = stream_stride_;
        return D3D_OK;
    }
    STDMETHODIMP SetIndices(IDirect3DIndexBuffer9 *buffer) override {
        replace_ref(indices_, buffer);
        return D3D_OK;
    }
    STDMETHODIMP GetIndices(IDirect3DIndexBuffer9 **buffer) override {
        *buffer = indices_;
        if (indices_) indices_->AddRef();
        return D3D_OK;
    }
    STDMETHODIMP SetTexture(DWORD stage, IDirect3DBaseTexture9 *texture) override {
        if (stage != 0) return D3D_OK;
        replace_ref(texture_, texture);
        return D3D_OK;
    }
    STDMETHODIMP GetTexture(DWORD stage, IDirect3DBaseTexture9 **texture) override {
        *texture = stage == 0 ? texture_ : nullptr;
        if (*texture) (*texture)->AddRef();
        return D3D_OK;
    }

    // Drawing
    STDMETHODIMP Clear(DWORD count, const D3DRECT *rects, DWORD flags, D3DCOLOR color, float z, DWORD) override;
    STDMETHODIMP DrawPrimitive(D3DPRIMITIVETYPE type, UINT start, UINT primitives) override {
        if (!vertices_) return D3DERR_INVALIDCALL;
        const auto *buffer = static_cast<VertexBuffer *>(vertices_);
        return draw(type, primitives, buffer->data.data() + stream_offset_ + (size_t)start * stream_stride_, stream_stride_,
                    buffer->data.size() - std::min(buffer->data.size(), stream_offset_ + (size_t)start * stream_stride_), nullptr, false, 0);
    }
    STDMETHODIMP DrawIndexedPrimitive(D3DPRIMITIVETYPE type, INT base, UINT, UINT, UINT start, UINT primitives) override {
        if (!vertices_ || !indices_) return D3DERR_INVALIDCALL;
        const auto *buffer = static_cast<VertexBuffer *>(vertices_);
        const auto *index = static_cast<IndexBuffer *>(indices_);
        bool wide = index->format_ == D3DFMT_INDEX32;
        size_t first = (size_t)start * (wide ? 4 : 2);
        if (first > index->data.size()) return D3DERR_INVALIDCALL;
        size_t base_bytes = (size_t)((std::ptrdiff_t)stream_offset_ + (std::ptrdiff_t)base * (std::ptrdiff_t)stream_stride_);
        if (base_bytes > buffer->data.size()) return D3DERR_INVALIDCALL;
        return draw(type, primitives, buffer->data.data() + base_bytes, stream_stride_, buffer->data.size() - base_bytes,
                    index->data.data() + first, wide, index->data.size() - first);
    }
    STDMETHODIMP DrawPrimitiveUP(D3DPRIMITIVETYPE type, UINT primitives, const void *data, UINT stride) override {
        replace_ref(vertices_, (IDirect3DVertexBuffer9 *)nullptr);
        return draw(type, primitives, (const uint8_t *)data, stride, SIZE_MAX, nullptr, false, 0);
    }
    STDMETHODIMP DrawIndexedPrimitiveUP(D3DPRIMITIVETYPE type, UINT, UINT, UINT primitives, const void *indices, D3DFORMAT format, const void *data, UINT stride) override {
        replace_ref(vertices_, (IDirect3DVertexBuffer9 *)nullptr);
        replace_ref(indices_, (IDirect3DIndexBuffer9 *)nullptr);
        return draw(type, primitives, (const uint8_t *)data, stride, SIZE_MAX, (const uint8_t *)indices, format == D3DFMT_INDEX32, SIZE_MAX);
    }

#include "IDirect3DDevice9_stubs.inc"

private:
    static bool D3DMATRIXHANDLE_WORLD(D3DTRANSFORMSTATETYPE state) { return state == D3DTS_WORLDMATRIX(0); }

    void reset_state() {
        memset(render_, 0, sizeof render_);
        render_[D3DRS_ZENABLE] = params_.EnableAutoDepthStencil ? D3DZB_TRUE : D3DZB_FALSE;
        render_[D3DRS_CULLMODE] = D3DCULL_CCW;
        render_[D3DRS_LIGHTING] = TRUE;
        render_[D3DRS_SHADEMODE] = D3DSHADE_GOURAUD;
        render_[D3DRS_ZWRITEENABLE] = TRUE;
        render_[D3DRS_DIFFUSEMATERIALSOURCE] = D3DMCS_COLOR1;
        render_[D3DRS_AMBIENTMATERIALSOURCE] = D3DMCS_MATERIAL;
        render_[D3DRS_EMISSIVEMATERIALSOURCE] = D3DMCS_MATERIAL;
        render_[D3DRS_COLORVERTEX] = TRUE;
        viewport_ = {0, 0, params_.BackBufferWidth, params_.BackBufferHeight, 0.0f, 1.0f};
        memset(&material_, 0, sizeof material_);
        memset(lights_, 0, sizeof lights_);
        memset(light_on_, 0, sizeof light_on_);
        color_op_ = D3DTOP_MODULATE;
        fvf_ = 0;
    }

    bool viewport_is_full() const {
        return viewport_.X == 0 && viewport_.Y == 0 && viewport_.Width == params_.BackBufferWidth &&
               viewport_.Height == params_.BackBufferHeight;
    }

    void rect_on_gpu(LONG x1, LONG y1, LONG x2, LONG y2, int out[4]) const {
        LONG w = (LONG)params_.BackBufferWidth, h = (LONG)params_.BackBufferHeight;
        out[0] = (int)(std::max(0L, x1) * SIDE / w);
        out[1] = (int)(std::max(0L, y1) * SIDE / h);
        out[2] = (int)(std::min(w, x2) * SIDE / w) - out[0];
        out[3] = (int)(std::min(h, y2) * SIDE / h) - out[1];
    }

    void light_vertex(const V3 &position, const V3 &normal, const D3DCOLORVALUE &diffuse, Corner &corner) const;
    bool make_corner(const uint8_t *vertex, Corner &corner) const;
    HRESULT draw(D3DPRIMITIVETYPE type, UINT primitives, const uint8_t *data, UINT stride, size_t data_size,
                 const uint8_t *indices, bool wide, size_t index_size);
    void triangle(Corner a, Corner b, Corner c);
    void send_screen_triangle(const Corner *points);

    Link link_;
    volatile LONG unused_ = 0;
    IDirect3D9 *owner_;
    D3DPRESENT_PARAMETERS params_;
    HWND window_;
    D3DDEVTYPE type_;
    DWORD flags_;
    D3DMATRIX world_, view_, projection_, clip_from_object_;
    D3DVIEWPORT9 viewport_;
    D3DMATERIAL9 material_;
    D3DLIGHT9 lights_[8];
    bool light_on_[8];
    DWORD render_[256];
    DWORD fvf_ = 0;
    DWORD color_op_ = D3DTOP_MODULATE;
    IDirect3DVertexBuffer9 *vertices_ = nullptr;
    IDirect3DIndexBuffer9 *indices_ = nullptr;
    IDirect3DBaseTexture9 *texture_ = nullptr;
    UINT stream_offset_ = 0, stream_stride_ = 0;
    int next_row_ = 0;
    unsigned generation_ = 0;
    // Filled in by draw() for the triangles of one call
    bool use_texture_ = false;
    bool screen_space_ = false;
    int tex_row_ = 0, tex_log2_ = 0;
    int offset_normal_ = 0, offset_diffuse_ = 0, offset_tex_ = 0;
};

HRESULT Device::Clear(DWORD count, const D3DRECT *rects, DWORD flags, D3DCOLOR color, float z, DWORD) {
    uint8_t index = rrrgggbb((color >> 16) & 255, (color >> 8) & 255, color & 255);
    uint16_t depth = (uint16_t)(std::min(1.0f, std::max(0.0f, z)) * 65535.0f + 0.5f);
    D3DRECT whole = {(LONG)viewport_.X, (LONG)viewport_.Y, (LONG)(viewport_.X + viewport_.Width), (LONG)(viewport_.Y + viewport_.Height)};
    bool everything = (count == 0 || !rects) && viewport_is_full();
    if (everything) {
        if (flags & D3DCLEAR_TARGET) link_.send_packet(P_CLEAR, &index, 1);
        if (flags & D3DCLEAR_ZBUFFER) {
            uint8_t payload[2] = {(uint8_t)(depth & 255), (uint8_t)(depth >> 8)};
            link_.send_packet(P_CLEAR_DEPTH, payload, 2);
        }
        return D3D_OK;
    }
    DWORD total = (count == 0 || !rects) ? 1 : count;
    for (DWORD i = 0; i < total; i++) {
        const D3DRECT &area = (count == 0 || !rects) ? whole : rects[i];
        int box[4];
        rect_on_gpu(area.x1, area.y1, area.x2, area.y2, box);
        if (box[2] <= 0 || box[3] <= 0) continue;
        uint8_t payload[10];
        for (int k = 0; k < 4; k++) {
            payload[k * 2] = (uint8_t)(box[k] & 255);
            payload[k * 2 + 1] = (uint8_t)(box[k] >> 8);
        }
        if (flags & D3DCLEAR_TARGET) {
            payload[8] = index;
            link_.send_packet(P_RECT, payload, 9);
        }
        if (flags & D3DCLEAR_ZBUFFER) {
            payload[8] = (uint8_t)(depth & 255);
            payload[9] = (uint8_t)(depth >> 8);
            link_.send_packet(P_DEPTH_RECT, payload, 10);
        }
    }
    return D3D_OK;
}

void Device::light_vertex(const V3 &position, const V3 &normal, const D3DCOLORVALUE &diffuse, Corner &corner) const {
    D3DCOLORVALUE ambient_light = color_value(render_[D3DRS_AMBIENT]);
    float r = material_.Emissive.r + ambient_light.r * material_.Ambient.r;
    float g = material_.Emissive.g + ambient_light.g * material_.Ambient.g;
    float b = material_.Emissive.b + ambient_light.b * material_.Ambient.b;
    for (int i = 0; i < 8; i++) {
        if (!light_on_[i]) continue;
        const D3DLIGHT9 &light = lights_[i];
        V3 to_light;
        float strength = 1;
        if (light.Type == D3DLIGHT_DIRECTIONAL) {
            to_light = normalised({-light.Direction.x, -light.Direction.y, -light.Direction.z});
        } else {
            V3 gap = {light.Position.x - position.x, light.Position.y - position.y, light.Position.z - position.z};
            float distance = std::sqrt(dot(gap, gap));
            if (light.Range > 0 && distance > light.Range) continue;
            to_light = normalised(gap);
            float fall = light.Attenuation0 + light.Attenuation1 * distance + light.Attenuation2 * distance * distance;
            strength = fall > 0 ? 1 / fall : 1;
        }
        r += ambient_light.r * 0 + light.Ambient.r * material_.Ambient.r * strength;
        g += light.Ambient.g * material_.Ambient.g * strength;
        b += light.Ambient.b * material_.Ambient.b * strength;
        float facing = dot(normal, to_light);
        if (facing > 0) {
            r += light.Diffuse.r * diffuse.r * facing * strength;
            g += light.Diffuse.g * diffuse.g * facing * strength;
            b += light.Diffuse.b * diffuse.b * facing * strength;
        }
    }
    corner.r = r;
    corner.g = g;
    corner.b = b;
}

bool Device::make_corner(const uint8_t *vertex, Corner &corner) const {
    const float *position = (const float *)vertex;
    bool has_diffuse = (fvf_ & D3DFVF_DIFFUSE) != 0;
    D3DCOLORVALUE vertex_color = {1, 1, 1, 1};
    if (has_diffuse) vertex_color = color_value(*(const DWORD *)(vertex + offset_diffuse_));

    if (screen_space_) {
        corner.clip = {position[0], position[1], position[2], position[3]};
        corner.r = vertex_color.r;
        corner.g = vertex_color.g;
        corner.b = vertex_color.b;
    } else {
        corner.clip = transform(clip_from_object_, position[0], position[1], position[2]);
        if (render_[D3DRS_LIGHTING]) {
            V3 normal = {0, 0, 0};
            if (fvf_ & D3DFVF_NORMAL) {
                const float *n = (const float *)(vertex + offset_normal_);
                normal = normalised({n[0] * world_._11 + n[1] * world_._21 + n[2] * world_._31,
                                     n[0] * world_._12 + n[1] * world_._22 + n[2] * world_._32,
                                     n[0] * world_._13 + n[1] * world_._23 + n[2] * world_._33});
            }
            V4 moved = transform(world_, position[0], position[1], position[2]);
            D3DCOLORVALUE diffuse = material_.Diffuse;
            if (has_diffuse && render_[D3DRS_COLORVERTEX] && render_[D3DRS_DIFFUSEMATERIALSOURCE] == D3DMCS_COLOR1) diffuse = vertex_color;
            light_vertex({moved.x, moved.y, moved.z}, normal, diffuse, corner);
        } else {
            corner.r = vertex_color.r;
            corner.g = vertex_color.g;
            corner.b = vertex_color.b;
        }
    }
    corner.u = corner.v = 0;
    if (offset_tex_) {
        const float *uv = (const float *)(vertex + offset_tex_);
        corner.u = uv[0];
        corner.v = uv[1];
    }
    return true;
}

HRESULT Device::draw(D3DPRIMITIVETYPE type, UINT primitives, const uint8_t *data, UINT stride, size_t data_size,
                     const uint8_t *indices, bool wide, size_t index_size) {
    DWORD position = fvf_ & D3DFVF_POSITION_MASK;
    if (position != D3DFVF_XYZ && position != D3DFVF_XYZRHW) {
        note_unsupported("a vertex format without plain XYZ or XYZRHW positions");
        return D3DERR_INVALIDCALL;
    }
    if (!stride) return D3DERR_INVALIDCALL;
    if (type != D3DPT_TRIANGLELIST && type != D3DPT_TRIANGLESTRIP && type != D3DPT_TRIANGLEFAN) {
        note_unsupported("points and lines");
        return D3D_OK;
    }
    screen_space_ = position == D3DFVF_XYZRHW;
    int offset = screen_space_ ? 16 : 12;
    offset_normal_ = offset;
    if (fvf_ & D3DFVF_NORMAL) offset += 12;
    if (fvf_ & D3DFVF_PSIZE) offset += 4;
    offset_diffuse_ = offset;
    if (fvf_ & D3DFVF_DIFFUSE) offset += 4;
    if (fvf_ & D3DFVF_SPECULAR) offset += 4;
    offset_tex_ = (fvf_ & D3DFVF_TEXCOUNT_MASK) ? offset : 0;
    clip_from_object_ = multiply(multiply(world_, view_), projection_);

    use_texture_ = false;
    if (texture_ && offset_tex_ && color_op_ != D3DTOP_DISABLE) {
        Texture *texture = static_cast<Texture *>(texture_);
        texture->upload(link_, next_row_, generation_);
        tex_row_ = texture->row;
        tex_log2_ = texture->log2_side;
        use_texture_ = true;
    }

    UINT count = type == D3DPT_TRIANGLELIST ? primitives * 3 : primitives + 2;
    auto fetch = [&](UINT i, Corner &corner) -> bool {
        UINT at = i;
        if (indices) {
            if ((size_t)(i + 1) * (wide ? 4 : 2) > index_size) return false;
            at = wide ? ((const uint32_t *)indices)[i] : ((const uint16_t *)indices)[i];
        }
        if (data_size != SIZE_MAX && ((size_t)at + 1) * stride > data_size) return false;
        return make_corner(data + (size_t)at * stride, corner);
    };
    Corner a, b, c;
    for (UINT i = 0; i < primitives; i++) {
        bool ok;
        if (type == D3DPT_TRIANGLELIST) ok = fetch(i * 3, a) && fetch(i * 3 + 1, b) && fetch(i * 3 + 2, c);
        else if (type == D3DPT_TRIANGLEFAN) ok = fetch(0, a) && fetch(i + 1, b) && fetch(i + 2, c);
        else if (i & 1) ok = fetch(i + 1, a) && fetch(i, b) && fetch(i + 2, c);  // keeps every strip triangle turning the same way
        else ok = fetch(i, a) && fetch(i + 1, b) && fetch(i + 2, c);
        if (!ok) return D3DERR_INVALIDCALL;
        if (i >= count) break;
        triangle(a, b, c);
    }
    return link_.alive() ? D3D_OK : D3DERR_DEVICELOST;
}

Corner mix(const Corner &a, const Corner &b, float t) {
    Corner out;
    out.clip = {a.clip.x + (b.clip.x - a.clip.x) * t, a.clip.y + (b.clip.y - a.clip.y) * t,
                a.clip.z + (b.clip.z - a.clip.z) * t, a.clip.w + (b.clip.w - a.clip.w) * t};
    out.r = a.r + (b.r - a.r) * t;
    out.g = a.g + (b.g - a.g) * t;
    out.b = a.b + (b.b - a.b) * t;
    out.u = a.u + (b.u - a.u) * t;
    out.v = a.v + (b.v - a.v) * t;
    return out;
}

// One side of the clip space: a corner is kept when its distance is at least 0.
float clip_distance(const V4 &p, int plane, float guard) {
    switch (plane) {
        case 0: return p.w - 1e-4f;
        case 1: return p.z;
        case 2: return p.w - p.z;
        case 3: return guard * p.w + p.x;
        case 4: return guard * p.w - p.x;
        case 5: return guard * p.w + p.y;
        default: return guard * p.w - p.y;
    }
}

void Device::triangle(Corner a, Corner b, Corner c) {
    if (render_[D3DRS_SHADEMODE] == D3DSHADE_FLAT) {
        b.r = c.r = a.r;
        b.g = c.g = a.g;
        b.b = c.b = a.b;
    }
    if (screen_space_) {
        Corner points[3] = {a, b, c};
        send_screen_triangle(points);
        return;
    }
    // Sutherland-Hodgman: cut the triangle against each plane in turn. Each cut adds at most one corner.
    float guard = viewport_is_full() ? GUARD : 1.0f;
    Corner polygon[10] = {a, b, c}, next[10];
    int size = 3;
    for (int plane = 0; plane < 7 && size; plane++) {
        int kept = 0;
        for (int i = 0; i < size; i++) {
            const Corner &now = polygon[i], &after = polygon[(i + 1) % size];
            float d0 = clip_distance(now.clip, plane, guard), d1 = clip_distance(after.clip, plane, guard);
            if (d0 >= 0) next[kept++] = now;
            if ((d0 >= 0) != (d1 >= 0)) next[kept++] = mix(now, after, d0 / (d0 - d1));
        }
        size = kept;
        memcpy(polygon, next, sizeof(Corner) * (size_t)size);
    }
    if (size < 3) return;
    float scale_x = (float)SIDE / (float)params_.BackBufferWidth, scale_y = (float)SIDE / (float)params_.BackBufferHeight;
    for (int i = 0; i < size; i++) {
        V4 &p = polygon[i].clip;
        float over = 1 / p.w;
        float x = (p.x * over + 1) * 0.5f * (float)viewport_.Width + (float)viewport_.X;
        float y = (1 - p.y * over) * 0.5f * (float)viewport_.Height + (float)viewport_.Y;
        float z = viewport_.MinZ + p.z * over * (viewport_.MaxZ - viewport_.MinZ);
        p = {x, y, z, 1};
        (void)scale_x;
        (void)scale_y;
    }
    for (int i = 1; i + 1 < size; i++) {
        Corner points[3] = {polygon[0], polygon[i], polygon[i + 1]};
        send_screen_triangle(points);
    }
}

// points hold back buffer pixel coordinates, where Direct3D 9 puts a pixel's centre on the whole number.
void Device::send_screen_triangle(const Corner *points) {
    float scale_x = (float)SIDE / (float)params_.BackBufferWidth, scale_y = (float)SIDE / (float)params_.BackBufferHeight;
    float x[3], y[3];
    for (int i = 0; i < 3; i++) {
        x[i] = (points[i].clip.x + 0.5f) * scale_x;
        y[i] = (points[i].clip.y + 0.5f) * scale_y;
        if (std::fabs(x[i]) >= 1023 || std::fabs(y[i]) >= 1023) return;
    }
    float area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0]);
    DWORD cull = render_[D3DRS_CULLMODE];
    if ((cull == D3DCULL_CCW && area < 0) || (cull == D3DCULL_CW && area > 0)) return;

    uint8_t payload[37];
    int mode = 4;  // always dither: 256 colours bands badly without it
    if (render_[D3DRS_ZENABLE] != D3DZB_FALSE) mode |= 1;
    if (use_texture_) mode |= 2;
    payload[0] = (uint8_t)mode;
    payload[1] = (uint8_t)(tex_row_ & 255);
    payload[2] = (uint8_t)(tex_row_ >> 8);
    payload[3] = (uint8_t)tex_log2_;

    // The GPU repeats a texture through a mask, but its texel numbers stop at 0 and 255, so move each triangle's
    // coordinates by whole repeats until they start at zero or above.
    float side = (float)(1 << tex_log2_);
    float shift_u = std::floor(std::min({points[0].u, points[1].u, points[2].u}));
    float shift_v = std::floor(std::min({points[0].v, points[1].v, points[2].v}));
    for (int i = 0; i < 3; i++) {
        uint8_t *out = payload + 4 + i * 11;
        int16_t sx = (int16_t)std::lround(x[i] * 16), sy = (int16_t)std::lround(y[i] * 16);
        uint16_t sz = (uint16_t)std::lround(std::min(1.0f, std::max(0.0f, points[i].clip.z)) * 65535.0f);
        memcpy(out, &sx, 2);
        memcpy(out + 2, &sy, 2);
        memcpy(out + 4, &sz, 2);
        out[6] = (uint8_t)to_byte(points[i].r);
        out[7] = (uint8_t)to_byte(points[i].g);
        out[8] = (uint8_t)to_byte(points[i].b);
        float u = (points[i].u - shift_u) * side, v = (points[i].v - shift_v) * side;
        out[9] = (uint8_t)std::min(255.0f, std::max(0.0f, u));
        out[10] = (uint8_t)std::min(255.0f, std::max(0.0f, v));
    }
    link_.send_packet(P_TRIANGLE, payload, sizeof payload);
}

HRESULT Device::GetDeviceCaps(D3DCAPS9 *caps) {
    memset(caps, 0, sizeof *caps);
    caps->DeviceType = D3DDEVTYPE_HAL;
    caps->PresentationIntervals = D3DPRESENT_INTERVAL_IMMEDIATE | D3DPRESENT_INTERVAL_ONE;
    caps->DevCaps = D3DDEVCAPS_DRAWPRIMITIVES2 | D3DDEVCAPS_HWRASTERIZATION | D3DDEVCAPS_EXECUTESYSTEMMEMORY;
    caps->PrimitiveMiscCaps = D3DPMISCCAPS_CULLNONE | D3DPMISCCAPS_CULLCW | D3DPMISCCAPS_CULLCCW;
    caps->RasterCaps = D3DPRASTERCAPS_DITHER;
    caps->ZCmpCaps = D3DPCMPCAPS_LESS;
    caps->ShadeCaps = D3DPSHADECAPS_COLORGOURAUDRGB;
    caps->TextureCaps = D3DPTEXTURECAPS_POW2 | D3DPTEXTURECAPS_SQUAREONLY;
    caps->TextureFilterCaps = D3DPTFILTERCAPS_MINFPOINT | D3DPTFILTERCAPS_MAGFPOINT;
    caps->TextureAddressCaps = D3DPTADDRESSCAPS_WRAP;
    caps->MaxTextureWidth = caps->MaxTextureHeight = 256;
    caps->MaxVertexIndex = 0xFFFFFF;
    caps->MaxPrimitiveCount = 0xFFFFFF;
    caps->MaxStreams = 1;
    caps->MaxStreamStride = 255;
    caps->MaxActiveLights = 8;
    caps->MaxSimultaneousTextures = 1;
    caps->MaxTextureBlendStages = 1;
    caps->FVFCaps = 1;
    caps->VertexProcessingCaps = D3DVTXPCAPS_DIRECTIONALLIGHTS | D3DVTXPCAPS_POSITIONALLIGHTS | D3DVTXPCAPS_MATERIALSOURCE7;
    caps->VertexShaderVersion = D3DVS_VERSION(0, 0);
    caps->PixelShaderVersion = D3DPS_VERSION(0, 0);
    return D3D_OK;
}

// The object Direct3DCreate9 returns -------------------------------------------------------------------------
bool format_supported(D3DFORMAT format) {
    return format == D3DFMT_X8R8G8B8 || format == D3DFMT_A8R8G8B8 || format == D3DFMT_R5G6B5;
}

class Direct3D : public IDirect3D9 {
public:
    COUNTED_UNKNOWN(riid == IID_IDirect3D9)
    STDMETHODIMP RegisterSoftwareDevice(void *) override { return D3DERR_INVALIDCALL; }
    STDMETHODIMP_(UINT) GetAdapterCount() override { return 1; }
    STDMETHODIMP GetAdapterIdentifier(UINT adapter, DWORD, D3DADAPTER_IDENTIFIER9 *out) override {
        if (adapter != 0) return D3DERR_INVALIDCALL;
        memset(out, 0, sizeof *out);
        strcpy_s(out->Driver, "dtgc_d3d9");
        strcpy_s(out->Description, "DTGC USB graphics (Direct3D 9 fixed-function subset)");
        strcpy_s(out->DeviceName, "\\\\.\\DTGC0");
        return D3D_OK;
    }
    STDMETHODIMP_(UINT) GetAdapterModeCount(UINT, D3DFORMAT format) override { return format_supported(format) ? 1 : 0; }
    STDMETHODIMP EnumAdapterModes(UINT, D3DFORMAT format, UINT mode, D3DDISPLAYMODE *out) override {
        if (mode != 0 || !format_supported(format)) return D3DERR_INVALIDCALL;
        *out = {SIDE, SIDE, 60, format};
        return D3D_OK;
    }
    STDMETHODIMP GetAdapterDisplayMode(UINT, D3DDISPLAYMODE *out) override {
        *out = {SIDE, SIDE, 60, D3DFMT_X8R8G8B8};
        return D3D_OK;
    }
    STDMETHODIMP CheckDeviceType(UINT, D3DDEVTYPE type, D3DFORMAT, D3DFORMAT back, BOOL) override {
        return type == D3DDEVTYPE_HAL && (back == D3DFMT_UNKNOWN || format_supported(back)) ? D3D_OK : D3DERR_NOTAVAILABLE;
    }
    STDMETHODIMP CheckDeviceFormat(UINT, D3DDEVTYPE, D3DFORMAT, DWORD usage, D3DRESOURCETYPE kind, D3DFORMAT format) override {
        if (usage & D3DUSAGE_DEPTHSTENCIL) return format == D3DFMT_D16 || format == D3DFMT_D24X8 || format == D3DFMT_D24S8 ? D3D_OK : D3DERR_NOTAVAILABLE;
        if (usage & D3DUSAGE_RENDERTARGET) return format_supported(format) && kind == D3DRTYPE_SURFACE ? D3D_OK : D3DERR_NOTAVAILABLE;
        return bytes_per_texel(format) ? D3D_OK : D3DERR_NOTAVAILABLE;
    }
    STDMETHODIMP CheckDeviceMultiSampleType(UINT, D3DDEVTYPE, D3DFORMAT, BOOL, D3DMULTISAMPLE_TYPE type, DWORD *quality) override {
        if (quality) *quality = 1;
        return type == D3DMULTISAMPLE_NONE ? D3D_OK : D3DERR_NOTAVAILABLE;
    }
    STDMETHODIMP CheckDepthStencilMatch(UINT, D3DDEVTYPE, D3DFORMAT, D3DFORMAT, D3DFORMAT) override { return D3D_OK; }
    STDMETHODIMP CheckDeviceFormatConversion(UINT, D3DDEVTYPE, D3DFORMAT, D3DFORMAT) override { return D3DERR_NOTAVAILABLE; }
    STDMETHODIMP GetDeviceCaps(UINT, D3DDEVTYPE, D3DCAPS9 *caps) override {
        Device probe(this, D3DPRESENT_PARAMETERS{}, nullptr, D3DDEVTYPE_HAL, 0);
        return probe.GetDeviceCaps(caps);
    }
    STDMETHODIMP_(HMONITOR) GetAdapterMonitor(UINT) override { return MonitorFromPoint({0, 0}, MONITOR_DEFAULTTOPRIMARY); }
    STDMETHODIMP CreateDevice(UINT adapter, D3DDEVTYPE type, HWND window, DWORD flags, D3DPRESENT_PARAMETERS *params, IDirect3DDevice9 **out) override {
        *out = nullptr;
        if (adapter != 0 || type != D3DDEVTYPE_HAL || !params) return D3DERR_INVALIDCALL;
        Device *device = new Device(this, *params, window, type, flags);
        if (!device->connect()) {  // nothing is listening: no emulator or bridge is running
            device->Release();
            return D3DERR_NOTAVAILABLE;
        }
        *out = device;
        return D3D_OK;
    }
};

}  // namespace

extern "C" {
IDirect3D9 *WINAPI Direct3DCreate9(UINT) { return new Direct3D(); }
HRESULT WINAPI Direct3DCreate9Ex(UINT, IDirect3D9Ex **out) {
    if (out) *out = nullptr;
    note_unsupported("Direct3DCreate9Ex");
    return D3DERR_NOTAVAILABLE;
}
// Debug markers that programs often import. They do nothing here.
int WINAPI D3DPERF_BeginEvent(D3DCOLOR, LPCWSTR) { return 0; }
int WINAPI D3DPERF_EndEvent() { return 0; }
void WINAPI D3DPERF_SetMarker(D3DCOLOR, LPCWSTR) {}
void WINAPI D3DPERF_SetRegion(D3DCOLOR, LPCWSTR) {}
BOOL WINAPI D3DPERF_QueryRepeatFrame() { return FALSE; }
void WINAPI D3DPERF_SetOptions(DWORD) {}
DWORD WINAPI D3DPERF_GetStatus() { return 0; }
}
