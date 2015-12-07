#!/usr/bin/env
"""Modifications to a CPIO file without unpacking.

Minor rant.  I find that 'cpio' has quite possible the least intuative
CLI of any common (and not so common) *nix commands.  It's unfortunate
that it was chosen as the Linux initramfs format, where simply unpacking
and repacking would lose permissions and special files unless run as root.

This script then adds files to a CPIO archive.

CPIO format ("new" ascii or "-H newc" variant) described at:
https://people.freebsd.org/~kientzle/libarchive/man/cpio.5.txt
"""

from __future__ import print_function

import sys, os.path

from struct import Struct

hdr = Struct("!6s8s8s8s8s8s8s8s8s8s8s8s8s8s")

def rpad4(FP):
    'Header and data start on 4 byte boundaries'
    P = FP.tell()&3
    if P:
        P = 4-P
        FP.seek(P,1)

def wpad4(FP, N=4):
    P = FP.tell()&(N-1)
    if P:
        P = N-P
        FP.write('\0'*P)

def alldirs(path):
    ret = []
    dname = os.path.dirname(path)
    while dname:
        ret.append(dname)
        dname = os.path.dirname(dname)
    ret.reverse() # closest to root first eg. ['a', 'a/b', 'a/b/c']
    return ret

class DOIT(object):
    def __init__(self):
        # from arguments
        self.dfiles = set()
        self.rfiles = {}
        self.afiles = []
        # from examination of the cpio file
        self.found = set()
        self.dirs = set()
        self.clear()
        self.maxinode = 0

    _flds = ['inode', 'mode', 'uid', 'gid', 'nlink',
             'mtime', 'fsize', 'major', 'minor',
             'rmajor', 'rminor']

    def clear(self):
        self.name = None
        for F in self._flds:
            setattr(self, F, 0)

    def procmds(self, cmds):
        while len(cmds):
            C = cmds[0]
            diskname = None
            archname = cmds[1]

            assert diskname is None or os.path.isfile(diskname), "Must be a file"

            if C=='add':
                diskname = cmds[2]
                cmds = cmds[3:]
                print("Add",diskname,'as',archname)
                self.afiles.append((archname,diskname))
            elif C=='replace':
                diskname = cmds[2]
                cmds = cmds[3:]
                print("Replace",archname,'with',diskname)
                self.rfiles[archname] = diskname
            elif C=='del':
                cmds = cmds[2:]
                print("Delete",archname)
                self.dfiles.add(archname)

    def readhead(self, FP):
        buf = FP.read(110)
        fld = hdr.unpack(buf)

        if fld[0] in ('070701', '070702'):
            pass
        else:
            raise RuntimeError("Not a recognised CPIO variant: '%s'"%repr(fld[0]))

        F = [fld[0]]+map(lambda v:int(v,16), fld[1:])

        for N,V in zip(self._flds, F[1:-2]):
            setattr(self, N, V)

        self.name = FP.read(F[12]).rstrip('\0')

        rpad4(FP) # read padding before content
        print("In",self.name,oct(self.mode),self.fsize)
        self.maxinode = max(self.maxinode, self.inode)

    def skipbody(self, FP):
        FP.seek(self.fsize, 1)
        rpad4(FP)

    def writehead(self, FP):
        F = map(self.__getattribute__, self._flds)+[len(self.name)+1, 0]
        F = ['070701']+["%08X"%v for v in F]

        FP.write(hdr.pack(*F))
        FP.write(self.name+'\0')
        wpad4(FP)

    def run(self, arch):
        print("Process",arch)
        with open(arch, "rb") as IF, open(arch+".tmp", "wb") as OF:
            while True:
                print(">>>",hex(IF.tell()),hex(OF.tell()))
                self.readhead(IF)
                if self.name=='TRAILER!!!' and self.fsize==0:
                    break
                self.found.add(self.name)

                if self.mode&0x4000:
                    assert self.fsize==0, "directory w/ bytes?"
                    self.dirs.add(self.name)
                    self.writehead(OF) # just write directories
                    print("Out directory",self.name)

                elif self.name in self.rfiles:
                    print("Replacing",self.name)
                    self.skipbody(IF)
                    name, inode = self.name, self.inode
                    self.clear()
                    self.name = name
                    self.inode = self.inode
                    with open(self.rfiles[self.name]) as D:
                        body = D.read()
                        self.mode = os.fstat(D.fileno()).st_mode
                        self.fsize = len(body)
                    self.writehead(OF)
                    OF.write(body)
                    wpad4(OF)

                elif self.name in self.dfiles:
                    print("Deleting",self.name)
                    self.skipbody(IF)

                else:
                    print("Out",self.name)
                    self.writehead(OF) # pass through
                    OF.write(IF.read(self.fsize))
                    wpad4(OF)
                    rpad4(IF)

            for aname, dname in self.afiles:
                if aname in self.found:
                    print(aname,"already exists in archive, refusing to add.  (hint, replace instead)")
                    continue

                for D in alldirs(aname):
                    if D not in self.dirs:
                        self.clear()
                        self.name = D
                        self.mode = 040755
                        self.inode = self.maxinode = self.maxinode+1
                        self.writehead(OF)

                self.clear()
                self.name = aname
                self.inode = self.maxinode = self.maxinode+1
                with open(dname, 'rb') as D:
                    body = D.read()
                    self.mode = os.fstat(D.fileno()).st_mode
                    self.fsize = len(body)
                self.writehead(OF)
                OF.write(body)
                wpad4(OF)
                print("Append",aname)

            self.clear()
            self.name = 'TRAILER!!!'
            self.nlink = 1
            self.writehead(OF)
            wpad4(OF, 256)

        os.rename(arch+".tmp", arch)
        print("Done")

if __name__=='__main__':
    C = DOIT()
    C.procmds(sys.argv[2:])
    C.run(sys.argv[1])
