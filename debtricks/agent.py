#!/usr/bin/env python

from __future__ import print_function

import sys, socket, threading, os, fcntl, select, json, time, signal
import subprocess as SP
from base64 import b64encode, b64decode
import traceback
try:
    from cStringIO import cStringIO as StringIO
except ImportError:
    from io import StringIO

VERSION=1

def makeblock(fd, block):
    flag = fcntl.fcntl(fd.fileno(), fcntl.F_GETFD)
    if not block:
        flag |= os.O_NONBLOCK
    else:
        flag &= ~os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFD, flag)

class Agent(threading.Thread):
    def __init__(self, path):
        self.sigR, self.sigW = os.pipe()
        def handler(sig,fm):
            os.write(self.sigW, '\0')
        signal.signal(signal.SIGCHLD, handler)

        self.devnull, self.fd = 0, None
        self.fd = open(path, 'r+')
        self.devnull = os.open('/dev/null', os.O_RDWR)

    def __del__(self):
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        os.close(self.sigR)
        os.close(self.sigW)

        if(self.devnull): os.close(self.devnull)
        if(self.fd): self.fd.close()

    def send(self, **D):
        self.fd.write(json.dumps(D))
        self.fd.write(b'\n')

    def recv(self):
        B = self.fd.readline()
        while len(B)==0:
            time.sleep(0.1)
            B = self.fd.readline()
        print('read',repr(B))
        try:
            return json.loads(B)
        except ValueError:
            print('decode error',repr(B))
            raise ValueError("decode error from %s"%repr(B))

    def run(self):
        while True:
            try:
                self.loop()
            except SystemExit:
                raise
            except Exception as e:
                S=StringIO()
                traceback.print_exc(S)
                self.send(error=str(e), stack=S.getvalue(), success=False)
                time.sleep(1)

    def loop(self):
        cmd = self.recv()
        action = cmd['action']
        if action=='ping':
            self.send(action='pong', key=cmd.get('key',None), success=True)

        elif action=='version':
            self.send(action='version', version=VERSION, success=True)

        elif action=='read':
            off, size = cmd.get('offset',0), cmd.get('size')
            with open(cmd['file'], 'rb') as F:
                if not size:
                    F.seek(0,2)
                    size = F.tell()
                F.seek(off)

                while size>0:
                    buf = F.read(min(size,16384))
                    if len(buf)==0:
                        break
                    self.send(action='read', bytes=b64encode(buf), size=len(buf))
                    size -= len(buf)
                self.send(action='read', success=True)

        elif action=='write':
            with open(cmd['file'], 'wb') as F:
                F.seek(cmd.get('offset',0))
                if cmd.get('truncate',True):
                    F.truncate(F.tell())
                F.write(b64decode(cmd['bytes']))
            self.send(action='write', success=True)

        elif action=='exec':
            env = cmd.get('environ') or os.environ
            P = SP.Popen(cmd['cmd'], close_fds=True, shell=False,
                         cwd=cmd.get('cwd','/'),
                         stdin=self.devnull, stdout=SP.PIPE, stderr=SP.PIPE)
            try:
                print("Exec Begin")
                makeblock(P.stdout, False)
                makeblock(P.stderr, False)
                self.send(action='exec')
                FDs = [self.sigR, self.fd, P.stdout, P.stderr]
                while P.poll() is None:
                    print('select',FDs)
                    Rs, _Ws, _Xs = select.select(FDs, [], [])
                    print('wake', Rs)

                    for fd in Rs:
                        print('handle',fd)
                        if fd is self.fd:
                            print('exec recv cmd')
                            ecmd = self.recv()
                            print('exec recv\'d', ecmd)
                            if ecmd['action']=='abort':
                                P.kill()
                                self.send(action='abort', success=True)
                                self.send(action='exec', success=False)
                                continue
                            else:
                                raise RuntimeError('Unexpected command during exec: "%s"'%ecmd['action'])

                        elif fd is self.sigR:
                            print('SIGCHLD')
                            os.read(self.sigR, 16)
                            pass # poll() will return non-None
                        elif fd in [P.stdout, P.stderr]:
                            print('exec recv',fd)
                            #data = fd.read(1024)
                            data = os.read(fd.fileno(), 1024)
                            print('     recv\'d',repr(data))
                            if not data:
                                FDs.remove(fd)
                            src = 'stdout' if fd is P.stdout else 'stderr'
                            R = {'action':'exec', src:b64encode(data)}
                            self.send(**R)
                        else:
                            print("unknown wakeup",fd)

                print("Exec Done")
                makeblock(P.stdout, True)
                makeblock(P.stderr, True)

                self.send(action='exec',
                          stdout=b64encode(P.stdout.read()),
                          stderr=b64encode(P.stderr.read()),
                          result=P.returncode,
                          success=True)

            except:
                P.kill()
                raise

        elif action=='abort':
            self.send(action='abort', success=False)

        else:
            self.send(error="unknown command '%s'"%action, success=False)

    def readCmd(self):
        J = self.fd.readline()
        return json.loads(self.fd.readline())

def main():
    A = Agent('/dev/virtio-ports/org.qemu.guest_agent.0')
    A.run()

if __name__=='__main__':
    main()
