import ctypes
import os


def activate_input_language(language: str) -> bool:
    """Activate a keyboard layout for the current JARVIS UI thread only."""
    if os.name != "nt":
        return False

    klid = "00000412" if language.lower().startswith("ko") else "00000409"
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.LoadKeyboardLayoutW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint)
    user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
    user32.ActivateKeyboardLayout.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    user32.ActivateKeyboardLayout.restype = ctypes.c_void_p

    # KLF_ACTIVATE | KLF_SUBSTITUTE_OK; no persistent Windows preference is changed.
    layout = user32.LoadKeyboardLayoutW(klid, 0x00000001 | 0x00000002)
    if not layout:
        return False
    return bool(user32.ActivateKeyboardLayout(layout, 0))


def set_ime_mode(window_handle: int, korean: bool) -> bool:
    """Set Hangul or alphanumeric mode for this focused edit control."""
    if os.name != "nt" or not window_handle:
        return False

    imm32 = ctypes.WinDLL("imm32", use_last_error=True)
    imm32.ImmGetContext.argtypes = (ctypes.c_void_p,)
    imm32.ImmGetContext.restype = ctypes.c_void_p
    imm32.ImmSetOpenStatus.argtypes = (ctypes.c_void_p, ctypes.c_int)
    imm32.ImmSetOpenStatus.restype = ctypes.c_int
    imm32.ImmSetConversionStatus.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint)
    imm32.ImmSetConversionStatus.restype = ctypes.c_int
    imm32.ImmReleaseContext.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    imm32.ImmReleaseContext.restype = ctypes.c_int

    hwnd = ctypes.c_void_p(window_handle)
    context = imm32.ImmGetContext(hwnd)
    if not context:
        return False
    try:
        if korean:
            opened = bool(imm32.ImmSetOpenStatus(context, 1))
            native_mode = bool(imm32.ImmSetConversionStatus(context, 0x0001, 0))
            return opened or native_mode
        alpha_mode = bool(imm32.ImmSetConversionStatus(context, 0, 0))
        closed = bool(imm32.ImmSetOpenStatus(context, 0))
        return alpha_mode or closed
    finally:
        imm32.ImmReleaseContext(hwnd, context)
