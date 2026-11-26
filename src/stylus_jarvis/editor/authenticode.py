"""Cache-only verification of the installed stable VS Code executable."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
from uuid import UUID


class _FileInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("path", w.LPCWSTR), ("file", w.HANDLE), ("known_subject", c.c_void_p)]


class _TrustData(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("policy", c.c_void_p), ("sip", c.c_void_p), ("ui", w.DWORD),
        ("revocation", w.DWORD), ("choice", w.DWORD), ("file", c.POINTER(_FileInfo)),
        ("action", w.DWORD), ("state", w.HANDLE), ("url", w.LPCWSTR), ("flags", w.DWORD),
        ("ui_context", w.DWORD), ("signature_settings", c.c_void_p),
    ]


class _ProviderCertificate(c.Structure):
    # Only the leading fields are needed to read the signer certificate.
    _fields_ = [("size", w.DWORD), ("certificate", c.c_void_p)]


def _publisher(path: Path, handle: int) -> str:
    wintrust = c.WinDLL("wintrust", winmode=0x800)
    crypt = c.WinDLL("crypt32", winmode=0x800)
    verify = wintrust.WinVerifyTrust
    verify.argtypes = (w.HWND, c.c_void_p, c.POINTER(_TrustData))
    verify.restype = w.LONG
    data_from_state = wintrust.WTHelperProvDataFromStateData
    data_from_state.argtypes = (w.HANDLE,)
    data_from_state.restype = c.c_void_p
    get_signer = wintrust.WTHelperGetProvSignerFromChain
    get_signer.argtypes = (c.c_void_p, w.DWORD, w.BOOL, w.DWORD)
    get_signer.restype = c.c_void_p
    get_certificate = wintrust.WTHelperGetProvCertFromChain
    get_certificate.argtypes = (c.c_void_p, w.DWORD)
    get_certificate.restype = c.POINTER(_ProviderCertificate)
    name = crypt.CertGetNameStringW
    name.argtypes = (c.c_void_p, w.DWORD, w.DWORD, c.c_void_p, w.LPWSTR, w.DWORD)
    name.restype = w.DWORD

    policy = (c.c_ubyte * 16).from_buffer_copy(UUID("00aac56b-cd44-11d0-8cc2-00c04fc295ee").bytes_le)
    info = _FileInfo(c.sizeof(_FileInfo), str(path), handle)
    # No UI, file subject, retain provider state and use only cached URLs.
    trust = _TrustData(size=c.sizeof(_TrustData), ui=2, choice=1, file=c.pointer(info), action=1, flags=0x1000)
    try:
        if verify(None, policy, c.byref(trust)) != 0:
            return ""
        state = data_from_state(trust.state)
        signer = get_signer(state, 0, False, 0) if state else None
        certificate = get_certificate(signer, 0) if signer else None
        if not certificate or not certificate.contents.certificate:
            return ""
        # CERT_NAME_ATTR_TYPE, with the common-name OID.
        output = c.create_unicode_buffer(256)
        if name(certificate.contents.certificate, 3, 0, c.c_char_p(b"2.5.4.3"), output, len(output)) <= 1:
            return ""
        return output.value
    finally:
        trust.action = 2  # WTD_STATEACTION_CLOSE
        verify(None, policy, c.byref(trust))


def _product_name(path: Path) -> str:
    version = c.WinDLL("version", winmode=0x800)
    size_of = version.GetFileVersionInfoSizeW
    size_of.argtypes = (w.LPCWSTR, c.POINTER(w.DWORD))
    size_of.restype = w.DWORD
    read = version.GetFileVersionInfoW
    read.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p)
    read.restype = w.BOOL
    query = version.VerQueryValueW
    query.argtypes = (c.c_void_p, w.LPCWSTR, c.POINTER(c.c_void_p), c.POINTER(w.UINT))
    query.restype = w.BOOL

    size = size_of(str(path), None)
    if not size or size > 1024 * 1024:
        return ""
    data = c.create_string_buffer(size)
    if not read(str(path), 0, size, data):
        return ""
    value = c.c_void_p()
    length = w.UINT()
    if not query(data, r"\VarFileInfo\Translation", c.byref(value), c.byref(length)) or length.value < 4:
        return ""
    languages = (w.WORD * (length.value // 2)).from_address(value.value)
    for index in range(0, len(languages) - 1, 2):
        field = f"\\StringFileInfo\\{languages[index]:04x}{languages[index + 1]:04x}\\ProductName"
        if query(data, field, c.byref(value), c.byref(length)) and value.value and length.value:
            product = c.wstring_at(value.value, length.value).rstrip("\0")
            if product == "Visual Studio Code":
                return product
    return ""


def is_stable_vscode(path: Path, handle: int) -> bool:
    return _publisher(path, handle) == "Microsoft Corporation" and _product_name(path) == "Visual Studio Code"
