
from __future__ import print_function

import sys, os, socket, json, time
from base64 import b64encode, b64decode

import logging
_log = logging.getLogger(__name__)

class RemoteError(RuntimeError):
    pass

class AgentClient(object):
    def __init__(self, path):
        S = self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        S.connect(path)
        self.R = S.makefile('r',1)
        self.ping()

    def close(self):
        self.sock.close()

    def send(self, **D):
        B = json.dumps(D).encode('ascii')
        _log.debug("out '%s'", B)
        self.sock.sendall(B+b'\n')

    def recv(self, expect, succeed=True, error=True):
        
        B = self.R.readline()
        _log.debug("in '%s'", B)
        R = json.loads(B)
        if error and 'error' in R:
            if 'stack' in R:
                _log.error("RemoteError %s", R['stack'])
            raise RemoteError(R['error'])
        act = R.get('action','')
        if expect and  act!=expect and act not in expect:
            raise RuntimeError("Expected %s Received %s"%(expect, act))
        if succeed and not R.get('success',False):
            raise RuntimeError("Unexpected failure")
        return R

    def version(self):
        self.send(action='version')
        R = self.recv('version')
        if not R.get('success'):
            raise RuntimeError("Failed to get version")
        return R['version']

    def ping(self):
        now = time.time()
        self.send(action='ping', key=now)
        while True:
            R = self.recv(None, succeed=False, error=False)
            if R.get('action','')=='pong' and R.get('key',-1)==now:
                return
            else:
                _log.debug('Junk %s', R)

    def write(self, fname, bytes, offset=0, truncate=True):
        self.send(action='write',
                  file=fname,
                  offset=offset,
                  truncate=truncate,
                  bytes=b64encode(bytes),
                  )
        self.recv('write')

    def read(self, fname, size=None, offset=0):
        self.send(action='read',
                  file=fname,
                  offset=offset,
                  size=size)
        ret = ''
        while True:
            R = self.recv('read', succeed=False)
            ret += b64decode(R.get('bytes',''))
            if 'success' in R:
                break
        return ret

    def exec_(self, cmd, env=None, timeout=None):
        self.send(action='exec',
                  cmd=cmd,
                  env=env,
                  )
        if timeout:
            self.sock.settimeout(timeout)
        stdout, stderr = '', ''
        while True:
            try:
                R = self.recv('exec', succeed=False)
            except socket.timeout:
                self.send(action='abort')
                break
            else:
                stdout += R.get('stdout','')
                stderr += R.get('stderr','')
                if 'success' in R:
                    return {'result':R['result'],
                            'stdout':stdout,
                            'stderr':stderr,
                            'success':R['success']
                            }

        R = self.recv(('abort','exec'), succeed=False)
        R = self.recv(('abort','exec'), succeed=False)
        raise RemoteError('timeout')


def main():
    logging.basicConfig(level=logging.DEBUG)

    cmd = sys.argv[2]
    A = AgentClient(sys.argv[1])
    
    if cmd=='version':
        print('verion',A.version())

    elif cmd=='read':
        print(A.read(sys.argv[3]))

    elif cmd=='write':
        if len(sys.argv)>4 and sys.argv[4]!='-':
            with open(sys.argv[4], 'rb') as F:
                data = F.read()
        else:
             data = sys.stdin.read()
        A.write(sys.argv[3], data)

    elif cmd=='exec':
        R = A.exec_(sys.argv[3:], timeout=30)
        print(b64decode(R.get('stdout','')).decode('ascii'))
        print(b64decode(R.get('stderr','')).decode('ascii'))
        sys.exit(R.get('result'))

    else:
        print("unknown command",cmd,file=sys.stderr)

if __name__=='__main__':
    main()
