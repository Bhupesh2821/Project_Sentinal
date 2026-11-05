"""Session-only credentials and explicit, OS-backed macOS Keychain storage.

Secret values never enter subprocess arguments or plaintext configuration.
"""
import ctypes as C
from dataclasses import dataclass, field
import hashlib
import json
import sys
from threading import RLock
from sentinal.config import ROOT

class CredentialError(RuntimeError):
    pass

@dataclass(frozen=True,repr=False)
class CameraCredentials:
    endpoint:str=field(repr=False)
    username:str=field(default='',repr=False)
    password:str=field(default='',repr=False)
    def __post_init__(self):
        if any(not isinstance(v,str) for v in (self.endpoint,self.username,self.password)) or not self.endpoint or len(self.endpoint)>8192 or len(self.username)>1024 or len(self.password)>4096:
            raise ValueError('Camera credential values are invalid')
    def __repr__(self):return 'CameraCredentials(values=hidden)'

class MacKeychain:
    """Apple Generic Password API, without shell commands or a fallback file."""
    def __init__(self,service=None):
        if sys.platform!='darwin':raise CredentialError('Secure storage is unavailable. Use session-only credentials.')
        self.service=service or 'org.sentinal.camera.'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:20]
        try:
            self.cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            self.sec=C.CDLL('/System/Library/Frameworks/Security.framework/Security')
            signatures={'CFStringCreateWithCString':([C.c_void_p,C.c_char_p,C.c_uint32],C.c_void_p),
                'CFDataCreate':([C.c_void_p,C.c_void_p,C.c_long],C.c_void_p),
                'CFDictionaryCreate':([C.c_void_p,C.POINTER(C.c_void_p),C.POINTER(C.c_void_p),C.c_long,C.c_void_p,C.c_void_p],C.c_void_p),
                'CFRelease':([C.c_void_p],None),'CFDataGetLength':([C.c_void_p],C.c_long),
                'CFDataGetBytePtr':([C.c_void_p],C.c_void_p)}
            for name,(args,result) in signatures.items():
                function=getattr(self.cf,name);function.argtypes=args;function.restype=result
            for name in ('SecItemAdd','SecItemCopyMatching','SecItemUpdate'):
                function=getattr(self.sec,name);function.argtypes=[C.c_void_p,C.c_void_p];function.restype=C.c_int32
            self.sec.SecItemDelete.argtypes=[C.c_void_p];self.sec.SecItemDelete.restype=C.c_int32
        except (OSError,AttributeError):raise CredentialError('macOS Keychain could not initialize; no plaintext fallback was created.') from None

    def _constant(self,name,library=None):return C.c_void_p.in_dll(library or self.sec,name).value
    def _string(self,text):return self.cf.CFStringCreateWithCString(None,text.encode(),0x08000100)
    def _dictionary(self,pairs):
        keys=(C.c_void_p*len(pairs))(*[p[0] for p in pairs]);values=(C.c_void_p*len(pairs))(*[p[1] for p in pairs])
        return self.cf.CFDictionaryCreate(None,keys,values,len(pairs),None,None)
    def _base(self,account):
        refs=[self._string(self.service),self._string(account)]
        pairs=[(self._constant('kSecClass'),self._constant('kSecClassGenericPassword')),
               (self._constant('kSecAttrService'),refs[0]),(self._constant('kSecAttrAccount'),refs[1])]
        return pairs,refs
    def _release(self,refs):
        for ref in refs:
            if ref:self.cf.CFRelease(ref)

    def put(self,account,payload):
        pairs,refs=self._base(account)
        data=payload.encode();buffer=C.create_string_buffer(data)
        value=self.cf.CFDataCreate(None,buffer,len(data));refs.append(value)
        query=attrs=combined=None
        try:
            attributes=[(self._constant('kSecValueData'),value),
                (self._constant('kSecAttrAccessible'),self._constant('kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly'))]
            query=self._dictionary(pairs);attrs=self._dictionary(attributes);combined=self._dictionary(pairs+attributes)
            status=self.sec.SecItemAdd(combined,None)
            if status==-25299:status=self.sec.SecItemUpdate(query,attrs)
            if status:raise CredentialError('Keychain could not save camera credentials. No plaintext fallback was created.')
        finally:self._release([combined,attrs,query]+refs)

    def get(self,account):
        pairs,refs=self._base(account);query=None;result=C.c_void_p()
        try:
            pairs.extend([(self._constant('kSecReturnData'),self._constant('kCFBooleanTrue',self.cf)),
                (self._constant('kSecMatchLimit'),self._constant('kSecMatchLimitOne'))])
            query=self._dictionary(pairs);status=self.sec.SecItemCopyMatching(query,C.byref(result))
            if status==-25300:return None
            if status:raise CredentialError('Keychain could not read camera credentials. Enter them for this session.')
            length=self.cf.CFDataGetLength(result)
            if not 0<=length<=32768:raise CredentialError('The saved camera credential is invalid.')
            return C.string_at(self.cf.CFDataGetBytePtr(result),length).decode()
        finally:self._release([result.value,query]+refs)

    def delete(self,account):
        pairs,refs=self._base(account);query=self._dictionary(pairs)
        try:
            status=self.sec.SecItemDelete(query)
            if status not in (0,-25300):raise CredentialError('Keychain could not remove the credential. Unlock it and retry.')
        finally:self._release([query]+refs)

class CredentialStore:
    def __init__(self,keychain=None):
        self._session={};self._keychain=keychain;self._lock=RLock()
    def _backend(self):
        if self._keychain is None:self._keychain=MacKeychain()
        return self._keychain
    def put(self,camera_id,credentials,remember=False):
        if not isinstance(credentials,CameraCredentials):raise ValueError('Expected camera credentials')
        payload=json.dumps({'endpoint':credentials.endpoint,'username':credentials.username,'password':credentials.password},ensure_ascii=False)
        if len(payload.encode())>32768:raise ValueError('Camera credentials are too large')
        with self._lock:
            if remember:self._backend().put(camera_id,payload)
            self._session[camera_id]=credentials
    def get(self,camera_id,remember=False):
        with self._lock:
            if camera_id in self._session:return self._session[camera_id]
            if not remember:return None
            payload=self._backend().get(camera_id)
            if payload is None:return None
            try:
                values=json.loads(payload)
                if set(values)!={'endpoint','username','password'} or not all(isinstance(v,str) for v in values.values()):raise ValueError()
                credentials=CameraCredentials(**values)
            except (ValueError,TypeError):raise CredentialError('The saved camera credential is invalid. Re-enter it.') from None
            self._session[camera_id]=credentials;return credentials
    def delete(self,camera_id,remember=False):
        with self._lock:
            if remember:self._backend().delete(camera_id)
            self._session.pop(camera_id,None)
    def clear_session(self):
        with self._lock:self._session.clear()
