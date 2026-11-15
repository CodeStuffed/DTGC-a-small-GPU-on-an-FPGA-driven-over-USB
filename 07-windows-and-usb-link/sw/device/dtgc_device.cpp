// Makes Windows list a "DTGC USB Graphics" device in Device Manager while this program runs.
//
// Usage: dtgc_device.exe [seconds]    (default: until Enter is pressed; the device goes away when it exits)
//
// This is a software device: Windows knows the name, but no driver sits behind it, so it adds nothing to
// the GPU list in Task Manager, cannot be chosen as a display, and does not speed up anything. It needs no signed
// driver. It is a first step and a test of the device name, not the real display driver (docs/windows-device.md).
#include <windows.h>
#include <swdevice.h>

#include <cstdio>
#include <cstdlib>

static HANDLE created;
static HRESULT created_result;

static void WINAPI on_created(HSWDEVICE, HRESULT result, void *, PCWSTR instance) {
    created_result = result;
    if (SUCCEEDED(result)) wprintf(L"instance id: %s\n", instance);
    SetEvent(created);
}

int main(int argc, char **argv) {
    created = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    SW_DEVICE_CREATE_INFO info = {};
    info.cbSize = sizeof info;
    info.pszInstanceId = L"DTGC0";
    info.pszzHardwareIds = L"DTGC\\USB_GPU_V1\0DTGC\\USB_GPU\0";
    info.pszzCompatibleIds = L"";
    info.pszDeviceDescription = L"DTGC USB Graphics (software device)";
    info.pszDeviceLocation = L"Created by dtgc_device.exe";
    info.CapabilityFlags = SWDeviceCapabilitiesRemovable | SWDeviceCapabilitiesSilentInstall;

    HSWDEVICE device = nullptr;
    HRESULT result = SwDeviceCreate(L"DTGC", L"HTREE\\ROOT\\0", &info, 0, nullptr, on_created, nullptr, &device);
    if (FAILED(result)) {
        printf("FAIL SwDeviceCreate: 0x%08lx\n", (unsigned long)result);
        if (result == E_ACCESSDENIED) printf("Windows refused: run this from a terminal opened as administrator.\n");
        return 1;
    }
    if (WaitForSingleObject(created, 15000) != WAIT_OBJECT_0) {
        printf("FAIL Windows did not answer within 15 seconds\n");
        SwDeviceClose(device);
        return 1;
    }
    if (FAILED(created_result)) {
        printf("FAIL creating the device: 0x%08lx\n", (unsigned long)created_result);
        SwDeviceClose(device);
        return 1;
    }
    printf("PASS the device exists. Look in Device Manager under Software devices.\n");
    fflush(stdout);
    if (argc > 1) {
        Sleep((DWORD)atoi(argv[1]) * 1000);
    } else {
        printf("Press Enter to remove it.\n");
        getchar();
    }
    SwDeviceClose(device);
    return 0;
}
