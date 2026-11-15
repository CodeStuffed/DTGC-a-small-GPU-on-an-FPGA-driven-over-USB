// Starts the DTGC app from the Python runtime packed beside it, so the PC needs nothing installed.
// Built twice by scripts/package_windows.py: dtgc.exe shows only windows, and dtgc-cli.exe (with CONSOLE_VERSION) prints to the
// console and returns the command's exit code. With no arguments dtgc.exe opens the app. Any arguments go on to sw.dtgc,
// and "--watch" alone means the app, minimised until a board is plugged in.
#include <windows.h>
#include <string>

static std::wstring folder_of_this_program(std::wstring& program) {
    wchar_t path[32768];
    GetModuleFileNameW(nullptr, path, 32768);
    program = path;
    return program.substr(0, program.find_last_of(L'\\'));
}

// The command line after the program's own name, exactly as it was typed, so its quoting survives.
static std::wstring arguments_after_program() {
    const wchar_t* text = GetCommandLineW();
    bool quoted = false;
    while (*text && (quoted || (*text != L' ' && *text != L'\t'))) {
        if (*text == L'"') quoted = !quoted;
        ++text;
    }
    while (*text == L' ' || *text == L'\t') ++text;
    return text;
}

static int run() {
    std::wstring program;
    std::wstring folder = folder_of_this_program(program);
    std::wstring arguments = arguments_after_program();
#ifdef CONSOLE_VERSION
    std::wstring python = folder + L"\\runtime\\python.exe";
#else
    std::wstring python = folder + L"\\runtime\\pythonw.exe";
    if (arguments.empty()) arguments = L"app";
    else if (arguments == L"--watch") arguments = L"app --watch";
#endif
    std::wstring command = L"\"" + python + L"\" -m sw.dtgc " + arguments;
    // The app needs this to set itself up to open at login.
    SetEnvironmentVariableW(L"DTGC_EXE", program.c_str());

    STARTUPINFOW startup = {};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, TRUE, 0, nullptr, nullptr, &startup, &process)) {
        std::wstring message = L"Could not start " + python + L". Keep this program in its folder, next to the runtime folder.";
        MessageBoxW(nullptr, message.c_str(), L"DTGC", MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    DWORD code = 0;
#ifdef CONSOLE_VERSION
    WaitForSingleObject(process.hProcess, INFINITE);
    GetExitCodeProcess(process.hProcess, &code);
#endif
    CloseHandle(process.hProcess);
    return static_cast<int>(code);
}

#ifdef CONSOLE_VERSION
int wmain() { return run(); }
#else
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) { return run(); }
#endif
