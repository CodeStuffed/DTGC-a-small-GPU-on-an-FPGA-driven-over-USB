// A small Direct3D 9 program with no knowledge of DTGC. It draws three test frames through whichever d3d9.dll
// Windows loads: the DTGC layer when it sits next to this file, else the real driver.
//
// Usage: test_app.exe [folder for frame_N.ppm files]   (only the real driver can read its pictures back)
#include <d3d9.h>
#include <windows.h>

#include <cmath>
#include <cstdio>
#include <string>

const int SIDE = 340;

struct Lit {
    float x, y, z, nx, ny, nz;
};
struct Screen {
    float x, y, z, rhw;
    DWORD color;
};
struct Textured {
    float x, y, z, u, v;
};

#define LIT_FVF (D3DFVF_XYZ | D3DFVF_NORMAL)
#define SCREEN_FVF (D3DFVF_XYZRHW | D3DFVF_DIFFUSE)
#define TEXTURED_FVF (D3DFVF_XYZ | D3DFVF_TEX1)

#define CHECK(call)                                                       \
    do {                                                                  \
        HRESULT result_ = (call);                                         \
        if (FAILED(result_)) {                                            \
            printf("FAIL %s: 0x%08lx\n", #call, (unsigned long)result_);  \
            return 1;                                                     \
        }                                                                 \
    } while (0)

D3DMATRIX identity() {
    D3DMATRIX m = {};
    m._11 = m._22 = m._33 = m._44 = 1;
    return m;
}

// Same formula as D3DXMatrixPerspectiveFovLH, written out so the program needs no helper library.
D3DMATRIX perspective(float fov, float aspect, float near_z, float far_z) {
    float y = 1 / std::tan(fov / 2);
    D3DMATRIX m = {};
    m._11 = y / aspect;
    m._22 = y;
    m._33 = far_z / (far_z - near_z);
    m._34 = 1;
    m._43 = -near_z * far_z / (far_z - near_z);
    return m;
}

D3DMATRIX turned(float yaw, float pitch, float z) {
    float cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
    D3DMATRIX m = identity();
    m._11 = cy;
    m._13 = -sy;
    m._21 = sp * sy;
    m._22 = cp;
    m._23 = sp * cy;
    m._31 = cp * sy;
    m._32 = -sp;
    m._33 = cp * cy;
    m._43 = z;
    return m;
}

bool save(IDirect3DDevice9 *device, const std::string &folder, int number) {
    IDirect3DSurface9 *back = nullptr, *copy = nullptr;
    if (FAILED(device->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back))) return false;
    bool ok = false;
    if (SUCCEEDED(device->CreateOffscreenPlainSurface(SIDE, SIDE, D3DFMT_X8R8G8B8, D3DPOOL_SYSTEMMEM, &copy, nullptr)) &&
        SUCCEEDED(device->GetRenderTargetData(back, copy))) {
        D3DLOCKED_RECT locked;
        if (SUCCEEDED(copy->LockRect(&locked, nullptr, D3DLOCK_READONLY))) {
            std::string path = folder + "\\frame_" + std::to_string(number) + ".ppm";
            FILE *file = nullptr;
            if (fopen_s(&file, path.c_str(), "wb") == 0) {
                fprintf(file, "P6\n%d %d\n255\n", SIDE, SIDE);
                for (int y = 0; y < SIDE; y++) {
                    const unsigned char *line = (const unsigned char *)locked.pBits + y * locked.Pitch;
                    for (int x = 0; x < SIDE; x++) {
                        fputc(line[x * 4 + 2], file);
                        fputc(line[x * 4 + 1], file);
                        fputc(line[x * 4], file);
                    }
                }
                fclose(file);
                ok = true;
            }
            copy->UnlockRect();
        }
    }
    if (copy) copy->Release();
    back->Release();
    return ok;
}

int main(int argc, char **argv) {
    std::string folder = argc > 1 ? argv[1] : "";
    WNDCLASSA kind = {};
    kind.lpfnWndProc = DefWindowProcA;
    kind.hInstance = GetModuleHandleA(nullptr);
    kind.lpszClassName = "dtgc_d3d9_test";
    RegisterClassA(&kind);
    HWND window = CreateWindowA("dtgc_d3d9_test", "DTGC D3D9 test", WS_OVERLAPPEDWINDOW, 0, 0, SIDE, SIDE, nullptr, nullptr, kind.hInstance, nullptr);

    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) {
        printf("FAIL Direct3DCreate9\n");
        return 1;
    }
    D3DADAPTER_IDENTIFIER9 who;
    CHECK(d3d->GetAdapterIdentifier(0, 0, &who));
    printf("adapter: %s\n", who.Description);

    D3DPRESENT_PARAMETERS params = {};
    params.BackBufferWidth = SIDE;
    params.BackBufferHeight = SIDE;
    params.BackBufferFormat = D3DFMT_X8R8G8B8;
    params.BackBufferCount = 1;
    params.SwapEffect = D3DSWAPEFFECT_COPY;
    params.hDeviceWindow = window;
    params.Windowed = TRUE;
    params.EnableAutoDepthStencil = TRUE;
    params.AutoDepthStencilFormat = D3DFMT_D24X8;
    params.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9 *device = nullptr;
    CHECK(d3d->CreateDevice(0, D3DDEVTYPE_HAL, window, D3DCREATE_SOFTWARE_VERTEXPROCESSING, &params, &device));

    // Frame 0: corners already in pixels, with a colour each. The test works out the exact expected picture.
    Screen flat[3] = {{40, 30, 0.5f, 1, D3DCOLOR_XRGB(255, 0, 0)},
                      {300, 90, 0.5f, 1, D3DCOLOR_XRGB(0, 255, 0)},
                      {120, 310, 0.5f, 1, D3DCOLOR_XRGB(0, 0, 255)}};
    CHECK(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE));
    CHECK(device->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_XRGB(0, 0, 85), 1.0f, 0));
    CHECK(device->BeginScene());
    CHECK(device->SetFVF(SCREEN_FVF));
    CHECK(device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, flat, sizeof(Screen)));
    CHECK(device->EndScene());
    if (!folder.empty() && !save(device, folder, 0)) printf("no read back\n");
    CHECK(device->Present(nullptr, nullptr, nullptr, nullptr));

    // Frame 1: a lit cube from vertex and index buffers, through world, view and projection matrices.
    static const float faces[6][3] = {{0, 0, -1}, {0, 0, 1}, {-1, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, -1, 0}};
    Lit corners[24];
    WORD order[36];
    for (int f = 0; f < 6; f++) {
        float nx = faces[f][0], ny = faces[f][1], nz = faces[f][2];
        float ux = ny ? 1.0f : 0.0f, uy = ny ? 0.0f : 1.0f;  // one direction along the face
        float vx = ny * 0 + uy * nz - 0 * ny, vy = 0 * nx - ux * nz, vz = ux * ny - uy * nx;  // up x normal gives the other
        static const float signs[4][2] = {{-1, -1}, {-1, 1}, {1, 1}, {1, -1}};
        for (int c = 0; c < 4; c++) {
            float a = signs[c][0], b = signs[c][1];
            corners[f * 4 + c] = {nx + vx * a + ux * b, ny + vy * a + uy * b, nz + vz * a, nx, ny, nz};
        }
        WORD base = (WORD)(f * 4);
        WORD one[6] = {base, (WORD)(base + 1), (WORD)(base + 2), base, (WORD)(base + 2), (WORD)(base + 3)};
        for (int i = 0; i < 6; i++) order[f * 6 + i] = one[i];
    }
    IDirect3DVertexBuffer9 *vertices = nullptr;
    IDirect3DIndexBuffer9 *indices = nullptr;
    void *memory = nullptr;
    CHECK(device->CreateVertexBuffer(sizeof corners, 0, LIT_FVF, D3DPOOL_MANAGED, &vertices, nullptr));
    CHECK(vertices->Lock(0, 0, &memory, 0));
    memcpy(memory, corners, sizeof corners);
    CHECK(vertices->Unlock());
    CHECK(device->CreateIndexBuffer(sizeof order, 0, D3DFMT_INDEX16, D3DPOOL_MANAGED, &indices, nullptr));
    CHECK(indices->Lock(0, 0, &memory, 0));
    memcpy(memory, order, sizeof order);
    CHECK(indices->Unlock());

    D3DMATRIX none = identity(), world = turned(0.6f, 0.5f, 5.0f), lens = perspective(0.9f, 1.0f, 0.5f, 50.0f);
    CHECK(device->SetTransform(D3DTS_WORLD, &world));
    CHECK(device->SetTransform(D3DTS_VIEW, &none));
    CHECK(device->SetTransform(D3DTS_PROJECTION, &lens));
    D3DMATERIAL9 material = {};
    material.Diffuse = {1.0f, 0.6f, 0.2f, 1.0f};
    material.Ambient = {1.0f, 0.6f, 0.2f, 1.0f};
    CHECK(device->SetMaterial(&material));
    D3DLIGHT9 light = {};
    light.Type = D3DLIGHT_DIRECTIONAL;
    light.Diffuse = {1.0f, 1.0f, 1.0f, 1.0f};
    light.Direction = {0.3f, -0.5f, 0.8f};
    CHECK(device->SetLight(0, &light));
    CHECK(device->LightEnable(0, TRUE));
    CHECK(device->SetRenderState(D3DRS_AMBIENT, D3DCOLOR_XRGB(60, 60, 60)));
    CHECK(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_CCW));
    CHECK(device->SetRenderState(D3DRS_ZENABLE, D3DZB_TRUE));
    CHECK(device->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_XRGB(0, 0, 85), 1.0f, 0));
    CHECK(device->BeginScene());
    CHECK(device->SetFVF(LIT_FVF));
    CHECK(device->SetStreamSource(0, vertices, 0, sizeof(Lit)));
    CHECK(device->SetIndices(indices));
    CHECK(device->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, 24, 0, 12));
    CHECK(device->EndScene());
    if (!folder.empty() && !save(device, folder, 1)) printf("no read back\n");
    CHECK(device->Present(nullptr, nullptr, nullptr, nullptr));

    // Frame 2: a checkered, textured square, with a clear part way through to test a viewport.
    IDirect3DTexture9 *texture = nullptr;
    CHECK(device->CreateTexture(32, 32, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_MANAGED, &texture, nullptr));
    D3DLOCKED_RECT locked;
    CHECK(texture->LockRect(0, &locked, nullptr, 0));
    for (int y = 0; y < 32; y++) {
        DWORD *line = (DWORD *)((BYTE *)locked.pBits + y * locked.Pitch);
        for (int x = 0; x < 32; x++) line[x] = ((x ^ y) & 8) ? D3DCOLOR_XRGB(255, 255, 255) : D3DCOLOR_XRGB(255, 0, 0);
    }
    CHECK(texture->UnlockRect(0));
    Textured square[4] = {{-1.5f, -1.5f, 0, 0, 2}, {-1.5f, 1.5f, 0, 0, 0}, {1.5f, -1.5f, 0, 2, 2}, {1.5f, 1.5f, 0, 2, 0}};
    D3DMATRIX flat_world = identity();
    flat_world._43 = 4.0f;
    CHECK(device->SetTransform(D3DTS_WORLD, &flat_world));
    CHECK(device->SetRenderState(D3DRS_LIGHTING, FALSE));
    CHECK(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE));
    CHECK(device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1));
    CHECK(device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE));
    CHECK(device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT));
    CHECK(device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT));
    CHECK(device->Clear(0, nullptr, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_XRGB(0, 0, 85), 1.0f, 0));
    CHECK(device->BeginScene());
    CHECK(device->SetTexture(0, texture));
    CHECK(device->SetFVF(TEXTURED_FVF));
    CHECK(device->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, square, sizeof(Textured)));
    CHECK(device->EndScene());
    if (!folder.empty() && !save(device, folder, 2)) printf("no read back\n");
    CHECK(device->Present(nullptr, nullptr, nullptr, nullptr));

    device->SetTexture(0, nullptr);
    device->SetStreamSource(0, nullptr, 0, 0);
    device->SetIndices(nullptr);
    texture->Release();
    vertices->Release();
    indices->Release();
    device->Release();
    d3d->Release();
    DestroyWindow(window);
    printf("PASS drew 3 frames\n");
    return 0;
}
